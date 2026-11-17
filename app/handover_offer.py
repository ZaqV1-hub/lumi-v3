from datetime import timedelta

from sqlalchemy import ForeignKey, String, select
from sqlalchemy.orm import Mapped, mapped_column

from .channels import channel_name, delivery
from .db import Base
from .models import Message


class HandoverOffer(Base):
    __tablename__ = "handover_offers"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    revision: Mapped[int]
    topic: Mapped[str | None] = mapped_column(String(32))


def pending_offer(db, tid, cid, revision, cutoff):
    offer = db.scalar(select(HandoverOffer).join(Message, Message.id == HandoverOffer.message_id).where(
        HandoverOffer.conversation_id == cid, HandoverOffer.revision == revision,
        Message.tenant_id == tid, Message.conversation_id == cid, Message.sender == "lumi",
        Message.created_at < cutoff, Message.created_at >= cutoff - timedelta(hours=24),
    ))
    if offer and channel_name(db, cid) in {"whatsapp", "instagram"}:
        receipt = delivery(db, offer.message_id)
        if not receipt or receipt.status not in {"sent", "delivered", "read"}:
            return None
    return offer
