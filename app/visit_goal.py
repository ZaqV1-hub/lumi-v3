"""Objetivo de visita configurado por empresa, comprovado pela reserva externa."""
import json

from sqlalchemy import ForeignKeyConstraint, String, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import FeatureCall


class VisitGoal(Base):
    __tablename__ = "tenant_visit_goals"

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    feature: Mapped[str] = mapped_column(String(80))
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "feature"], ["tenant_features.tenant_id", "tenant_features.name"]),
    )


def _confirmed_visit(result):
    try:
        data = json.loads(result).get("data")
    except (AttributeError, ValueError):
        return False
    if not isinstance(data, dict) or data.get("ok") is not True:
        return False
    booking = data.get("booking")
    return (isinstance(booking, dict) and bool(booking.get("booking_id"))
            and booking.get("status") == "Confirmado")


def confirmed_conversations(db, tenant_id, *, conversation_id=None, incoming_id=None):
    goal = db.get(VisitGoal, tenant_id)
    if not goal:
        return set()
    calls = select(FeatureCall.conversation_id, FeatureCall.result).where(
        FeatureCall.tenant_id == tenant_id, FeatureCall.feature == goal.feature,
    )
    if conversation_id is not None:
        calls = calls.where(FeatureCall.conversation_id == conversation_id)
    if incoming_id is not None:
        calls = calls.where(FeatureCall.message_id == incoming_id)
    return {cid for cid, result in db.execute(calls) if _confirmed_visit(result)}

