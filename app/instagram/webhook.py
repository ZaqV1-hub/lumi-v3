import asyncio
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from ..db import Session
from .config import value
from .models import Channel
from .bridge import receive
from .comments import receive as receive_comment

router = APIRouter()
pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="instagram")


@router.get("/webhooks/instagram")
def verify(request: Request):
    configured = value("INSTAGRAM_VERIFY_TOKEN")
    token = request.query_params.get("hub.verify_token", "")
    if not configured or request.query_params.get("hub.mode") != "subscribe" or not hmac.compare_digest(configured, token):
        raise HTTPException(403, "Verificação inválida")
    return PlainTextResponse(request.query_params.get("hub.challenge", ""))


@router.post("/webhooks/instagram")
async def incoming(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024:
            raise HTTPException(413, "Evento muito grande")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict) or not isinstance(body.get("entry", []), list):
            raise ValueError()
        if body.get("object") != "instagram":
            return {"ok": True}
        events = []
        comments = []
        with Session() as db:
            for entry in body.get("entry", []):
                channel = db.get(Channel, str(entry["id"]))
                if not channel:
                    continue
                secret = value(channel.secret_env)
                expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
                if not secret or not hmac.compare_digest(expected, request.headers.get("x-hub-signature-256", "")):
                    raise HTTPException(401, "Assinatura inválida")
                for event in entry.get("messaging", []):
                    if not isinstance(event, dict):
                        raise ValueError()
                    events.append((channel.profile_id, event))
                for change in entry.get("changes", []):
                    if not isinstance(change, dict):
                        raise ValueError()
                    if change.get("field") == "comments" and isinstance(change.get("value"), dict):
                        comments.append((channel.profile_id, change["value"]))
        for profile_id, event in events:
            await asyncio.to_thread(receive, profile_id, event, pool)
        for profile_id, event in comments:
            await asyncio.to_thread(receive_comment, profile_id, event, pool)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(400, "Evento inválido")
    return {"ok": True}
