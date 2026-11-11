"""Explicit export activation and receipts; no Google access in the chat process."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class AnalyticsActivation(Base):
    __tablename__ = "analytics_activations"
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    destination: Mapped[str] = mapped_column(String(80), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(500))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),)


class AnalyticsReceipt(Base):
    __tablename__ = "analytics_receipts"
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    destination: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    __table_args__ = (ForeignKeyConstraint(["tenant_id", "destination"],
        ["analytics_activations.tenant_id", "analytics_activations.destination"]),)


def scoped_message_id(tenant_id, conversation_id):
    from .usage import scope
    current = scope.get()
    return current[2] if current and current[:2] == (tenant_id, conversation_id) else None
