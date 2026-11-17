from ..reply_delivery import may_deliver
import re
import secrets
from sqlalchemy import event, select
from sqlalchemy.orm import Session as OrmSession
from ..db import Session
from ..models import Contact, Conversation, VisitorSession, Message, MessageAuthor
from ..media_models import MessageImage, ImageAsset
from ..spam import admission_lock
from .models import Channel, Chat, Inbox, Outbox, DeliveryStatus
from .graph import send
from ..documents import message_document
from ..operator_media import FILENAMES, operator_attachment
from .follow_up import arm_after_send, may_send


@event.listens_for(OrmSession, "after_flush")
def queue_messages(db, _):
    # A fila é gravada na mesma transação do histórico, inclusive para operadores.
    for message in list(db.new):
        if isinstance(message, Message) and message.sender != "cliente":
            if db.get(Chat, message.conversation_id):
                db.add(Outbox(message_id=message.id, created_at=message.created_at))


def bind_sender(db, channel, sender, name):
    chat = db.scalar(
        select(Chat).where(
            Chat.phone_number_id == channel.phone_number_id, Chat.sender == sender
        )
    )
    if chat:
        existing = db.get(Conversation, chat.id)
        if not existing or existing.tenant_id != channel.tenant_id:
            raise RuntimeError("Vínculo de conversa incompatível com o canal.")
        return chat.token
    contact = Contact(
        tenant_id=channel.tenant_id, name=name[:120] or sender, role="cliente"
    )
    db.add(contact)
    db.flush()
    conversation = Conversation(tenant_id=channel.tenant_id, contact_id=contact.id)
    db.add(conversation)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(
        VisitorSession(
            token=token, tenant_id=channel.tenant_id, conversation_id=conversation.id
        )
    )
    db.add(
        Chat(
            id=conversation.id,
            phone_number_id=channel.phone_number_id,
            sender=sender,
            token=token,
        )
    )
    return token


def receive(phone_id, incoming, name, pool):
    with admission_lock:
        return _receive(phone_id, incoming, name, pool)


def _receive(phone_id, incoming, name, pool):
    from ..client import receive_message, process_message
    from ..schemas import TextInput

    external_id = incoming.get("id")
    sender = incoming.get("from", "")
    if not external_id or not sender.isdigit():
        return
    with admission_lock, Session.begin() as db:
        channel = db.get(Channel, phone_id)
        if not channel or db.get(Inbox, external_id):
            return
        row = Inbox(external_id=external_id, phone_number_id=phone_id)
        db.add(row)
        token = bind_sender(db, channel, sender, name)
        incoming_type = incoming.get("type")
        token_env = channel.token_env
        if incoming_type not in ("text", "image", "audio"):
            row.status = "unsupported"
            return
    try:
        loader = None
        if incoming_type == "text":
            content = incoming["text"]["body"]
        else:
            media = incoming.get(incoming_type, {})
            caption = media.get("caption", "")
            content = caption or ("[Imagem enviada]" if incoming_type == "image" else "[Áudio enviado]")

            def loader():
                from .graph import download_media
                from ..incoming import validated_file
                binary, mime = download_media(str(media.get("id", "")), token_env)
                return validated_file(binary, mime, caption)
        receipt = receive_message(token, TextInput(content=content))
        receipt["whatsapp_external_id"] = external_id
        if loader:
            receipt["attachment_loader"] = loader
    except Exception:
        finish_inbox(external_id, "failed", "Não foi possível registrar a mensagem.")
        return
    if not receipt.get("accepted") and not (loader and receipt.get("save_attachment")):
        finish_inbox(external_id, "done")
        return

    def run():
        try:
            if receipt.get("accepted"):
                process_message(receipt)
            else:
                from ..incoming import prepare_attachment
                prepare_attachment(receipt)
            finish_inbox(external_id, "done")
        except Exception:
            finish_inbox(external_id, "failed", "Não foi possível processar a mensagem. Consulte o histórico local.")

    try:
        pool.submit(run)
    except Exception:
        if receipt.get("accepted"):
            from ..spam import cancel_turn, finish
            cancel_turn(receipt["contact_id"], receipt["message_id"])
            finish(receipt["contact_id"])
        finish_inbox(external_id, "failed", "Não foi possível agendar a mensagem.")



def finish_inbox(external_id, status, error=""):
    with Session.begin() as db:
        row = db.get(Inbox, external_id)
        row.status, row.error = status, error


def whatsapp_text(text):
    return re.sub(
        r"(```[\s\S]*?```|`[^`\n]*`|https?://\S+)|"
        r"(?<![\\*])\*\*(?=\S)([^*\r\n]+?)(?<![\\\s])\*\*(?!\*)",
        lambda match: match[1] or f"*{match[2]}*",
        text,
    )


def deliver_one():
    with admission_lock, Session.begin() as db:
        item = db.scalar(
            select(Outbox)
            .where(Outbox.status == "pending")
            .order_by(Outbox.created_at, Outbox.message_id)
            .limit(1)
        )
        if not item:
            return False
        item.status = "sending"
        mid = item.message_id
        message = db.get(Message, mid)
        if not may_deliver(db, message) or not may_send(db, mid):
            item.status, item.error = "cancelled", "Resposta interrompida por mudança no atendimento."
            return True
        chat = db.get(Chat, message.conversation_id)
        channel = db.get(Channel, chat.phone_number_id) if chat else None
        if not channel or message.tenant_id != channel.tenant_id:
            item.status, item.error = "cancelled", "Canal transferido ou incompatível com esta conversa."
            return True
        text = whatsapp_text(message.content) if message.sender == "lumi" else message.content
        author = db.get(MessageAuthor, mid)
        if author:
            text = f"*{author.name}*\n{text}"
        attached = db.get(MessageImage, mid)
        image = db.get(ImageAsset, attached.image_id) if attached else None
        document = message_document(db, message.tenant_id, message.conversation_id, mid)
        attachment = {"document": (document.filename, document.data)} if document else {}
        operator_file = operator_attachment(db, message)
        if operator_file:
            attachment["operator_media"] = (operator_file.kind, FILENAMES[operator_file.kind], operator_file.data, operator_file.mime)
        args = (
            channel.phone_number_id,
            channel.token_env,
            chat.sender,
            text,
            image.data if image else None,
        )
    try:
        result = send(*args, **attachment)
        status, error = "sent", ""
    except Exception as exc:
        result, status, error = (
            "",
            "failed",
            str(exc)[:300]
            if isinstance(exc, RuntimeError)
            else "Falha de conexão com a Meta; confirme a entrega antes de reenviar.",
        )
    with Session.begin() as db:
        item = db.get(Outbox, mid)
        reported = db.get(DeliveryStatus, result) if result else None
        item.status, item.external_id, item.error = (
            reported.status if reported else status,
            result,
            reported.error if reported else error,
        )
        arm_after_send(db, mid, item.status)
    return True


def record_delivery(phone_id, delivery):
    external_id, status = delivery.get("id"), delivery.get("status")
    if not external_id or status not in ("sent", "delivered", "read", "failed"):
        return
    rank = {"sent": 1, "delivered": 2, "read": 3, "failed": 4}
    with admission_lock, Session.begin() as db:
        if not db.get(Channel, phone_id):
            return
        row = db.get(DeliveryStatus, external_id)
        if row and (row.phone_number_id != phone_id or rank[row.status] > rank[status]):
            return
        if not row:
            row = DeliveryStatus(external_id=external_id, phone_number_id=phone_id)
            db.add(row)
        error = delivery.get("errors", [{}])[0] if delivery.get("errors") else {}
        row.status = status
        row.error = (
            f"Meta {error.get('code')}: {str(error.get('title', 'Falha de entrega'))[:200]}"
            if error
            else ""
        )
        item = db.scalar(
            select(Outbox)
            .join(Message, Message.id == Outbox.message_id)
            .join(Chat, Chat.id == Message.conversation_id)
            .where(Outbox.external_id == external_id, Chat.phone_number_id == phone_id)
        )
        if item:
            item.status, item.error = row.status, row.error
