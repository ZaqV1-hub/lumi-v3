"""Calling state only: no message outbox, audio or transcription storage."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import now, uid


class CallingChannel(Base):
    __tablename__ = 'whatsapp_calling_channels'
    phone_number_id: Mapped[str] = mapped_column(ForeignKey('whatsapp_channels.phone_number_id'), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CallPermission(Base):
    __tablename__ = 'whatsapp_call_permissions'
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), primary_key=True)
    phone_number_id: Mapped[str] = mapped_column(ForeignKey('whatsapp_channels.phone_number_id'), primary_key=True)
    recipient: Mapped[str] = mapped_column(String(40), primary_key=True)
    state: Mapped[str] = mapped_column(String(24), default='unknown')
    permanent: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    version: Mapped[int] = mapped_column(Integer, default=1)


class CallOperation(Base):
    __tablename__ = 'whatsapp_call_operations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'))
    conversation_id: Mapped[str] = mapped_column(String(36))
    operator_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    phone_number_id: Mapped[str] = mapped_column(ForeignKey('whatsapp_channels.phone_number_id'))
    recipient: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    arguments_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default='reserved')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    external_id: Mapped[str | None] = mapped_column(String(240))
    tab_token_hash: Mapped[str | None] = mapped_column(String(64))
    session_hash: Mapped[str | None] = mapped_column(String(64))
    session_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_sdp: Mapped[str | None] = mapped_column(Text)
    browser_state: Mapped[str] = mapped_column(String(24), default='new')
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    terminate_attempts: Mapped[int] = mapped_column(Integer, default=0)
    reconcile_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    public_error: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'conversation_id'], ['conversations.tenant_id', 'conversations.id']),
        UniqueConstraint('tenant_id', 'operator_id', 'idempotency_key'),
        UniqueConstraint('phone_number_id', 'kind', 'external_id'),
        Index('uq_call_active_operator', 'operator_id', unique=True,
              sqlite_where=text("active AND kind = 'call'"), postgresql_where=text("active AND kind = 'call'")),
        Index('uq_call_active_conversation', 'tenant_id', 'conversation_id', unique=True,
              sqlite_where=text("active AND kind = 'call'"), postgresql_where=text("active AND kind = 'call'")),
        Index('uq_permission_active_recipient', 'phone_number_id', 'recipient', unique=True,
              sqlite_where=text("active AND kind = 'permission'"), postgresql_where=text("active AND kind = 'permission'")),
    )


class CallEvent(Base):
    __tablename__ = 'whatsapp_call_events'
    phone_number_id: Mapped[str] = mapped_column(ForeignKey('whatsapp_channels.phone_number_id'), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'))
    operation_id: Mapped[str | None] = mapped_column(ForeignKey('whatsapp_call_operations.id'), index=True)
    external_id: Mapped[str | None] = mapped_column(String(240), index=True)
    recipient: Mapped[str | None] = mapped_column(String(40))
    answer_sdp: Mapped[str | None] = mapped_column(Text)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


CALLING_TABLES = [model.__table__ for model in (CallingChannel, CallPermission, CallOperation, CallEvent)]
