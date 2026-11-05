"""Validação e armazenamento local de tokens, fora do histórico da Lumi."""
import json
import threading
import httpx
from dotenv import set_key
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from ..access import current_user
from ..db import Session
from .config import config_path
from .models import Channel

router = APIRouter(prefix="/api/admin/instagram")
config_lock = threading.Lock()


@router.get("/channels")
def channels(user=Depends(current_user)):
    with Session() as db:
        return [{"profile_id": channel.profile_id} for channel in db.scalars(
            select(Channel).where(Channel.tenant_id == user.tenant_id))]


@router.post("/token")
async def save_token(request: Request, user=Depends(current_user)):
    if request.headers.get("origin") and request.headers["origin"] != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Origem inválida")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise HTTPException(413)
    try:
        body = json.loads(raw)
        token = body["token"].strip()
        profile = str(body["profile_id"])
        if not 20 <= len(token) <= 4096 or any(c.isspace() for c in token) or not profile.isdigit():
            raise ValueError()
    except Exception:
        raise HTTPException(400, "Confira o token e o perfil selecionado.") from None
    with Session() as db:
        channel = db.get(Channel, profile)
        if not channel or channel.tenant_id != user.tenant_id:
            raise HTTPException(404, "Perfil não encontrado")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.get(f"https://graph.facebook.com/v26.0/{profile}",
                params={"fields": "id,username"}, headers={"Authorization": "Bearer " + token})
        if result.is_error or result.json().get("id") != profile:
            raise ValueError()
        username = str(result.json().get("username", ""))
    except Exception:
        raise HTTPException(400, "A Meta não aceitou esse token do Login Unificado para o perfil selecionado.") from None
    key = "INSTAGRAM_CHANNEL_TOKEN_" + profile
    with config_lock:
        set_key(str(config_path()), key, token, quote_mode="never")
        set_key(str(config_path()), key + "_GRAPH_HOST", "graph.facebook.com")
        with Session.begin() as db:
            channel = db.get(Channel, profile)
            if not channel or channel.tenant_id != user.tenant_id:
                raise HTTPException(404, "Perfil não encontrado")
            channel.token_env = key
    return {"ok": True, "username": username}
