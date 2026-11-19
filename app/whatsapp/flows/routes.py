import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ..config import app_secret
from ..models import Channel
from ...db import Session
from .config import channel_config
from .runtime import exchange
from .security import decrypt, encrypt, signed

router = APIRouter()
process_pool = None
log = logging.getLogger(__name__)


@router.post('/webhooks/whatsapp/flows/{phone}')
async def flow_endpoint(phone: str, request: Request):
    config = channel_config(phone)
    if not config or process_pool is None:
        raise HTTPException(404)
    with Session() as db:
        channel = db.get(Channel, phone)
        if not channel or channel.tenant_id != config['tenant_id']:
            raise HTTPException(404)
        secret = app_secret(channel.token_env)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 65536:
            raise HTTPException(413)
    raw = bytes(raw)
    if not signed(raw, request.headers.get('x-hub-signature-256'), secret):
        raise HTTPException(403)
    try:
        data, key, iv = decrypt(raw, Path(config['private_key_path']).read_bytes())
    except Exception:
        log.warning('Invalid encrypted Flows request for configured channel')
        raise HTTPException(421, 'Não foi possível abrir a sessão') from None
    result = await asyncio.to_thread(exchange, phone, config, data, process_pool)
    return PlainTextResponse(encrypt(result, key, iv))
