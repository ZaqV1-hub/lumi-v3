from fastapi import HTTPException
from datetime import timezone
from sqlalchemy import select
from .models import Conversation, Message, MessageAuthor, VisitorSession
from .media_models import MessageImage
from .whatsapp.models import Outbox


def timestamp(value):
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def conversation(db, tenant_id, cid):
    row = db.scalar(
        select(Conversation).where(
            Conversation.id == cid, Conversation.tenant_id == tenant_id
        )
    )
    if not row:
        raise HTTPException(404, "Conversa não encontrada")
    return row


def messages(db, tenant_id, cid):
    rows = db.scalars(
        select(Message)
        .where(Message.tenant_id == tenant_id, Message.conversation_id == cid)
        .order_by(Message.created_at, Message.id)
    )
    return [
        {
            "id": m.id,
            "sender": m.sender,
            "delivery_error": db.get(Outbox, m.id).error
            if db.get(Outbox, m.id)
            else "",
            "delivery": db.get(Outbox, m.id).status if db.get(Outbox, m.id) else None,
            "content": m.content,
            "created_at": timestamp(m.created_at),
            "image_id": db.get(MessageImage, m.id).image_id
            if db.get(MessageImage, m.id)
            else None,
            "name": (
                db.get(MessageAuthor, m.id).name
                if db.get(MessageAuthor, m.id)
                else None
            ),
        }
        for m in rows
    ]


def visitor(db, token):
    row = db.get(VisitorSession, token)
    if not row:
        raise HTTPException(401, "Inicie uma conversa")
    return row
