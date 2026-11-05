"""Adapta mensagens do Instagram ao atendimento comum, sem conceder papéis."""
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from sqlalchemy import event, select
from sqlalchemy.orm import Session as OrmSession
from ..db import Session
from ..models import Contact, Conversation, VisitorSession, Message, MessageAuthor
from ..spam import admission_lock
from .models import Channel, Chat, Inbox, Outbox
from .graph import send, download_media
from .media import public_image


def operator_heading(name):
    # O campo text da API não recebe marcação de negrito: destacar só o nome com Unicode.
    plain = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    bold = "".join(chr(start + i) for start, length in ((0x1D5D4, 26), (0x1D5EE, 26), (0x1D7EC, 10)) for i in range(length))
    return unicodedata.normalize("NFD", name).translate(str.maketrans(plain, bold))


@event.listens_for(OrmSession, "after_flush")
def queue_messages(db, _):
    for message in list(db.new):
        if isinstance(message, Message) and message.sender != "cliente" and db.get(Chat, message.conversation_id):
            db.add(Outbox(message_id=message.id))


def bind_sender(db, channel, sender, received_at):
    chat = db.scalar(select(Chat).where(Chat.profile_id == channel.profile_id, Chat.sender == sender))
    if chat:
        previous = chat.last_incoming_at.replace(tzinfo=timezone.utc)
        chat.last_incoming_at = max(previous, received_at)
        return chat.token
    contact = Contact(tenant_id=channel.tenant_id, name=sender, role="cliente")
    db.add(contact)
    db.flush()
    conversation = Conversation(tenant_id=channel.tenant_id, contact_id=contact.id)
    db.add(conversation)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(VisitorSession(token=token, tenant_id=channel.tenant_id, conversation_id=conversation.id))
    db.add(Chat(id=conversation.id, profile_id=channel.profile_id, sender=sender, token=token, last_incoming_at=received_at))
    return token


def receive(profile_id, incoming, pool):
    with admission_lock:
        return _receive(profile_id, incoming, pool)


def _receive(profile_id, incoming, pool):
    from ..client import receive_message, process_message
    from ..schemas import TextInput
    from ..incoming import validated_file
    message = incoming.get("message", {})
    sender = str(incoming.get("sender", {}).get("id", ""))
    external_id = message.get("mid")
    if (not isinstance(external_id, str) or not 0 < len(external_id) <= 300 or not sender.isdigit()
            or sender == profile_id or message.get("is_echo") or message.get("is_deleted")
            or str(incoming.get("recipient", {}).get("id", "")) != profile_id):
        return
    try:
        received_at = datetime.fromtimestamp(float(incoming["timestamp"]) / 1000, timezone.utc)
        if received_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            return
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return
    text = message.get("text", "")
    attachments = message.get("attachments", [])
    if not isinstance(text, str) or not isinstance(attachments, list):
        return
    supported = not attachments or (len(attachments) == 1 and attachments[0].get("type") in ("image", "audio"))
    with admission_lock, Session.begin() as db:
        channel = db.get(Channel, profile_id)
        if not channel or db.get(Inbox, (profile_id, external_id)):
            return
        row = Inbox(profile_id=profile_id, external_id=external_id)
        db.add(row)
        if not supported or (not text and not attachments):
            row.status = "unsupported"
            return
        token = bind_sender(db, channel, sender, received_at)
    stage = "registro da mensagem"
    try:
        loader = None
        if attachments:
            kind = attachments[0]["type"]
            content = text or ("[Imagem enviada]" if kind == "image" else "[Áudio enviado]")

            def loader():
                nonlocal stage
                stage = "download do anexo"
                binary, mime = download_media(attachments[0].get("payload", {}).get("url", ""), kind)
                stage = "validação do anexo"
                attachment = validated_file(binary, mime, text)
                if attachment["kind"] != kind:
                    raise ValueError("Tipo de mídia inválido")
                stage = "geração da resposta"
                return attachment
        else:
            content = text
        receipt = receive_message(token, TextInput(content=content))
        if loader:
            receipt["attachment_loader"] = loader
    except Exception as exc:
        failed_receipt(profile_id, external_id, sender, text, stage, exc)
        return
    if not receipt.get("accepted") and not (loader and receipt.get("save_attachment")):
        finish(profile_id, external_id, "done")
        return

    def run():
        nonlocal stage
        try:
            if receipt.get("accepted"):
                process_message(receipt)
            else:
                from ..incoming import prepare_attachment
                prepare_attachment(receipt)
            finish(profile_id, external_id, "done")
        except Exception as exc:
            if stage in ("download do anexo", "validação do anexo"):
                failed_receipt(profile_id, external_id, sender, text, stage, exc, registered=True)
            else:
                finish(profile_id, external_id, "failed", "Não foi possível gerar a resposta. Consulte o histórico local.")

    try:
        pool.submit(run)
    except Exception:
        if receipt.get("accepted"):
            from ..spam import cancel_turn, finish as finish_pending
            cancel_turn(receipt["contact_id"], receipt["message_id"])
            finish_pending(receipt["contact_id"])
        finish(profile_id, external_id, "failed", "Não foi possível agendar a mensagem.")



def failed_receipt(profile_id, external_id, sender, text, stage, exc, registered=False):
    from ..media_models import ContactGate
    from ..tenant_runtime import enabled, allows_role
    import httpx
    # Guardar o motivo sem URLs assinadas, tokens ou corpo de erro da Meta.
    detail = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
    with admission_lock, Session.begin() as db:
        row = db.get(Inbox, (profile_id, external_id))
        row.status, row.error = "failed", f"Falha no {stage} ({detail})."
        chat = db.scalar(select(Chat).where(Chat.profile_id == profile_id, Chat.sender == sender))
        channel = db.get(Channel, profile_id)
        if not chat or not channel:
            return
        conversation = db.get(Conversation, chat.id)
        contact = db.get(Contact, conversation.contact_id)
        gate = db.get(ContactGate, contact.id)
        if gate and gate.blocked:
            return
        if not registered and stage != "registro da mensagem":
            db.add(Message(tenant_id=channel.tenant_id, conversation_id=chat.id, sender="cliente", content=text[:2000] or "[Anexo recebido: não foi possível carregar o arquivo.]"))
        if conversation.status == "lumi" and enabled(db, channel.tenant_id) and allows_role(db, channel.tenant_id, contact.role):
            db.add(Message(tenant_id=channel.tenant_id, conversation_id=chat.id, sender="sistema", content="Não consegui abrir o anexo que você enviou. Pode reenviar ou mandar sua mensagem por escrito?"))


def finish(profile_id, external_id, status, error=""):
    with Session.begin() as db:
        row = db.get(Inbox, (profile_id, external_id))
        row.status, row.error = status, error


def deliver_one():
    with admission_lock, Session.begin() as db:
        item = db.scalar(select(Outbox).where(Outbox.status == "pending").order_by(Outbox.created_at, Outbox.message_id).limit(1))
        if not item:
            return False
        item.status = "sending"
        mid = item.message_id
        message = db.get(Message, mid)
        chat = db.get(Chat, message.conversation_id)
        channel = db.get(Channel, chat.profile_id)
        if chat.last_incoming_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) - timedelta(hours=24):
            item.status, item.error = "failed", "A janela de atendimento do Instagram expirou. Aguarde nova mensagem do cliente."
            return True
        if message.tenant_id != channel.tenant_id:
            item.status, item.error = "failed", "Canal inválido para esta conversa."
            return True
        author = db.get(MessageAuthor, mid)
        text = f"{operator_heading(author.name)}\n{message.content}" if author else message.content
        try:
            args = (channel.profile_id, channel.token_env, chat.sender, text, public_image(db, mid))
        except RuntimeError as exc:
            item.status, item.error = "failed", str(exc)
            return True
    try:
        result = send(*args)
        status, error = "sent", ""
    except Exception:
        result, status, error = "", "failed", "Falha no envio ao Instagram; confira a entrega antes de reenviar."
    with Session.begin() as db:
        item = db.get(Outbox, mid)
        item.status, item.external_id, item.error = status, result, error
    return True
