"""Política de atendimento humano por empresa; horários não são decididos pelo modelo."""
import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, select, func
from sqlalchemy.orm import Mapped, mapped_column

from .access import current_user
from .db import Base, Session
from .models import now, Conversation

router = APIRouter(prefix="/api/admin/attendance")


@router.get("/waiting")
def waiting_count(user=Depends(current_user)):
    with Session() as db:
        count = db.scalar(select(func.count(func.distinct(Conversation.contact_id))).where(
            Conversation.tenant_id == user.tenant_id, Conversation.status == "aguardando"))
        return {"waiting_count": count}


class AttendancePolicy(Base):
    __tablename__ = "tenant_attendance_policies"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    hours_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(80), default="America/Sao_Paulo")
    windows: Mapped[str] = mapped_column(Text, default="[]")
    timeout_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_minutes: Mapped[int] = mapped_column(Integer, default=10)
    timeout_mode: Mapped[str] = mapped_column(String(16), default="waiting")
    phone_consent: Mapped[bool] = mapped_column(Boolean, default=False)


class AttendanceRequest(Base):
    __tablename__ = "attendance_requests"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unavailable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Window(BaseModel):
    weekday: int = Field(ge=0, le=6)
    enabled: bool = True
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")


class PolicyInput(BaseModel):
    hours_enabled: bool = False
    timezone: str = "America/Sao_Paulo"
    windows: list[Window] = Field(default_factory=list, max_length=7)
    timeout_enabled: bool = False
    timeout_minutes: int = Field(default=10, ge=1, le=120)
    timeout_mode: str = Field(default="waiting", pattern="^(both|waiting|claimed)$")
    phone_consent: bool = False

    @model_validator(mode="after")
    def valid_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Fuso horário inválido") from None
        if self.hours_enabled and not any(w.enabled for w in self.windows):
            raise ValueError("Informe ao menos um período de atendimento")
        if len({w.weekday for w in self.windows}) != len(self.windows) or any(w.enabled and w.end <= w.start for w in self.windows):
            raise ValueError("Confira os dias e horários")
        return self


def public_policy(row):
    if not row:
        return PolicyInput().model_dump()
    return {key: json.loads(row.windows) if key == "windows" else getattr(row, key) for key in PolicyInput.model_fields}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def schedule(policy, at=None):
    """Returns open and next start, including overnight periods and DST transitions."""
    if not policy or not policy.hours_enabled:
        return True, None
    at = utc(at or now())
    zone = ZoneInfo(policy.timezone)
    local_date = at.astimezone(zone).date()
    starts = []
    for offset in range(-1, 9):
        day = local_date + timedelta(days=offset)
        for window in json.loads(policy.windows):
            if not window.get("enabled", True):
                continue
            if day.weekday() != window["weekday"]:
                continue
            start = datetime.combine(day, time.fromisoformat(window["start"]), zone).astimezone(timezone.utc)
            midnight = window["end"] == "24:00"
            end_day = day + timedelta(days=midnight or window["end"] <= window["start"])
            end = datetime.combine(end_day, time(0) if midnight else time.fromisoformat(window["end"]), zone).astimezone(timezone.utc)
            if start <= at < end:
                return True, None
            if start > at:
                starts.append(start)
    return False, min(starts) if starts else None


def prompt_context(db, tid):
    row = db.get(AttendancePolicy, tid)
    if not row or not row.hours_enabled:
        return ""
    opened, next_start = schedule(row)
    return ("\nHORÁRIO DO ATENDIMENTO HUMANO (estado calculado pelo servidor): " + json.dumps({
        "timezone": row.timezone, "open_now": opened,
        "next_start": next_start.astimezone(ZoneInfo(row.timezone)).isoformat() if next_start else None,
        "weekly_periods": json.loads(row.windows),
    }) + ". A assistente continua atendendo. Se o cliente confirmar o pedido de humano fora do horário, "
        "registre normalmente: a solicitação será avisada à equipe quando o período de atendimento abrir. "
        "Explique esse horário ao confirmar o pedido, sem prometer resposta imediata ou citar a fila em toda mensagem.")


@router.get("")
def get_policy(user=Depends(current_user)):
    with Session() as db:
        return public_policy(db.get(AttendancePolicy, user.tenant_id))


@router.put("")
def save_policy(data: PolicyInput, user=Depends(current_user)):
    with Session.begin() as db:
        row = db.get(AttendancePolicy, user.tenant_id)
        if not row:
            row = AttendancePolicy(tenant_id=user.tenant_id)
            db.add(row)
        for key, value in data.model_dump().items():
            setattr(row, key, json.dumps(value) if key == "windows" else value)
    return data.model_dump()
