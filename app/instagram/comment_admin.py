from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
import httpx
from ..access import current_user
from ..db import Session
from .models import Channel
from .comment_models import CommentSettings
from .comment_graph import connection

router = APIRouter(prefix="/api/admin/instagram/comments")


def channel_for(db, profile_id, user):
    row = db.scalar(select(Channel).where(Channel.profile_id == profile_id, Channel.tenant_id == user.tenant_id))
    if not row:
        raise HTTPException(404, "Perfil não encontrado nesta empresa")
    return row


@router.get("/{profile_id}")
def settings(profile_id: str, user=Depends(current_user)):
    with Session() as db:
        channel_for(db, profile_id, user)
        row = db.get(CommentSettings, profile_id)
        return {"enabled": bool(row and row.enabled), "instructions": row.instructions if row else ""}


class SettingsInput(BaseModel):
    enabled: bool = False
    instructions: str = Field(max_length=6000)


def check_access(channel):
    base, headers = connection(channel)
    try:
        with httpx.Client(timeout=15) as http:
            result = http.get(base + "/me/permissions", headers=headers)
            result.raise_for_status()
            permissions = {p.get("permission") for p in result.json().get("data", []) if p.get("status") == "granted"}
            if not permissions.intersection({"instagram_manage_comments", "instagram_business_manage_comments"}):
                raise ValueError()
            result = http.get(base + "/" + channel.profile_id + "/subscribed_apps", headers=headers)
            result.raise_for_status()
            if not any("comments" in app.get("subscribed_fields", []) for app in result.json().get("data", [])):
                raise ValueError()
    except Exception:
        raise HTTPException(409, "Salve as instruções com a opção desativada. Para ativar, autorize comentários na Meta e assine o evento comments para este perfil.") from None


@router.put("/{profile_id}")
def save(profile_id: str, data: SettingsInput, user=Depends(current_user)):
    with Session.begin() as db:
        channel = channel_for(db, profile_id, user)
        if data.enabled:
            if not data.instructions.strip():
                raise HTTPException(422, "Preencha as instruções dos comentários")
            check_access(channel)
        db.merge(CommentSettings(profile_id=profile_id, enabled=data.enabled, instructions=data.instructions.strip()))
    return {"ok": True}
