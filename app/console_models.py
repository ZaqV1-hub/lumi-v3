"""Acesso da equipe e operação do console, sem conteúdo de conversas na auditoria."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import now, uid


class ConsoleAccount(Base):
    __tablename__ = "console_accounts"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="admin")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsoleAudit(Base):
    __tablename__ = "console_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(200))
    target: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RemovedAccess(Base):
    __tablename__ = "console_removed_accesses"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    removed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ConsoleIssue(Base):
    __tablename__ = "console_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default="media")
    status: Mapped[str] = mapped_column(String(20), default="aberto")
    source: Mapped[str] = mapped_column(String(20), default="operador")
    source_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ConsoleIssueNote(Base):
    __tablename__ = "console_issue_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    issue_id: Mapped[str] = mapped_column(ForeignKey("console_issues.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
