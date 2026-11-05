"""Simulação de papéis exige login; o visitante público continua sendo cliente."""
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from .access import current_user
from .business_models import ManagementChat, ReportGrant
from .db import Session
from .models import Contact, Conversation, Tenant, VisitorSession
from .role_instructions import RoleInstruction
from .tenant_runtime import allows_role, enabled

router = APIRouter(prefix="/api/admin/simulations")


def roles(db, user):
    if user.console_role not in ("admin", "brevia") or not enabled(db, user.tenant_id):
        return []
    result = []
    for row in db.scalars(select(RoleInstruction).where(RoleInstruction.tenant_id == user.tenant_id)):
        if not allows_role(db, user.tenant_id, row.role):
            continue
        grant = db.get(ReportGrant, (user.tenant_id, row.role))
        if row.role == "cliente" or (grant and grant.enabled and
                (grant.scope == "own" or (grant.scope == "all" and user.console_role == "brevia"))):
            result.append({"role": row.role, "label": row.label})
    return result


@router.get("/roles")
def available(user=Depends(current_user)):
    with Session() as db:
        return roles(db, user)


class StartSimulation(BaseModel):
    role: str = Field(max_length=40)
    name: str = Field(default="", max_length=120)


@router.post("")
def start(data: StartSimulation, user=Depends(current_user)):
    with Session.begin() as db:
        if data.role not in {r["role"] for r in roles(db, user)}:
            raise HTTPException(403, "Papel não autorizado para esta simulação")
        tenant = db.get(Tenant, user.tenant_id)
        contact = Contact(tenant_id=tenant.id, name=data.name.strip() or user.name, role=data.role)
        db.add(contact); db.flush()
        chat = Conversation(tenant_id=tenant.id, contact_id=contact.id)
        db.add(chat); db.flush()
        token = secrets.token_urlsafe(32)
        db.add(VisitorSession(token=token, tenant_id=tenant.id, conversation_id=chat.id))
        db.add(ManagementChat(conversation_id=chat.id, actor_id=user.id))
        return {"token": token, "tenant": tenant.name}
