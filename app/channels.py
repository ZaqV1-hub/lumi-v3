from .whatsapp.models import Chat as WhatsAppChat, Outbox as WhatsAppOutbox
from .instagram.models import Chat as InstagramChat, Outbox as InstagramOutbox
from .instagram.comment_models import CommentJob
from sqlalchemy import select


def channel_name(db, conversation_id):
    if db.get(WhatsAppChat, conversation_id):
        return "whatsapp"
    if db.get(InstagramChat, conversation_id):
        return "instagram"
    if db.scalar(select(CommentJob.comment_id).where(CommentJob.conversation_id == conversation_id).limit(1)):
        return "instagram_comment"
    return "simulator"


def delivery(db, message_id):
    return db.get(WhatsAppOutbox, message_id) or db.get(InstagramOutbox, message_id)
