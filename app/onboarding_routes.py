from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
import json
from .access import current_user
from .db import Session
from .models import Contact, Conversation
from .onboarding import objectives, profile_state
from .onboarding_models import OnboardingObjective
from .objective_options import ObjectiveOptions, options, normalized

router = APIRouter()


class ChoiceInput(BaseModel):
    value: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=30)


class ObjectiveInput(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=2000)
    required: bool = True
    updates_name: bool = False
    choices: list[ChoiceInput] = Field(default_factory=list, max_length=200)
    allow_other: bool = False

    @model_validator(mode='after')
    def validate_choices(self):
        names=set()
        if self.updates_name and self.choices:
            raise ValueError('Nome do contato deve ser uma informação livre.')
        for choice in self.choices:
            for name in [choice.value]+choice.aliases:
                key=normalized(name)
                if not key or len(name)>120 or key in names:
                    raise ValueError('Use opções e variações distintas, de até 120 caracteres.')
                names.add(key)
        return self


def save_options(db, user, field, data):
    row=db.get(ObjectiveOptions,field.id)
    if not row:
        row=ObjectiveOptions(objective_id=field.id,tenant_id=user.tenant_id);db.add(row)
    row.choices_json=json.dumps([c.model_dump() for c in data.choices],ensure_ascii=False)
    row.allow_other=data.allow_other


def owned(db, user, oid):
    field = db.get(OnboardingObjective, oid)
    if not field or field.tenant_id != user.tenant_id:
        raise HTTPException(404, "Objetivo não encontrado")
    return field


@router.get("/api/admin/onboarding")
def list_objectives(user=Depends(current_user)):
    with Session() as db:
        return [{"id": f.id, "title": f.title, "description": f.description,
                 "required": f.required, "updates_name": f.updates_name, **options(db,user.tenant_id,f.id)} for f in objectives(db, user.tenant_id)]


@router.post("/api/admin/onboarding")
def create_objective(data: ObjectiveInput, user=Depends(current_user)):
    with Session.begin() as db:
        field=OnboardingObjective(tenant_id=user.tenant_id, **data.model_dump(exclude={'choices','allow_other'}))
        db.add(field);db.flush();save_options(db,user,field,data)
    return {"ok": True}


@router.put("/api/admin/onboarding/{oid}")
def edit_objective(oid: str, data: ObjectiveInput, user=Depends(current_user)):
    with Session.begin() as db:
        field = owned(db, user, oid)
        for key, value in data.model_dump(exclude={'choices','allow_other'}).items():
            setattr(field, key, value)
        if 'choices' in data.model_fields_set or 'allow_other' in data.model_fields_set:
            save_options(db,user,field,data)
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
