from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base
from ..models import now, uid


class CommentSettings(Base):
    __tablename__ = "instagram_comment_settings"
    profile_id: Mapped[str] = mapped_column(ForeignKey("instagram_channels.profile_id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    instructions: Mapped[str] = mapped_column(Text, default="")


class CommentJob(Base):
    __tablename__ = "instagram_comments"
    profile_id: Mapped[str] = mapped_column(ForeignKey("instagram_channels.profile_id"), primary_key=True)
    comment_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    media_id: Mapped[str] = mapped_column(String(100))
    sender: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text, default="")
    reply_id: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    error: Mapped[str] = mapped_column(Text, default="")
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
