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


async def respond(phone, config, data, pool, budget=7.0):
    # Stay below Meta's request deadline. Waiting never holds the admission lock
    # or submits another inference; slow answers retain the manual refresh.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget
    result = await asyncio.to_thread(exchange, phone, config, data, pool)
    while (data.get('action') == 'data_exchange'
        and result.get('data', {}).get('can_ask') is False):
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(0.25, remaining))
        current = channel_config(phone)
        if not current or current['tenant_id'] != config['tenant_id']:
            raise HTTPException(403, 'Sessão indisponível')
        result = await asyncio.to_thread(exchange, phone, current,
            {'action':'INIT', 'flow_token':data.get('flow_token')}, pool)
    return result


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
        log.warning('Flows request signature rejected; channel=%s', phone)
        raise HTTPException(403)
    try:
        data, key, iv = decrypt(raw, Path(config['private_key_path']).read_bytes())
    except Exception:
        log.warning('Invalid encrypted Flows request for configured channel')
        raise HTTPException(421, 'Não foi possível abrir a sessão') from None
    try:
        result = await respond(phone, config, data, process_pool)
    except HTTPException as error:
        log.warning('Flows request rejected; channel=%s status=%s', phone, error.status_code)
        raise
    return PlainTextResponse(encrypt(result, key, iv))
