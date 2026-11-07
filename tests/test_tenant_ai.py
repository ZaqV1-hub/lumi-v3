"""Tenant AI selection, private credentials and concurrent routing, without external calls."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import create_engine, select

from app import main, providers
from app.console_models import ConsoleAccount
from app.db import Base, Session
from app.models import Tenant, User
from app.seed import seed
from app.tenant_ai import TenantAI, configuration


HTTP_CLIENT = httpx.Client
KEY_A = "sk-test-tenant-a-not-a-real-key"
KEY_B = "sk-test-tenant-b-not-a-real-key"


def response():
    answer = {"reply": "Resposta fictícia.", "action": "none", "tool_call": None,
              "image_id": None, "profile_updates": [], "asked_objective_id": None}
    return {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps(answer)}]}]}


class TenantAITest(unittest.TestCase):
    def setUp(self):
        self.previous = Session.kw["bind"]
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + self.folder.name + "/ai.db")
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        seed()
        self.environment = patch.dict(os.environ, {
            "LUMI_AI_SECRET_KEY": Fernet.generate_key().decode(),
            "OPENAI_API_KEY": "sk-test-global-must-never-be-used",
            "LUMI_PROVIDER": "openai", "LUMI_OPENAI_MODEL": "global-model",
        })
        self.environment.start()
        with Session.begin() as db:
            self.first = db.scalar(select(Tenant.id).where(Tenant.slug == "rincao"))
            self.second = db.scalar(select(Tenant.id).where(Tenant.slug == "breve"))
            operator = db.scalar(select(User).where(User.email == "ana@breve.local"))
            db.add(ConsoleAccount(user_id=operator.id, role="brevia"))
            self.customer_id = db.scalar(select(User.id).where(User.email == "isaque@rincao.local"))
        self.operator = TestClient(main.app)
        self.customer = TestClient(main.app)
        self.operator.post("/api/login", json={"email": "ana@breve.local", "password": "demo1234"}).raise_for_status()
        self.customer.post("/api/login", json={"email": "isaque@rincao.local", "password": "demo1234"}).raise_for_status()

    def tearDown(self):
        self.operator.close()
        self.customer.close()
        self.environment.stop()
        Session.configure(bind=self.previous)
        self.engine.dispose()
        self.folder.cleanup()

    def save(self, tenant, **changes):
        data = {"provider": "openai", "model": "test-model", **changes}
        result = self.operator.put("/api/admin/ai", params={"tenant": tenant}, json=data)
        self.assertEqual(result.status_code, 200, result.text)
        for secret in (KEY_A, KEY_B, "sk-test-global-must-never-be-used"):
            self.assertNotIn(secret, result.text)
        return result.json()

    def read(self, tenant):
        result = self.operator.get("/api/admin/ai", params={"tenant": tenant})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers.get("cache-control"), "no-store")
        return result.json()

    def test_only_brevia_with_explicit_valid_tenant_can_read_or_change_credentials(self):
        data = {"provider": "openai", "model": "test-model", "api_key": KEY_A}
        with TestClient(main.app) as anonymous:
            self.assertEqual(anonymous.get("/api/admin/ai", params={"tenant": self.first}).status_code, 401)
            self.assertEqual(anonymous.put("/api/admin/ai", params={"tenant": self.first}, json=data).status_code, 401)
        for tenant in (self.first, self.second):
            self.assertEqual(self.customer.get("/api/admin/ai", params={"tenant": tenant}).status_code, 403)
            self.assertEqual(self.customer.put("/api/admin/ai", params={"tenant": tenant}, json=data).status_code, 403)
        self.assertEqual(self.operator.get("/api/admin/ai").status_code, 403)
        self.assertEqual(self.operator.put("/api/admin/ai", json=data).status_code, 403)
        self.assertEqual(self.operator.get("/api/admin/ai", params={"tenant": "missing"}).status_code, 404)
        denied = self.operator.put("/api/admin/ai", params={"tenant": self.first}, json=data,
                                   headers={"Origin": "https://untrusted.example"})
        self.assertEqual(denied.status_code, 403)
        with Session.begin() as db:
            db.add(ConsoleAccount(user_id=self.customer_id, role="leitura"))
        self.assertEqual(self.customer.put("/api/admin/ai", json=data).status_code, 403)
        with Session() as db:
            self.assertIsNone(db.get(TenantAI, self.first))

    def test_credentials_are_encrypted_never_returned_and_changes_stay_in_selected_tenant(self):
        self.save(self.first, api_key=KEY_A)
        self.save(self.second, api_key=KEY_B, model="other-model")
        with Session() as db:
            encrypted = db.get(TenantAI, self.first).encrypted_api_key
            self.assertTrue(encrypted)
            self.assertNotIn(KEY_A, encrypted)
        first = self.read(self.first)
        self.assertTrue(first["api_key_configured"])
        self.assertTrue(first["ready"])
        self.assertNotIn(KEY_A, json.dumps(first))
        self.assertNotIn(encrypted, json.dumps(first))
        self.assertNotIn(KEY_A, self.operator.get("/api/console/audit").text)
        self.save(self.first, model="changed-model", api_key="")
        self.assertEqual(configuration(self.first).api_key, KEY_A)
        self.save(self.first, api_key=None)
        self.assertEqual(configuration(self.first).api_key, KEY_A)
        self.save(self.first, remove_api_key=True)
        self.assertFalse(self.read(self.first)["api_key_configured"])
        self.assertFalse(self.read(self.first)["ready"])
        self.assertEqual(configuration(self.second).api_key, KEY_B)
        self.assertEqual(configuration(self.second).model, "other-model")

    def test_invalid_secret_and_missing_encryption_key_do_not_leak_or_partially_save(self):
        self.save(self.first, provider="codex", model="test-codex")
        invalid = "sk-private-invalid-key with spaces"
        result = self.operator.put("/api/admin/ai", params={"tenant": self.first}, json={
            "provider": "openai", "model": "test-model", "api_key": invalid})
        self.assertIn(result.status_code, (400, 422))
        self.assertNotIn(invalid, result.text)
        with patch.dict(os.environ, {"LUMI_AI_SECRET_KEY": ""}):
            result = self.operator.put("/api/admin/ai", params={"tenant": self.first}, json={
                "provider": "openai", "model": "test-model", "api_key": KEY_A})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn(KEY_A, result.text)
        with Session() as db:
            row = db.get(TenantAI, self.first)
            self.assertEqual(row.provider, "codex")
            self.assertEqual(row.model, "test-codex")
            self.assertFalse(row.encrypted_api_key)

    def test_global_environment_is_not_a_fallback_and_ciphertext_cannot_move_between_tenants(self):
        with patch("app.openai_provider.httpx.Client") as network, patch.object(providers.subprocess, "run") as cli:
            for tid in (None, self.first, "missing"):
                with self.subTest(tenant=tid), self.assertRaises(RuntimeError):
                    providers.reply("Teste", tenant_id=tid)
            self.save(self.first)
            with self.assertRaises(RuntimeError):
                providers.reply("Teste", tenant_id=self.first)
            network.assert_not_called()
            cli.assert_not_called()
        self.save(self.first, api_key=KEY_A)
        self.save(self.second, api_key=KEY_B)
        with Session.begin() as db:
            db.get(TenantAI, self.second).encrypted_api_key = db.get(TenantAI, self.first).encrypted_api_key
        with self.assertRaises(RuntimeError):
            configuration(self.second)
        self.assertEqual(configuration(self.first).api_key, KEY_A)

    def test_concurrent_tenants_use_their_own_openai_key_and_model(self):
        self.save(self.first, api_key=KEY_A, model="model-a")
        self.save(self.second, api_key=KEY_B, model="model-b")
        barrier = threading.Barrier(2)
        observed = []

        def respond(request):
            body = json.loads(request.content)
            observed.append((body["input"][0]["content"][0]["text"],
                             body["model"], request.headers["authorization"]))
            barrier.wait(timeout=10)
            return httpx.Response(200, json=response())

        def http_client(**kwargs):
            return HTTP_CLIENT(transport=httpx.MockTransport(respond))

        with patch("app.openai_provider.httpx.Client", side_effect=http_client), \
                patch.object(providers.subprocess, "run", side_effect=AssertionError("Codex fallback")):
            with ThreadPoolExecutor(max_workers=2) as workers:
                calls = [workers.submit(providers.reply, "tenant-a", tenant_id=self.first),
                         workers.submit(providers.reply, "tenant-b", tenant_id=self.second)]
                self.assertTrue(all(call.result(timeout=15)["reply"] for call in calls))
        self.assertCountEqual(observed, [("tenant-a", "model-a", "Bearer " + KEY_A),
                                        ("tenant-b", "model-b", "Bearer " + KEY_B)])

    def test_provider_switch_is_tenant_local_and_needs_no_process_restart(self):
        self.save(self.first, provider="codex", model="test-codex")
        self.save(self.second, api_key=KEY_B)
        final = {"reply": "Codex fictício.", "action": "none"}
        stream = json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": json.dumps(final)}})
        with patch.object(providers.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stream, "")) as cli, \
                patch("app.openai_provider.reply", return_value={"reply": "API fictícia."}) as api:
            self.assertEqual(providers.reply("Teste", tenant_id=self.first)["reply"], "Codex fictício.")
            self.assertEqual(providers.reply("Teste", tenant_id=self.second)["reply"], "API fictícia.")
            self.assertEqual(api.call_args.kwargs["api_key"], KEY_B)
            self.assertEqual(cli.call_count, 1)
            self.save(self.first, api_key=KEY_A)
            providers.reply("Teste", tenant_id=self.first)
            self.assertEqual(api.call_args.kwargs["api_key"], KEY_A)
            self.assertEqual(cli.call_count, 1)

    def test_migration_adds_missing_settings_without_copying_global_key_or_overwriting_tenants(self):
        from app.migrate_tenant_ai import migrate
        with Session() as db:
            before = [(t.id, t.name, t.identity, t.personality) for t in db.scalars(select(Tenant).order_by(Tenant.id))]
        TenantAI.__table__.drop(self.engine)
        self.assertEqual(migrate("openai", "prepared-model", "rincao"), 1)
        self.assertFalse(self.read(self.first)["api_key_configured"])
        self.assertFalse(self.read(self.first)["ready"])
        with Session() as db:
            self.assertIsNone(db.get(TenantAI, self.second))
        self.save(self.first, api_key=KEY_A, model="chosen-model")
        self.assertEqual(migrate("codex", "test-codex"), 1)
        self.assertEqual(migrate("demo", ""), 0)
        self.assertEqual(configuration(self.first).api_key, KEY_A)
        self.assertEqual(configuration(self.first).model, "chosen-model")
        self.assertEqual(configuration(self.second).provider, "codex")
        with self.assertRaises(ValueError):
            migrate("codex", "test-codex", "missing-tenant")
        with Session() as db:
            after = [(t.id, t.name, t.identity, t.personality) for t in db.scalars(select(Tenant).order_by(Tenant.id))]
        self.assertEqual(after, before)
