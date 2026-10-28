from sqlalchemy import Integer, LargeBinary, String, Text, ForeignKeyConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid


class ImageAsset(Base):
    __tablename__ = "image_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(240))
    when_to_use: Mapped[str] = mapped_column(String(200))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),)


class MessageImage(Base):
    __tablename__ = "message_images"
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_id: Mapped[str] = mapped_column(String(36))


class TenantPreferences(Base):
    __tablename__ = "tenant_preferences"
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tone: Mapped[str] = mapped_column(String(30), default="Neutro")
    length: Mapped[str] = mapped_column(String(30), default="Curto")
    style: Mapped[str] = mapped_column(String(30), default="Objetivo")
    max_pending: Mapped[int] = mapped_column(Integer, default=3)


class ContactGate(Base):
    __tablename__ = "contact_gates"
    contact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pending: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)


class ConversationControl(Base):
    __tablename__ = "conversation_controls"
    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    operator_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
