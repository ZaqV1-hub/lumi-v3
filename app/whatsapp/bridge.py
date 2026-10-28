import secrets
from sqlalchemy import event, select
from sqlalchemy.orm import Session as OrmSession
from ..db import Session
from ..models import Contact, Conversation, VisitorSession, Message, MessageAuthor
from ..media_models import MessageImage, ImageAsset
from ..spam import admission_lock
from .models import Channel, Chat, Inbox, Outbox
from .graph import send


@event.listens_for(OrmSession, "after_flush")
def queue_messages(db, _):
    # A fila é gravada na mesma transação do histórico, inclusive para operadores.
    for message in list(db.new):
        if isinstance(message, Message) and message.sender != "cliente":
            if db.get(Chat, message.conversation_id):
                db.add(Outbox(message_id=message.id))


def bind_sender(db, channel, sender, name):
    chat = db.scalar(
        select(Chat).where(
            Chat.phone_number_id == channel.phone_number_id, Chat.sender == sender
        )
    )
    if chat:
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
        if incoming.get("type") != "text":
            row.status = "unsupported"
            return
    try:
        receipt = receive_message(token, TextInput(content=incoming["text"]["body"]))
    except Exception:
        finish_inbox(external_id, "failed", "Não foi possível registrar a mensagem.")
        return
    if not receipt.get("accepted"):
        finish_inbox(external_id, "done")
        return

    def run():
        try:
            process_message(receipt)
            finish_inbox(external_id, "done")
        except Exception:
            finish_inbox(
                external_id,
                "failed",
                "Não foi possível gerar a resposta. Consulte o histórico local.",
            )

    pool.submit(run)


def finish_inbox(external_id, status, error=""):
    with Session.begin() as db:
        row = db.get(Inbox, external_id)
        row.status, row.error = status, error


def deliver_one():
    with Session.begin() as db:
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
        chat = db.get(Chat, message.conversation_id)
        channel = db.get(Channel, chat.phone_number_id)
        text = message.content
        author = db.get(MessageAuthor, mid)
        if author:
            text = f"*{author.name}*\n{text}"
        attached = db.get(MessageImage, mid)
        image = db.get(ImageAsset, attached.image_id) if attached else None
        args = (
            channel.phone_number_id,
            channel.token_env,
            chat.sender,
            text,
            image.data if image else None,
        )
    try:
        result = send(*args)
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
        item.status, item.external_id, item.error = status, result, error
    return True
