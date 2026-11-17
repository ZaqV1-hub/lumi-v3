from sqlalchemy import ForeignKeyConstraint, String, Text, LargeBinary, Float
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class IncomingAttachment(Base):
    __tablename__ = "incoming_attachments"
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(10))
    mime: Mapped[str] = mapped_column(String(40))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    caption: Mapped[str] = mapped_column(Text, default="")
    transcript: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="received")
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]),
        ForeignKeyConstraint(["message_id"], ["messages.id"]),)
