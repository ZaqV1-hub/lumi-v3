from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base
from ..models import now


class Channel(Base):
    __tablename__ = "whatsapp_channels"
    phone_number_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36))
    token_env: Mapped[str] = mapped_column(String(120), default="WHATSAPP_ACCESS_TOKEN")
    __table_args__ = (ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),)


class Chat(Base):
    __tablename__ = "whatsapp_chats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone_number_id: Mapped[str] = mapped_column(String(80))
    sender: Mapped[str] = mapped_column(String(40))
    token: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        ForeignKeyConstraint(["id"], ["conversations.id"]),
        ForeignKeyConstraint(
            ["phone_number_id"], ["whatsapp_channels.phone_number_id"]
        ),
        UniqueConstraint("phone_number_id", "sender"),
    )


class Inbox(Base):
    __tablename__ = "whatsapp_inbox"
    external_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    phone_number_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="processing")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DeliveryStatus(Base):
    __tablename__ = "whatsapp_delivery_status"
    external_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    phone_number_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))
    error: Mapped[str] = mapped_column(Text, default="")


class Outbox(Base):
    __tablename__ = "whatsapp_outbox"
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    external_id: Mapped[str] = mapped_column(String(240), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
