import hashlib
import hmac
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func


class QueuedExecutor:
    def __init__(self):
        self.jobs = []

    def submit(self, job):
        self.jobs.append(job)


class WhatsAppTest(unittest.TestCase):
    def test_signed_webhook_routing_deduplication_and_delivery(self):
        from app import main, client
        from app.db import Base, Session
        from app.models import Tenant, Conversation, Contact, Message, MessageAuthor
        from app.seed import seed
        from app.whatsapp import webhook, bridge
        from app.whatsapp.models import Channel, Inbox, Outbox, Chat

        original_engine = Session.kw["bind"]
        with tempfile.TemporaryDirectory() as folder:
            engine = create_engine("sqlite:///" + folder + "/whatsapp.db")
            Base.metadata.create_all(engine)
            Session.configure(bind=engine)
            seed()
            try:
                with Session.begin() as db:
                    tenant = db.scalar(select(Tenant).where(Tenant.slug == "breve"))
                    tid = tenant.id
                    db.add(Channel(phone_number_id="111", tenant_id=tid))
                queued = QueuedExecutor()
                http = TestClient(webhook.app)
                payload = {
                    "object": "whatsapp_business_account",
                    "entry": [
                        {
                            "changes": [
                                {
                                    "field": "messages",
                                    "value": {
                                        "metadata": {"phone_number_id": "111"},
                                        "contacts": [
                                            {
                                                "wa_id": "5511999999999",
                                                "profile": {"name": "Teste Meta"},
                                            }
                                        ],
                                        "messages": [
                                            {
                                                "id": "wamid.test-1",
                                                "from": "5511999999999",
                                                "type": "text",
                                                "text": {"body": "Oi"},
                                            }
                                        ],
                                    },
                                }
                            ]
                        }
                    ],
                }
                raw = json.dumps(payload).encode()
                signature = (
                    "sha256="
                    + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
                )
                with (
                    patch.dict(
                        os.environ,
                        {
                            "WHATSAPP_APP_SECRET": "test-secret",
                            "WHATSAPP_VERIFY_TOKEN": "test-verify",
                        },
                    ),
                    patch.object(webhook, "pool", queued),
                ):
                    self.assertEqual(http.get("/admin").status_code, 404)
                    self.assertEqual(
                        http.get(
                            "/webhooks/whatsapp",
                            params={
                                "hub.mode": "subscribe",
                                "hub.verify_token": "bad",
                                "hub.challenge": "123",
                            },
                        ).status_code,
                        403,
                    )
                    self.assertEqual(
                        http.get(
                            "/webhooks/whatsapp",
                            params={
                                "hub.mode": "subscribe",
                                "hub.verify_token": "test-verify",
                                "hub.challenge": "123",
                            },
                        ).text,
                        "123",
                    )
                    self.assertEqual(
                        http.post(
                            "/webhooks/whatsapp",
                            content=raw,
                            headers={"x-hub-signature-256": "bad"},
                        ).status_code,
                        401,
                    )
                    headers = {
                        "x-hub-signature-256": signature,
                        "Content-Type": "application/json",
                    }
                    for _ in range(2):
                        self.assertEqual(
                            http.post(
                                "/webhooks/whatsapp", content=raw, headers=headers
                            ).status_code,
                            200,
                        )
                    self.assertEqual(len(queued.jobs), 1)
                    with patch.object(client, "reply", return_value="Olá, da Breve!"):
                        queued.jobs[0]()
                with Session() as db:
                    self.assertEqual(
                        db.scalar(select(func.count()).select_from(Inbox)), 1
                    )
                    self.assertEqual(
                        db.scalar(select(func.count()).select_from(Contact)), 1
                    )
                    conversation = db.scalar(select(Conversation))
                    self.assertEqual(conversation.tenant_id, tid)
                    cid = conversation.id
                    contact = db.get(Contact, conversation.contact_id)
                    self.assertEqual(contact.role, "cliente")
                    self.assertEqual(db.scalar(select(Inbox)).status, "done")
                with patch.object(
                    bridge, "send", return_value="wamid.response"
                ) as send:
                    self.assertTrue(bridge.deliver_one())
                    self.assertFalse(bridge.deliver_one())
                    self.assertEqual(
                        send.call_args.args[:4],
                        (
                            "111",
                            "WHATSAPP_ACCESS_TOKEN",
                            "5511999999999",
                            "Olá, da Breve!",
                        ),
                    )
                with Session.begin() as db:
                    message = Message(
                        tenant_id=tid,
                        conversation_id=cid,
                        sender="humano",
                        content="Estou aqui.",
                    )
                    db.add(message)
                    db.flush()
                    db.add(MessageAuthor(message_id=message.id, name="Ana"))
                with patch.object(
                    bridge, "send", side_effect=RuntimeError("Erro de teste")
                ) as send:
                    self.assertTrue(bridge.deliver_one())
                    self.assertFalse(bridge.deliver_one())
                    self.assertEqual(send.call_args.args[3], "*Ana*\nEstou aqui.")
                with Session() as db:
                    self.assertEqual(
                        db.scalar(
                            select(Outbox).where(Outbox.status == "failed")
                        ).error,
                        "Erro de teste",
                    )
            finally:
                engine.dispose()
                Session.configure(bind=original_engine)

    def test_graph_image_upload_uses_bearer_and_media_id(self):
        import httpx
        from app.whatsapp import graph

        original_client = httpx.Client
        requests = []

        def respond(request):
            requests.append(request)
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            if request.url.path.endswith("/media"):
                return httpx.Response(200, json={"id": "media-test"})
            data = json.loads(request.content)
            self.assertEqual(data["type"], "image")
            self.assertEqual(data["image"], {"id": "media-test", "caption": "Mapa"})
            return httpx.Response(200, json={"messages": [{"id": "wamid.image"}]})

        with (
            patch.dict(
                os.environ,
                {
                    "WHATSAPP_ACCESS_TOKEN": "test-token",
                    "WHATSAPP_GRAPH_VERSION": "v99.0",
                },
            ),
            patch.object(
                graph.httpx,
                "Client",
                side_effect=lambda **kwargs: original_client(
                    transport=httpx.MockTransport(respond), **kwargs
                ),
            ),
        ):
            self.assertEqual(
                graph.send(
                    "111",
                    "WHATSAPP_ACCESS_TOKEN",
                    "5511999999999",
                    "Mapa",
                    b"fake-image",
                ),
                "wamid.image",
            )
        self.assertEqual(len(requests), 2)
