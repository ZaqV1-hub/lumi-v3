"""Estado operacional no banco, independente das instruções do modelo."""
from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class TenantRuntime(Base):
    __tablename__ = "tenant_runtime"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    listed: Mapped[bool] = mapped_column(Boolean, default=True)
    lumi_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class TenantChatPolicy(Base):
    __tablename__ = "tenant_chat_policies"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    allowed_roles: Mapped[str] = mapped_column(Text)


def allows_role(db, tid, role):
    policy = db.get(TenantChatPolicy, tid)
    return policy is None or role in policy.allowed_roles.split(",")


def enabled(db, tid):
    state=db.get(TenantRuntime,tid)
    return state is None or (state.listed and state.lumi_enabled)


def listed(db, tid):
    state=db.get(TenantRuntime,tid)
    return state is None or state.listed
