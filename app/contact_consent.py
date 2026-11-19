"""Consentimento explícito pelo botão recebido no webhook autenticado do canal."""
import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from .attendance import AttendancePolicy
from .db import Base
from .models import Contact, Conversation, Message, now
from .reply_delivery import ReplyPart
from .spam import control
from .phone_visibility import phone_mode

PURPOSE = "exibir telefone à equipe e permitir contato sobre o atendimento"
QUESTION = ("Você autoriza disponibilizar seu número de WhatsApp à nossa equipe para entrar em contato sobre seu atendimento? "
            "A escolha é opcional. Você pode continuar normalmente e alterar sua decisão pelos botões abaixo.")


class PhoneConsent(Base):
    __tablename__ = "phone_consents"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    nonce: Mapped[str] = mapped_column(String(64), unique=True)
    sender: Mapped[str] = mapped_column(String(32))
    phone_number_id: Mapped[str] = mapped_column(String(64))
    granted: Mapped[bool | None] = mapped_column(Boolean)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str] = mapped_column(String(150), default=PURPOSE)
    __table_args__ = (UniqueConstraint("tenant_id", "contact_id"),)


class PhoneConsentEvent(Base):
    __tablename__ = "phone_consent_events"
    external_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("phone_consents.message_id", ondelete="CASCADE"))
    granted: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def ensure_request(db, message, delivery_status):
    from .whatsapp.models import Chat
    if phone_mode(db, message.tenant_id) != "consent" or message.sender != "lumi" or delivery_status not in {"sent", "delivered", "read"}:
        return
    conversation = db.get(Conversation, message.conversation_id)
    chat = db.get(Chat, message.conversation_id)
    if not conversation or conversation.tenant_id != message.tenant_id or not chat or conversation.status not in {"lumi", "aguardando"}:
        return
    if db.scalar(select(PhoneConsent).where(PhoneConsent.tenant_id == message.tenant_id, PhoneConsent.contact_id == conversation.contact_id)):
        return
    question = Message(tenant_id=message.tenant_id, conversation_id=message.conversation_id, sender="lumi", content=QUESTION)
    db.add(question)
    db.flush()
    db.add(ReplyPart(message_id=question.id, revision=control(db, conversation.id).revision))
    db.add(PhoneConsent(message_id=question.id, tenant_id=message.tenant_id, contact_id=conversation.contact_id,
                        nonce=secrets.token_urlsafe(24), sender=chat.sender, phone_number_id=chat.phone_number_id, granted=None))


def buttons(db, mid):
    row = db.get(PhoneConsent, mid)
    if not row:
        return None
    return [{"type": "reply", "reply": {"id": f"phone:{row.nonce}:yes", "title": "Autorizar"}},
            {"type": "reply", "reply": {"id": f"phone:{row.nonce}:no", "title": "Não autorizar"}}]


def accept_button(db, tid, cid, incoming):
    from .whatsapp.models import Outbox, Chat
    value = incoming.get("interactive", {})
    if value.get("type") != "button_reply":
        return None
    parts = str(value.get("button_reply", {}).get("id", "")).split(":")
    if len(parts) != 3 or parts[0] != "phone" or parts[2] not in {"yes", "no"}:
        return None
    conversation = db.get(Conversation, cid)
    if not conversation or conversation.tenant_id != tid:
        return None
    row = db.scalar(select(PhoneConsent).where(PhoneConsent.tenant_id == tid, PhoneConsent.contact_id == conversation.contact_id,
                                            PhoneConsent.nonce == parts[1]).with_for_update())
    sent = db.get(Outbox, row.message_id) if row else None
    chat = db.get(Chat, cid)
    if row and (not chat or chat.sender != row.sender or chat.phone_number_id != row.phone_number_id):
        return None
    reference = incoming.get("context", {}).get("id")
    if not row or not sent or sent.status not in {"sent", "delivered", "read"} or not reference or reference != sent.external_id:
        return None
    external = str(incoming.get("id", ""))
    if not external or len(external) > 240:
        return None
    prior = db.get(PhoneConsentEvent, external)
    granted = parts[2] == "yes"
    if not prior:
        row.granted, row.decided_at = granted, now()
        db.add(PhoneConsentEvent(external_id=external, message_id=row.message_id, granted=granted))
    return "Autorizei compartilhar meu número com a equipe para contato sobre este atendimento." if granted else "Não autorizei compartilhar meu número com a equipe."


def public_contact(db, tid, cid):
    from .whatsapp.models import Channel, Chat
    from .whatsapp.flows.runtime import source_chat
    conversation = db.get(Conversation, cid)
    if not conversation or conversation.tenant_id != tid:
        return {"phone": None, "phone_consent": "not_requested"}
    mode = phone_mode(db, tid)
    if mode == "hidden":
        return {"phone": None, "phone_consent": "hidden"}
    if mode == "visible":
        chat = db.get(Chat, cid) or source_chat(db, tid, cid)
        channel = db.get(Channel, chat.phone_number_id) if chat else None
        phone = "+" + chat.sender if channel and channel.tenant_id == tid else None
        return {"phone": phone, "phone_consent": "not_required"}
    row = db.scalar(select(PhoneConsent).where(PhoneConsent.tenant_id == tid, PhoneConsent.contact_id == conversation.contact_id))
    state = "not_requested" if not row else "pending" if row.granted is None else "granted" if row.granted else "declined"
    phone = None
    if row and row.granted:
        chat = db.get(Chat, cid) or source_chat(db, tid, cid)
        channel = db.get(Channel, chat.phone_number_id) if chat else None
        if channel and channel.tenant_id == tid and chat.sender == row.sender and chat.phone_number_id == row.phone_number_id:
            phone = "+" + chat.sender
    return {"phone": phone, "phone_consent": state}


def prompt_context(db, tid, cid):
    if phone_mode(db, tid) != "consent":
        return ""
    state = public_contact(db, tid, cid)["phone_consent"]
    if not db.get(AttendancePolicy, tid) or state == "not_requested":
        return ""
    return ("\nCONSENTIMENTO DE TELEFONE verificado pelo servidor: " + state +
            ". A autorização refere-se a exibir o número à equipe para contato sobre o atendimento. "
            "Não afirme que uma fala genérica autorizou: somente o botão confirma ou altera a decisão. "
            "Se a pessoa quiser alterar a escolha ou responder em texto, oriente os botões da pergunta de autorização. "
            "Recusa não impede responder dúvidas, comprar ou pedir atendimento. Não pergunte novamente se já decidiu.")


def may_send_request(db, mid, tid):
    return db.get(PhoneConsent, mid) is None or phone_mode(db, tid) == "consent"
