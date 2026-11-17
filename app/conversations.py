from fastapi import HTTPException
from datetime import timezone
from sqlalchemy import and_, or_, select
from .models import Conversation, Message, MessageAuthor, VisitorSession
from .media_models import MessageImage
from .channels import delivery
from .incoming_models import IncomingAttachment
from .usage_models import ResponseRun
from .documents import message_document


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


def before_cursor(at, key, before):
    date, row_id = before
    return or_(at < date, and_(at == date, key < row_id))


def messages(db, tenant_id, cid, *, limit=None, before=None, period=None):
    query = select(Message).where(Message.tenant_id == tenant_id, Message.conversation_id == cid)
    if before:
        query = query.where(before_cursor(Message.created_at, Message.id, before))
    if period:
        start, end = period
        query = query.where(Message.created_at >= start, Message.created_at < end)
    if limit is None:
        rows = db.scalars(query.order_by(Message.created_at, Message.id))
    else:
        rows = reversed(db.scalars(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)).all())
    result = []
    for message in rows:
        mid = message.id
        incoming = db.get(IncomingAttachment, mid)
        document = message_document(db, tenant_id, cid, mid)
        run = db.get(ResponseRun, mid)
        receipt = delivery(db, mid)
        image = db.get(MessageImage, mid)
        author = db.get(MessageAuthor, mid)
        result.append({
            "id": mid,
            "sender": message.sender,
            "response_status": run.status if run else None,
            "delivery_error": receipt.error if receipt else "",
            "delivery": receipt.status if receipt else None,
            "content": message.content,
            "created_at": timestamp(message.created_at),
            "attachment_kind": "document" if document else incoming.kind if incoming else None,
            "attachment_name": document.filename if document else "Documento.pdf" if incoming and incoming.kind == "document" else None,
            "attachment_url": f"/api/admin/conversations/{cid}/attachments/{mid}" if document or incoming else None,
            "image_id": image.image_id if image else None,
            "name": author.name if author else None,
        })
    return result


def visitor(db, token):
    row = db.get(VisitorSession, token)
    if not row:
        raise HTTPException(401, "Inicie uma conversa")
    return row
