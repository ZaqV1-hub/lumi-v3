from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base
from ..models import now


class Channel(Base):
    __tablename__ = "instagram_channels"
    profile_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    token_env: Mapped[str] = mapped_column(String(120))
    secret_env: Mapped[str] = mapped_column(String(120), default="INSTAGRAM_APP_SECRET")


class Chat(Base):
    __tablename__ = "instagram_chats"
    id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("instagram_channels.profile_id"))
    sender: Mapped[str] = mapped_column(String(80))
    token: Mapped[str] = mapped_column(String(64))
    last_incoming_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("profile_id", "sender"),)


class Inbox(Base):
    __tablename__ = "instagram_inbox"
    profile_id: Mapped[str] = mapped_column(ForeignKey("instagram_channels.profile_id"), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(300), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Outbox(Base):
    __tablename__ = "instagram_outbox"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    external_id: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MediaAccess(Base):
    __tablename__ = "instagram_media_access"
    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
