from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .access import current_user
from .db import Session
from .models import Contact, Conversation
from .onboarding import objectives, profile_state
from .onboarding_models import OnboardingObjective

router = APIRouter()


class ObjectiveInput(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=2000)
    required: bool = True
    updates_name: bool = False


def owned(db, user, oid):
    field = db.get(OnboardingObjective, oid)
    if not field or field.tenant_id != user.tenant_id:
        raise HTTPException(404, "Objetivo não encontrado")
    return field


@router.get("/api/admin/onboarding")
def list_objectives(user=Depends(current_user)):
    with Session() as db:
        return [{"id": f.id, "title": f.title, "description": f.description,
                 "required": f.required, "updates_name": f.updates_name} for f in objectives(db, user.tenant_id)]


@router.post("/api/admin/onboarding")
def create_objective(data: ObjectiveInput, user=Depends(current_user)):
    with Session.begin() as db:
        db.add(OnboardingObjective(tenant_id=user.tenant_id, **data.model_dump()))
    return {"ok": True}


@router.put("/api/admin/onboarding/{oid}")
def edit_objective(oid: str, data: ObjectiveInput, user=Depends(current_user)):
    with Session.begin() as db:
        field = owned(db, user, oid)
        for key, value in data.model_dump().items():
            setattr(field, key, value)
    return {"ok": True}


@router.delete("/api/admin/onboarding/{oid}")
def disable_objective(oid: str, user=Depends(current_user)):
    with Session.begin() as db:
        owned(db, user, oid).enabled = False
    return {"ok": True}


@router.get("/api/admin/conversations/{cid}/profile")
def contact_profile(cid: str, user=Depends(current_user)):
    with Session() as db:
        conversation = db.get(Conversation, cid)
        if not conversation or conversation.tenant_id != user.tenant_id:
            raise HTTPException(404, "Conversa não encontrada")
        return profile_state(db, user.tenant_id, conversation.contact_id)
