from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base
from ...models import now, uid


class FlowSession(Base):
    __tablename__ = "whatsapp_flow_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36))
    conversation_id: Mapped[str] = mapped_column(String(36), unique=True)
    source_id: Mapped[str] = mapped_column(String(36))
    phone_number_id: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    nonce: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]),
        ForeignKeyConstraint(["tenant_id", "source_id"], ["conversations.tenant_id", "conversations.id"]),
    )


class FlowLaunch(Base):
    __tablename__ = "whatsapp_flow_launches"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_flow_sessions.id"))
    flow_id: Mapped[str] = mapped_column(String(80))
    token: Mapped[str] = mapped_column(String(120))


class FlowTurn(Base):
    __tablename__ = "whatsapp_flow_turns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_flow_sessions.id"))
    nonce: Mapped[str] = mapped_column(String(64))
    question_hash: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"))
    state: Mapped[str] = mapped_column(String(24), default="preparing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("session_id", "nonce"),)


class FlowPricing(Base):
    __tablename__ = 'whatsapp_flow_pricing'
    external_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'))
    phone_number_id: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40))
    pricing_type: Mapped[str] = mapped_column(String(40))
    billable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
