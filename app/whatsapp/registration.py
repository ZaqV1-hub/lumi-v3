"""Ativação explícita de um telefone já verificado; o PIN nunca é armazenado."""
import json
import re
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from ..access import current_user
from ..db import Session
from .models import Channel
from .config import access_token

router = APIRouter(prefix="/api/admin/whatsapp")


def channel_token(user, phone):
    if not phone.isdigit():
        raise HTTPException(400, "Telefone inválido")
    with Session() as db:
        channel = db.get(Channel, phone)
        if not channel or channel.tenant_id != user.tenant_id:
            raise HTTPException(404, "Canal não encontrado")
        try:
            return access_token(channel.token_env)
        except RuntimeError:
            raise HTTPException(400, "Valide primeiro o token deste canal.") from None


async def phone_status(client, phone, token):
    result = await client.get(f"https://graph.facebook.com/v26.0/{phone}",
        params={"fields":"id,display_phone_number,status,code_verification_status,platform_type"},
        headers={"Authorization":"Bearer " + token})
    if result.is_error:
        raise HTTPException(400, "A Meta recusou a consulta. Confira a autorização do canal.")
    row = result.json()
    return {key: row.get(key) for key in ("id", "display_phone_number", "status", "code_verification_status", "platform_type")}


@router.get("/registration/{phone}")
async def status(phone: str, user=Depends(current_user)):
    token = channel_token(user, phone)
    async with httpx.AsyncClient(timeout=15) as client:
        return await phone_status(client, phone, token)


@router.post("/registration/{phone}")
async def register(phone: str, request: Request, user=Depends(current_user)):
    if request.headers.get("origin") and request.headers["origin"] != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Origem inválida")
    token = channel_token(user, phone)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 512:
            raise HTTPException(413)
    try:
        pin = json.loads(raw)["pin"]
        if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{6}", pin):
            raise ValueError()
    except Exception:
        raise HTTPException(400, "Informe o PIN de seis dígitos diretamente nesta página.") from None
    async with httpx.AsyncClient(timeout=25) as client:
        current = await phone_status(client, phone, token)
        if current["platform_type"] != "NOT_APPLICABLE" or current["code_verification_status"] != "VERIFIED":
            raise HTTPException(409, "Este fluxo ativa somente números verificados que ainda não foram registrados na API.")
        try:
            result = await client.post(f"https://graph.facebook.com/v26.0/{phone}/register",
                headers={"Authorization":"Bearer " + token}, json={"messaging_product":"whatsapp", "pin":pin})
        except httpx.HTTPError:
            raise HTTPException(502, "A Meta não confirmou o resultado. Consulte o status antes de tentar novamente.") from None
        if result.is_error or result.json().get("success") is not True:
            code = result.json().get("error", {}).get("code")
            raise HTTPException(400, f"A Meta recusou o registro (código {code}). Confira se já existe um PIN nesse número.")
    return {"ok":True, "message":"Registro confirmado pela Meta. Consulte o status do número; o recebimento ainda precisa ser configurado."}
