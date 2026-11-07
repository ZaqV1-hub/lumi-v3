"""A equipe administra a IA do tenant; segredos nunca são devolvidos."""
import json
import re
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .access import current_user
from .db import Session
from .tenant_ai import TenantAI, PROVIDERS, encrypt_key, public_configuration

router = APIRouter()


def operator(user=Depends(current_user)):
    if user.console_role != "brevia":
        raise HTTPException(403, "Configuração de IA exclusiva da equipe Brevia")
    return user


@router.get("/api/admin/ai")
def settings(response: Response, user=Depends(operator)):
    response.headers["Cache-Control"] = "no-store"
    with Session() as db:
        return public_configuration(db.get(TenantAI, user.tenant_id))


@router.put("/api/admin/ai")
async def save(request: Request, response: Response, user=Depends(operator)):
    response.headers["Cache-Control"] = "no-store"
    if request.headers.get("origin") and request.headers["origin"] != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Origem inválida")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise HTTPException(413, "Configuração muito grande")
    # Parse manual evita que erros de validação reflitam a chave enviada.
    try:
        body = json.loads(raw)
        if not isinstance(body, dict) or set(body) - {"provider", "model", "api_key", "remove_api_key"}:
            raise ValueError()
        provider, model = body["provider"], body.get("model", "")
        key, remove = body.get("api_key", ""), body.get("remove_api_key", False)
        if key is None:
            key = ""
        if not isinstance(provider, str) or provider not in PROVIDERS or not isinstance(model, str):
            raise ValueError()
        model = model.strip()
        if provider != "demo" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", model):
            raise ValueError()
        if not isinstance(key, str) or type(remove) is not bool or (key and remove):
            raise ValueError()
        if key and not re.fullmatch(r"[A-Za-z0-9_-]{20,4096}", key):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, "Confira o provider, modelo e credencial informados.") from None
    try:
        encrypted = encrypt_key(user.tenant_id, key) if key else None
        with Session.begin() as db:
            row = db.scalar(select(TenantAI).where(TenantAI.tenant_id == user.tenant_id).with_for_update())
            if not row:
                row = TenantAI(tenant_id=user.tenant_id, provider=provider, model=model, encrypted_api_key="")
                db.add(row)
            row.provider, row.model = provider, "" if provider == "demo" else model
            if remove:
                row.encrypted_api_key = ""
            elif encrypted is not None:
                row.encrypted_api_key = encrypted
            return public_configuration(row)
    except RuntimeError:
        raise HTTPException(503, "A proteção de credenciais precisa ser configurada no servidor.") from None
    except IntegrityError:
        raise HTTPException(409, "A configuração mudou durante a gravação. Recarregue e tente novamente.") from None
