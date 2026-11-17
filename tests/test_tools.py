import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select


class ToolsTest(unittest.TestCase):
    def setUp(self):
        from app import main
        from app.db import Base, Session
        from app.seed import seed
        from app.models import Tenant, Feature
        from app.tool_models import ToolContract
        from services.rincao.contracts import CONTRACTS
        # Registra comércio explicitamente, sem depender da ordem dos outros testes.
        from services.rincao import commerce_contracts
        from services.web_tools.contracts import CONTRACTS as WEB_CONTRACTS
        self.session = Session
        self.previous = Session.kw["bind"]
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + self.folder.name + "/tools.db")
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        seed()
        with Session.begin() as db:
            self.tid = db.scalar(select(Tenant.id).where(Tenant.slug == "rincao"))
            for item in [*CONTRACTS, *WEB_CONTRACTS]:
                f = Feature(tenant_id=self.tid, name=item["name"], description=item["description"],
                    endpoint="http://127.0.0.1:8003" + item["path"], roles=",".join(item["roles"]))
                db.add(f); db.flush()
                db.add(ToolContract(feature_id=f.id, parameters_schema=json.dumps(item["parameters"]), secret_env="TEST_TOOL_SECRET"))
        self.http = TestClient(main.app)
        self.other = TestClient(main.app)
        for http, email in [(self.http, "isaque@rincao.local"), (self.other, "ana@breve.local")]:
            http.post("/api/login", json={"email": email, "password": "demo1234"}).raise_for_status()
        self.token = self.http.post("/api/public/rincao/start", json={"name": "Teste"}).json()["token"]
        self.cid = self.http.get("/api/admin/conversations").json()[0]["id"]
        self.role_url = "/api/admin/conversations/" + self.cid + "/role"
        self.env = patch.dict(os.environ, {"TEST_TOOL_SECRET": "fake-secret"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.http.close(); self.other.close()
        self.session.configure(bind=self.previous)
        self.engine.dispose(); self.folder.cleanup()

    def send(self, content):
        return self.http.post("/api/client/" + self.token + "/messages", json={"content": content})

    def test_role_tenant_boundaries_and_denied_tool(self):
        from app import client, tools
        self.assertEqual(self.other.put(self.role_url, json={"role": "gestor"}).status_code, 404)
        self.assertEqual(self.http.put(self.role_url, json={"role": "admin"}).status_code, 422)
        self.assertEqual(self.http.get("/api/admin/conversations").json()[0]["role"], "cliente")
        answers = [{"reply": "", "action": "call_tool", "tool_call": {
            "name": "consultar_faturamento", "arguments": {"start_date": None, "end_date": None, "representative": None, "date_base": "evento"}}},
            {"reply": "Sem acesso a essa consulta", "action": "none"}]
        with patch.object(client, "reply", side_effect=answers) as model, patch.object(tools.urllib.request, "urlopen") as network:
            self.send("Qual o faturamento?").raise_for_status()
            network.assert_not_called()
            names = [t["name"] for t in model.call_args_list[0].kwargs["tools"]]
            self.assertNotIn("consultar_faturamento", names)
            self.assertIn("acesso_negado", model.call_args_list[1].args[0])
        from app.models import FeatureCall
        with self.session() as db:
            log = db.scalar(select(FeatureCall).where(FeatureCall.conversation_id == self.cid))
            self.assertEqual(json.loads(log.result)["error"], "acesso_negado")

    def test_public_validation_reaches_model_and_audit_without_raw_error(self):
        import urllib.error
        from app import client, tools
        body = b'{"error":"dados_invalidos","invalid_fields":[{"field":"cpf","reason":"invalid"}],"detail":"private technical error"}'
        answers = [{"reply": "", "action": "call_tool", "tool_call": {
            "name": "consultar_agenda", "arguments": {"start_date": None, "end_date": None}}},
            {"reply": "Confira o CPF, por favor.", "action": "none"}]
        error = urllib.error.HTTPError('http://local', 422, 'validation', {}, io.BytesIO(body))
        with patch.object(client, "reply", side_effect=answers) as model, patch.object(tools.urllib.request, "urlopen", side_effect=error):
            self.send("Continuar").raise_for_status()
            prompt = model.call_args_list[1].args[0]
            self.assertIn('"field": "cpf"', prompt)
            self.assertNotIn("private technical error", prompt)
        from app.models import FeatureCall
        with self.session() as db:
            logged = db.scalar(select(FeatureCall).where(FeatureCall.conversation_id == self.cid))
            self.assertEqual(json.loads(logged.result)["data"]["error"], "dados_invalidos")

    def test_service_context_reference_preserves_catalogue_for_followup(self):
        from app import tools
        result = b'{"ok":true,"context_reference":"catalog","products":[{"product_id":"p1","title":"Passeio"}]}'
        call = {"name": "consultar_agenda", "arguments": {"start_date": None, "end_date": None}}
        with patch.object(tools.urllib.request, "urlopen", return_value=io.BytesIO(result)):
            tools.execute_tool(self.tid, self.cid, call, 0)
        with self.session() as db:
            memory = tools.conversation_tool_context(db, self.tid, self.cid, "cliente")
            self.assertEqual(memory[0]["result"]["products"][0]["product_id"], "p1")

    def test_visit_slot_remains_in_prompt_after_confirmation_and_name(self):
        from app import client, tools
        available = {"ok": True, "environment": "TESTE", "context_reference": "horarios_TESTE_2099-01-15",
                     "slots": [{"slot_id": "slot-confirmed-choice", "start": "2099-01-15T14:00:00-03:00"}]}
        call = {"name": "consultar_agenda", "arguments": {"start_date": None, "end_date": None}}
        with patch.object(tools.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(available).encode())):
            tools.execute_tool(self.tid, self.cid, call, 0)
        with patch.object(client, "reply", return_value={"reply": "Qual nome devo informar?", "action": "none"}) as model:
            self.send("Confirmo esse horário").raise_for_status()
            self.assertIn('"slot_id": "slot-confirmed-choice"', model.call_args.args[0])
        with patch.object(client, "reply", return_value={"reply": "Nome recebido.", "action": "none"}) as model:
            self.send("Pessoa fictícia").raise_for_status()
            self.assertIn('"slot_id": "slot-confirmed-choice"', model.call_args.args[0])

    def test_breve_cannot_discover_or_execute_rincao_commerce_tools(self):
        from app import tools
        from app.models import Tenant
        self.other.post("/api/public/breve/start", json={"name": "Teste de isolamento"}).raise_for_status()
        cid = self.other.get("/api/admin/conversations").json()[0]["id"]
        with self.session() as db:
            tid = db.scalar(select(Tenant.id).where(Tenant.slug == "breve"))
            self.assertEqual(tools.available_tools(db, tid, "cliente"), [])
            self.assertEqual(tools.available_tools(db, tid, "gestor"), [])
            self.assertEqual(tools.conversation_tool_context(db, tid, cid, "gestor"), [])
        with patch.object(tools.urllib.request, "urlopen") as network:
            for name in ("consultar_agenda", "consultar_faturamento", "cotar_ingressos",
                         "criar_compra_ingressos", "consultar_compra_ingressos", "pesquisar_web", "consultar_previsao_tempo"):
                result = tools.execute_tool(tid, cid, {"name": name, "arguments": {}}, 0)
                self.assertEqual(result["error"], "acesso_negado")
            network.assert_not_called()

    def test_manager_result_logging_and_downgrade_history(self):
        from app import client, tools
        self.http.put(self.role_url, json={"role": "gestor"}).raise_for_status()
        answers = [{"reply": "", "action": "call_tool", "tool_call": {
            "name": "consultar_faturamento", "arguments": {"start_date": "2026-10-01", "end_date": "2026-10-29", "representative": None, "date_base": "evento"}}},
            {"reply": "Total financeiro confidencial: 1234,56", "action": "none"}]
        def service(request, **kwargs):
            data = json.loads(request.data)
            self.assertEqual(data["tenant_id"], self.tid)
            self.assertEqual(data["role"], "gestor")
            self.assertNotIn("sql", data["arguments"])
            return io.BytesIO(b'{"total":"1234.56"}')
        with patch.object(client, "reply", side_effect=answers) as model, patch.object(tools.urllib.request, "urlopen", side_effect=service):
            self.send("Faturamento de outubro?").raise_for_status()
            self.assertIn("1234.56", model.call_args_list[1].args[0])
        # Uma paráfrase posterior também deve herdar a restrição financeira.
        with patch.object(client, "reply", return_value={"reply": "Repetindo: 1234,56", "action": "none"}):
            self.send("Repete o total").raise_for_status()
        self.http.put(self.role_url, json={"role": "cliente"}).raise_for_status()
        with patch.object(client, "reply", return_value={"reply": "Como posso ajudar?", "action": "none"}) as model:
            self.send("O que conversamos?").raise_for_status()
            self.assertNotIn("1234,56", model.call_args.args[0])
        from app.models import FeatureCall
        with self.session() as db:
            log = db.scalar(select(FeatureCall).where(FeatureCall.conversation_id == self.cid))
            self.assertEqual(json.loads(log.result)["data"]["total"], "1234.56")
            self.assertGreaterEqual(int(log.duration_ms), 0)

    def test_role_change_during_inference_prevents_external_query(self):
        from app import client, tools
        self.http.put(self.role_url, json={"role": "gestor"}).raise_for_status()
        def choose(*args, **kwargs):
            self.http.put(self.role_url, json={"role": "cliente"}).raise_for_status()
            return {"reply": "", "action": "call_tool", "tool_call": {"name": "consultar_faturamento", "arguments": {}}}
        with patch.object(client, "reply", side_effect=lambda *a, **k: choose(*a, **k) if k.get("tools") else {"reply": "Sem acesso", "action": "none"}), patch.object(tools.urllib.request, "urlopen") as network:
            self.send("Qual faturamento?").raise_for_status()
            network.assert_not_called()
        self.assertFalse(any(m["sender"] == "lumi" for m in self.http.get("/api/client/" + self.token).json()["messages"]))

    def test_manager_can_still_request_handover(self):
        from app import client
        self.http.put(self.role_url, json={"role": "gestor"}).raise_for_status()
        with patch.object(client, "reply", return_value={"reply": "Fala gerada pela Lumi", "action": "handover"}), patch.object(client, "request_handover") as feature:
            self.send("Quero falar com um humano").raise_for_status()
            feature.assert_called_once()
        self.assertEqual(self.http.get("/api/client/" + self.token).json()["status"], "aguardando")

    def test_quote_is_available_next_turn_without_showing_internal_id(self):
        from app import client, tools
        quote_id = "q" * 43
        first = {"reply": "", "action": "call_tool", "tool_call": {"name": "cotar_ingressos",
            "arguments": {"visit_date": "2027-01-01", "ticket_type": "padrao", "adults": 2, "children": 0, "exempt": 0}}}
        with patch.object(client, "reply", side_effect=[first, {"reply": "O total é R$ 140.", "action": "none"}]), patch.object(
            tools.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps({"ok": True, "quote_id": quote_id, "totalAmount": 140}).encode())):
            self.send("Quero dois ingressos adultos para 1 de janeiro.").raise_for_status()
        self.assertNotIn(quote_id, json.dumps(self.http.get("/api/client/" + self.token).json()))
        with patch.object(client, "reply", return_value={"reply": "Vamos continuar.", "action": "none"}) as model:
            self.send("Pode continuar a compra.").raise_for_status()
            self.assertIn(quote_id, model.call_args.args[0])

    def test_buyer_context_comes_from_channel_and_cpf_is_masked_in_audit(self):
        from app import client, tools
        from app.models import FeatureCall
        from app.whatsapp.models import Channel, Chat
        with self.session.begin() as db:
            db.add(Channel(phone_number_id="test-phone", tenant_id=self.tid))
            db.flush()
            db.add(Chat(id=self.cid, phone_number_id="test-phone", sender="5511999999999", token=self.token))
        answers = [{"reply": "", "action": "call_tool", "tool_call": {
            "name": "criar_compra_ingressos", "arguments": {"quote_id": "q" * 43,
                "name": "Teste", "cpf": "52998224725", "phone": "0000000000", "email": None}}},
            {"reply": "Pagamento indisponível", "action": "none"}]
        def service(request, **kwargs):
            payload = json.loads(request.data)
            self.assertEqual(payload["context"]["whatsapp"], "5511999999999")
            self.assertEqual(payload["context"]["channel"], "whatsapp")
            self.assertTrue(any("529.982.247-25" in text for text in payload["context"]["customer_messages"]))
            return io.BytesIO(b'{"ok":false}')
        with patch.object(client, "reply", side_effect=answers), patch.object(tools.urllib.request, "urlopen", side_effect=service) as network:
            self.send("CPF de teste: 529.982.247-25").raise_for_status()
            network.assert_called_once()
        with self.session() as db:
            log = db.scalar(select(FeatureCall).where(FeatureCall.conversation_id == self.cid))
            self.assertEqual(json.loads(log.parameters)["cpf"], "***4725")

    def test_instagram_and_simulator_are_distinct_without_verified_phone(self):
        from app import tools
        from app.instagram.models import Channel, Chat
        from app.models import now
        call = {"name": "pesquisar_web", "arguments": {"query": "horário de parque público"}}
        def check(expected):
            def service(request, **kwargs):
                context = json.loads(request.data)["context"]
                self.assertEqual(context["channel"], expected)
                self.assertIsNone(context["whatsapp"])
                return io.BytesIO(b'{"ok":true}')
            with patch.object(tools.urllib.request, "urlopen", side_effect=service) as network:
                tools.execute_tool(self.tid, self.cid, call, 0)
                network.assert_called_once()
        check("simulator")
        with self.session.begin() as db:
            db.add(Channel(profile_id="test-profile", tenant_id=self.tid, token_env="unused"))
            db.flush()
            db.add(Chat(id=self.cid, profile_id="test-profile", sender="instagram-user", token=self.token,
                        last_incoming_at=now()))
        check("instagram")


class ExternalServiceTest(unittest.TestCase):
    def test_commerce_service_rejects_another_tenant_before_querying(self):
        from services.rincao import api
        http = TestClient(api.app)
        headers = {"Authorization": "Bearer fake"}
        body = {"tenant_id": "breve", "conversation_id": "chat", "role": "gestor",
                "arguments": {"visit_date": "2027-01-01", "ticket_type": "padrao",
                              "adults": 2, "children": 0, "exempt": 0}}
        with patch.dict(os.environ, {"RINCAO_TOOLS_SECRET": "fake", "RINCAO_TENANT_ID": "rincao"}), \
                patch.object(api, "quote_cart") as quote:
            self.assertEqual(http.post("/commerce/quote", json=body, headers=headers).status_code, 403)
            quote.assert_not_called()

    def test_representative_is_a_parameter_never_sql(self):
        from datetime import date
        from services.rincao import buffet
        injection = "nome' OR 1=1; DROP TABLE tevento; --"
        settings = {"BUFFET_DB_HOST": "test", "BUFFET_DB_NAME": "test", "BUFFET_DB_USER": "test", "BUFFET_DB_PASSWORD": "fake"}
        with patch.dict(os.environ, settings), patch.object(buffet.pymysql, "connect") as connect:
            cursor = connect.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = []
            result = buffet.query_revenue(date(2026, 10, 1), date(2026, 10, 29), "evento", injection)
            sql, parameters = cursor.execute.call_args.args
            self.assertNotIn(injection, sql)
            self.assertEqual(parameters[-1], injection)
            self.assertTrue(sql.lstrip().startswith("SELECT"))
            self.assertEqual(result["events"], 0)
            connect.return_value.rollback.assert_called_once()

    def test_external_auth_roles_dates_and_tenant(self):
        from services.rincao import api
        http = TestClient(api.app)
        body = {"tenant_id": "tenant-a", "conversation_id": "chat", "role": "cliente",
                "arguments": {"start_date": "2026-10-01", "end_date": "2026-10-29", "date_base": "evento", "representative": None}}
        with patch.dict(os.environ, {"RINCAO_TOOLS_SECRET": "fake", "RINCAO_TENANT_ID": "tenant-a"}), patch.object(api, "query_revenue", return_value={"total": "10.00"}) as query:
            self.assertEqual(http.post("/faturamento", json=body).status_code, 401)
            headers = {"Authorization": "Bearer fake"}
            self.assertEqual(http.post("/faturamento", json=body, headers=headers).status_code, 403)
            body["role"] = "gestor"; body["tenant_id"] = "tenant-b"
            self.assertEqual(http.post("/faturamento", json=body, headers=headers).status_code, 403)
            query.assert_not_called()
            body["tenant_id"] = "tenant-a"
            self.assertEqual(http.post("/faturamento", json=body, headers=headers).status_code, 200)
            body["arguments"]["start_date"] = "2026-11-01"
            self.assertEqual(http.post("/faturamento", json=body, headers=headers).status_code, 422)
            body["arguments"]["sql"] = "SELECT anything"
            self.assertEqual(http.post("/faturamento", json=body, headers=headers).status_code, 422)
