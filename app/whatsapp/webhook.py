"""Único serviço exposto pelo túnel. O admin continua em localhost:8000."""

import asyncio
import hashlib
import hmac
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import update
from ..db import Base, engine
from ..media_models import ContactGate
from .config import load_config
from .models import Inbox
from .bridge import receive, deliver_one, record_delivery

load_config()
pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="whatsapp")


@asynccontextmanager
async def lifespan(_):
    Base.metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(
            update(Inbox)
            .where(Inbox.status == "processing")
            .values(
                status="interrupted", error="Servidor reiniciado durante processamento."
            )
        )
        db.execute(update(ContactGate).values(pending=0))

    async def deliver():
        while True:
            try:
                had_item = await asyncio.to_thread(deliver_one)
            except Exception:
                had_item = False
            await asyncio.sleep(0.1 if had_item else 0.5)

    worker = asyncio.create_task(deliver())
    yield
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/webhooks/whatsapp")
def verify(request: Request):
    configured = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    token = request.query_params.get("hub.verify_token", "")
    if (
        not configured
        or request.query_params.get("hub.mode") != "subscribe"
        or not hmac.compare_digest(configured, token)
    ):
        raise HTTPException(403, "Verificação inválida")
    return PlainTextResponse(request.query_params.get("hub.challenge", ""))


@app.post("/webhooks/whatsapp")
async def incoming(request: Request):
    secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if not secret:
        raise HTTPException(503, "Webhook não configurado")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024:
            raise HTTPException(413, "Evento muito grande")
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(
        expected, request.headers.get("x-hub-signature-256", "")
    ):
        raise HTTPException(401, "Assinatura inválida")
    import json

    try:
        body = json.loads(raw)
        if body.get("object") != "whatsapp_business_account":
            return {"ok": True}
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue
                value = change.get("value", {})
                phone_id = value.get("metadata", {}).get("phone_number_id", "")
                for delivery in value.get("statuses", []):
                    await asyncio.to_thread(record_delivery, phone_id, delivery)
                names = {
                    c.get("wa_id"): c.get("profile", {}).get("name", "")
                    for c in value.get("contacts", [])
                }
                for message in value.get("messages", []):
                    await asyncio.to_thread(
                        receive,
                        phone_id,
                        message,
                        names.get(message.get("from"), ""),
                        pool,
                    )
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(400, "Evento inválido")
    return {"ok": True}
