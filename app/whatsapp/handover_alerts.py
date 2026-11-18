"""Avisos de fila com assunto limitado e link autenticado."""
import json
import logging
import os
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from sqlalchemy import ForeignKey, String, select, update
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, Session
from ..models import Conversation, Message, now
from ..tenant_runtime import enabled
from ..handover_summary import HandoverBrief, summarize
from .graph import send, send_handover_template
from .models import Channel, Chat, Outbox

log = logging.getLogger(__name__)
TOPICS = {
    "ingressos": "Compra ou disponibilidade de ingressos",
    "pagamento": "Pagamento ou pedido",
    "passeio_escolar": "Passeio escolar",
    "visita": "Confirmação de visita ao clube",
    "parque": "Informações sobre o clube",
    "outro": "Solicitação de apoio da equipe",
}


class HandoverAlert(Base):
    __tablename__ = "whatsapp_handover_alerts"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    phone_number_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_channels.phone_number_id", ondelete="CASCADE"))
    topic: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    external_id: Mapped[str] = mapped_column(String(240), default="")


def destination(tid):
    try:
        path = os.getenv("LUMI_HANDOVER_ALERTS_FILE")
        raw = Path(path).read_text(encoding="utf-8") if path else os.getenv("LUMI_HANDOVER_ALERTS", "{}")
        value = json.loads(raw).get(tid)
        if not isinstance(value, dict):
            return None
        host = urlsplit(value["admin_url"])
        if (host.scheme != "https" or not host.hostname or host.username or host.password
                or host.path not in {"", "/"} or host.query or host.fragment
                or not re.fullmatch(r"[1-9][0-9]{9,14}", value["recipient"])
                or not re.fullmatch(r"[0-9]{5,80}", value["phone_number_id"])
                or not re.fullmatch(r"[a-z0-9_]*", value.get("template", ""))):
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        log.error("Invalid WhatsApp handover alert configuration")
        return None


def enqueue(db, tid, cid, message_id, topic):
    chat = db.get(Chat, cid)
    config = destination(tid) if chat else None
    if not config or chat.phone_number_id != config["phone_number_id"]:
        return
    channel = db.get(Channel, chat.phone_number_id)
    if channel and channel.tenant_id == tid:
        db.add(HandoverAlert(message_id=message_id, phone_number_id=chat.phone_number_id,
                             topic=topic if topic in TOPICS else "outro"))


def deliver_alert():
    with Session.begin() as db:
        row = db.execute(select(HandoverAlert, Message, Channel)
            .join(Message, Message.id == HandoverAlert.message_id)
            .join(Channel, Channel.phone_number_id == HandoverAlert.phone_number_id)
            .join(Outbox, Outbox.message_id == Message.id)
            .where(HandoverAlert.status == "pending", Outbox.status.notin_(("pending", "sending")))
            .order_by(Message.created_at).limit(1)).first()
        if not row:
            return False
        alert, message, channel = row
        conversation = db.get(Conversation, message.conversation_id)
        config = destination(message.tenant_id)
        if (not config or channel.tenant_id != message.tenant_id or not enabled(db, message.tenant_id)
                or config["phone_number_id"] != channel.phone_number_id or not conversation
                or conversation.tenant_id != message.tenant_id or conversation.status != "aguardando"):
            alert.status = "cancelled"
            return True
        recipient = config["recipient"]
        template = config.get("template")
        recent = db.scalar(select(Message.id).join(Chat, Chat.id == Message.conversation_id).where(
            Message.tenant_id == message.tenant_id, Chat.phone_number_id == channel.phone_number_id,
            Chat.sender == recipient, Message.sender == "cliente",
            Message.created_at > now() - timedelta(hours=23),
        ).limit(1)) if not template else None
        if not (template or recent):
            alert.status = "no_window"
            return True
        mid, phone, token_env = message.id, channel.phone_number_id, channel.token_env
        link = config["admin_url"].rstrip("/") + "/admin?" + urlencode({
            "tenant": message.tenant_id, "conversation": message.conversation_id,
        }) + "#conversas"
        subject = TOPICS[alert.topic]
        changed = db.execute(update(HandoverAlert).where(
            HandoverAlert.message_id == mid, HandoverAlert.status == "pending"
        ).values(status="preparing")).rowcount
        if not changed:
            return True
        tid, cid = message.tenant_id, message.conversation_id
    brief = summarize(tid, cid, mid)
    subject = (subject + ". " + brief)[:800]
    with Session.begin() as db:
        conversation = db.get(Conversation, cid)
        channel = db.get(Channel, phone)
        if not conversation or conversation.tenant_id != tid or conversation.status != "aguardando" or not channel or channel.tenant_id != tid or destination(tid) != config:
            db.execute(update(HandoverAlert).where(HandoverAlert.message_id == mid).values(status="cancelled"))
            return True
        changed = db.execute(update(HandoverAlert).where(HandoverAlert.message_id == mid,
            HandoverAlert.status == "preparing").values(status="sending")).rowcount
        if not changed:
            return True
    external_id = ""
    status = "accepted"
    try:
        if template:
            external_id = send_handover_template(phone, token_env, recipient, template, subject, link)
        else:
            external_id = send(phone, token_env, recipient, f"Pedido de atendimento humano.\nAssunto: {subject}.\nAbra a conversa no admin: {link}")
    except RuntimeError:
        log.warning("Meta rejected a WhatsApp handover alert")
        status = "failed"
    except Exception:
        log.warning("WhatsApp handover alert delivery uncertain")
        status = "uncertain"
    with Session.begin() as db:
        db.execute(update(HandoverAlert).where(HandoverAlert.message_id == mid)
                   .values(status=status, external_id=external_id))
    return True
