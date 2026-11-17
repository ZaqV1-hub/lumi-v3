"""Único serviço exposto pelo túnel. O admin continua em localhost:8000."""

import asyncio
import hashlib
import hmac
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, update
from ..db import Base, engine, Session
from ..media_models import ContactGate
from .config import app_secret, load_config
from .models import Channel, Inbox
from .bridge import receive, deliver_one, record_delivery
from .follow_up import poll as poll_follow_up
from .calling_webhook import is_permission_reply, process_permission, process_calls
from .calling_models import CALLING_TABLES
from .checkout_proxy import router as checkout_router
from ..instagram.webhook import router as instagram_router
from ..instagram.media import router as instagram_media_router
from ..instagram.bridge import deliver_one as deliver_instagram
from ..instagram.models import Inbox as InstagramInbox, Outbox as InstagramOutbox
from ..privacy import router as privacy_router
from ..instagram.comments import deliver_one as deliver_comment
from ..instagram.comment_models import CommentJob

load_config()
pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="whatsapp")


@asynccontextmanager
async def lifespan(_):
    from ..db import Session
    active_engine = Session.kw["bind"]
    Base.metadata.create_all(active_engine, tables=[table for table in Base.metadata.sorted_tables if table not in CALLING_TABLES])
    with active_engine.begin() as db:
        db.execute(update(InstagramInbox).where(InstagramInbox.status.in_(["queued", "processing"])).values(status="interrupted", error="Servidor reiniciado durante processamento."))
        db.execute(update(InstagramOutbox).where(InstagramOutbox.status == "sending").values(status="failed", error="Envio interrompido. Confira a entrega antes de reenviar."))
        db.execute(
            update(Inbox)
            .where(Inbox.status == "processing")
            .values(
                status="interrupted", error="Servidor reiniciado durante processamento."
            )
        )
        db.execute(update(ContactGate).values(pending=0))
        db.execute(update(CommentJob).where(CommentJob.status.in_(["queued", "generating", "sending"])).values(status="interrupted", error="Servidor reiniciado; confira o comentário antes de reenviar."))

    async def deliver():
        while True:
            try:
                had_item = await asyncio.to_thread(deliver_one)
                had_item = await asyncio.to_thread(deliver_instagram) or had_item
                had_item = await asyncio.to_thread(deliver_comment) or had_item
            except Exception:
                had_item = False
            await asyncio.sleep(0.1 if had_item else 0.5)

    worker = asyncio.create_task(deliver())
    follow_up = asyncio.create_task(poll_follow_up())
    try:
        yield
    finally:
        worker.cancel()
        follow_up.cancel()
        await asyncio.gather(worker, follow_up, return_exceptions=True)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(checkout_router)
app.include_router(instagram_router)
app.include_router(instagram_media_router)
app.include_router(privacy_router)


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
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024:
            raise HTTPException(413, "Evento muito grande")
    import json

    try:
        body = json.loads(raw)
        changes = [change for entry in body.get("entry", []) for change in entry.get("changes", [])] \
            if body.get("object") == "whatsapp_business_account" else []
        phones = [change.get("value", {}).get("metadata", {}).get("phone_number_id", "") for change in changes]
        if any(not isinstance(phone, str) for phone in phones):
            raise ValueError()
        with Session() as db:
            channels = {channel.phone_number_id: channel.token_env for channel in db.scalars(
                select(Channel).where(Channel.phone_number_id.in_(set(phones))))} if phones else {}
        secrets = {app_secret(token_env) for token_env in channels.values()} if channels else {app_secret()}
        # Valida o lote inteiro antes de registrar recibos ou iniciar conversas.
        if not all(secrets):
            raise HTTPException(503, "Webhook não configurado")
        for secret in secrets:
            expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, request.headers.get("x-hub-signature-256", "")):
                raise HTTPException(401, "Assinatura inválida")
        for change, phone_id in zip(changes, phones):
            if phone_id not in channels:
                continue
            value = change.get("value", {})
            if change.get("field") == "calls":
                await asyncio.to_thread(process_calls, phone_id, value)
                continue
            if change.get("field") != "messages":
                continue
            for delivery in value.get("statuses", []):
                await asyncio.to_thread(record_delivery, phone_id, delivery)
            names = {
                c.get("wa_id"): c.get("profile", {}).get("name", "")
                for c in value.get("contacts", [])
            }
            for message in value.get("messages", []):
                if is_permission_reply(message):
                    await asyncio.to_thread(process_permission, phone_id, message)
                    continue
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
