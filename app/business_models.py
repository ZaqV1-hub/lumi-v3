"""Registros de gestão da Brevia. Cada registro pertence a um cliente (tenant)."""
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import now, uid


class ClientProfile(Base):
    __tablename__ = "business_clients"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    contact_name: Mapped[str] = mapped_column(String(120), default="")
    contact_email: Mapped[str] = mapped_column(String(180), default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class Project(Base):
    __tablename__ = "business_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="em_andamento")
    summary: Mapped[str] = mapped_column(Text, default="")
    next_steps: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("tenant_id", "id"),)


class Contract(Base):
    __tablename__ = "business_contracts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="ativo")
    description: Mapped[str] = mapped_column(Text, default="")
    included_minutes: Mapped[int] = mapped_column(Integer, default=0)
    carried_minutes: Mapped[int] = mapped_column(Integer, default=0)
    opening_used_minutes: Mapped[int] = mapped_column(Integer, default=0)
    opening_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    opening_note: Mapped[str] = mapped_column(Text, default="")
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    __table_args__ = (UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "project_id"], ["business_projects.tenant_id", "business_projects.id"]))


class WorkLog(Base):
    __tablename__ = "business_work_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    contract_id: Mapped[str] = mapped_column(String(36), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    minutes: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (ForeignKeyConstraint(["tenant_id", "contract_id"], ["business_contracts.tenant_id", "business_contracts.id"]),)


class ProjectUpdate(Base):
    __tablename__ = "business_project_updates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    content: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (ForeignKeyConstraint(["tenant_id", "project_id"], ["business_projects.tenant_id", "business_projects.id"]),)


class ReportGrant(Base):
    __tablename__ = "business_report_grants"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(40), primary_key=True)
    scope: Mapped[str] = mapped_column(String(10))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ManagementChat(Base):
    __tablename__ = "business_management_chats"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class ImportedRecord(Base):
    __tablename__ = "business_imported_records"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(600), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(36))
    snapshot_json: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
