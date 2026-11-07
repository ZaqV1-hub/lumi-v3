"""Renovação de credencial pelo admin local, sem passar pelo histórico da IA."""
import re
import threading
import httpx
from dotenv import set_key
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from ..access import current_user
from ..db import Session
from .models import Channel
from .config import app_secret, config_path, required

router = APIRouter()
config_lock = threading.Lock()


@router.get("/api/admin/whatsapp/channels")
def channels(user=Depends(current_user)):
    with Session() as db:
        return [{"phone_id": c.phone_number_id} for c in db.scalars(
            select(Channel).where(Channel.tenant_id == user.tenant_id))]


@router.post("/api/admin/whatsapp/token")
async def save_token(request: Request, user=Depends(current_user)):
    if request.headers.get("origin") and request.headers["origin"] != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Origem inválida")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise HTTPException(413)
    try:
        import json
        body = json.loads(raw)
        token = body["token"].strip()
        phone = str(body["phone_id"])
        if not 20 <= len(token) <= 4096 or any(c.isspace() for c in token) or not phone.isdigit():
            raise ValueError()
    except Exception:
        raise HTTPException(400, "Confira o token e o canal selecionado.") from None
    with Session() as db:
        channel = db.scalar(select(Channel).where(Channel.phone_number_id == phone,
                                                  Channel.tenant_id == user.tenant_id))
        if not channel:
            raise HTTPException(404, "Canal não encontrado")
    version = required("WHATSAPP_GRAPH_VERSION")
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise HTTPException(503, "Versão da Meta não configurada")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.get(f"https://graph.facebook.com/{version}/{phone}",
                params={"fields": "id,display_phone_number"}, headers={"Authorization": "Bearer " + token})
        if result.is_error or result.json().get("id") != phone:
            raise ValueError()
        number = result.json().get("display_phone_number", "")
    except Exception:
        raise HTTPException(400, "A Meta não aceitou esse token para o número selecionado. Gere um novo token com acesso a esse número.") from None
    key = "WHATSAPP_CHANNEL_TOKEN_" + phone
    with config_lock:
        with Session.begin() as db:
            channel = db.scalar(select(Channel).where(Channel.phone_number_id == phone,
                                                      Channel.tenant_id == user.tenant_id).with_for_update())
            if not channel:
                raise HTTPException(404, "Canal não encontrado")
            shared = db.scalar(select(Channel).where(Channel.token_env == key, Channel.phone_number_id != phone))
            if shared:
                raise HTTPException(409, "A credencial de destino está vinculada a outro canal. Revise a configuração.")
            secret = app_secret(channel.token_env)
            # A troca do nome do token não pode trocar o app que valida o webhook.
            set_key(str(config_path()), key + "_APP_SECRET", secret)
            set_key(str(config_path()), key, token, quote_mode="never")
            channel.token_env = key
    return {"ok": True, "phone": number}
