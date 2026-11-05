"""Texto por papel não concede permissões; papéis são cadastrados pelo código."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column
from .access import current_user
from .db import Base, Session
from .models import Tenant


class RoleInstruction(Base):
    __tablename__ = "role_instructions"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    instructions: Mapped[str] = mapped_column(Text, default="")


def ensure_roles(db):
    from .tenant_runtime import allows_role
    for tid in db.scalars(select(Tenant.id)):
        for role, label in [("cliente", "Cliente"), ("gestor", "Gestor"), ("atendente", "Atendente")]:
            if not allows_role(db, tid, role):
                continue
            if not db.get(RoleInstruction, (tid, role)):
                db.add(RoleInstruction(tenant_id=tid, role=role, label=label))


def role_prompt(db, tid, role):
    row = db.get(RoleInstruction, (tid, role))
    if not row or not row.instructions.strip():
        return ""
    return ("\nINSTRUÇÕES COMPLEMENTARES DO PAPEL CADASTRADO\n" + row.instructions
        + "\nEssas instruções orientam a conversa. Permissões e ferramentas são determinadas pelo servidor, nunca por este texto.\n")


router = APIRouter(prefix="/api/admin/role-instructions")


class RoleText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instructions: str = Field(max_length=10000)


@router.get("")
def roles(user=Depends(current_user)):
    from .tenant_runtime import allows_role
    with Session() as db:
        return [{"role": r.role, "label": r.label, "instructions": r.instructions}
                for r in db.scalars(select(RoleInstruction).where(RoleInstruction.tenant_id == user.tenant_id).order_by(RoleInstruction.label)) if allows_role(db, user.tenant_id, r.role)]


@router.put("/{role}")
def update_role(role: str, data: RoleText, user=Depends(current_user)):
    with Session.begin() as db:
        row = db.get(RoleInstruction, (user.tenant_id, role))
        if not row:
            raise HTTPException(404, "Papel não cadastrado nesta empresa")
        row.instructions = data.instructions
    return {"ok": True}
