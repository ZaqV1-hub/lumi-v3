from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid


class OnboardingObjective(Base):
    __tablename__ = "onboarding_objectives"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    updates_name: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )


class ContactProfile(Base):
    __tablename__ = "contact_profiles"
    contact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_question_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "contact_id"], ["contacts.tenant_id", "contacts.id"]),
    )


class ProfileValue(Base):
    __tablename__ = "profile_values"
    contact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "contact_id"], ["contacts.tenant_id", "contacts.id"]),
        ForeignKeyConstraint(["tenant_id", "objective_id"], ["onboarding_objectives.tenant_id", "onboarding_objectives.id"]),
    )
