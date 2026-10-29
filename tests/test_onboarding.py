import json
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, select
from fastapi.testclient import TestClient


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        from app import main
        from app.db import Base, Session
        from app.seed import seed
        self.Session = Session
        self.previous = Session.kw["bind"]
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + self.folder.name + "/onboarding.db")
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        seed()
        self.admin = TestClient(main.app)
        self.other = TestClient(main.app)
        self.admin.post("/api/login", json={"email": "isaque@rincao.local", "password": "demo1234"}).raise_for_status()
        self.other.post("/api/login", json={"email": "ana@breve.local", "password": "demo1234"}).raise_for_status()
        self.name = self.objective("Como prefere ser chamado", True)
        self.reason = self.objective("Motivo do contato", False)
        self.token = self.admin.post("/api/public/rincao/start", json={"name": "NomeDoCanal"}).json()["token"]
        self.cid = self.admin.get("/api/admin/conversations").json()[0]["id"]

    def tearDown(self):
        self.admin.close()
        self.other.close()
        self.Session.configure(bind=self.previous)
        self.engine.dispose()
        self.folder.cleanup()

    def objective(self, title, updates_name):
        self.admin.post("/api/admin/onboarding", json={"title": title,
            "description": "Descobrir naturalmente com a própria pessoa", "required": True,
            "updates_name": updates_name}).raise_for_status()
        return next(f["id"] for f in self.admin.get("/api/admin/onboarding").json() if f["title"] == title)

    def send(self, text, updates=None, asked=None, effect=None):
        from app import client
        answer = {"reply": "Resposta de teste", "action": "none", "image_id": None,
                  "profile_updates": updates or [], "asked_objective_id": asked}
        with patch.object(client, "reply", side_effect=effect, return_value=answer) as model:
            self.admin.post("/api/client/" + self.token + "/messages", json={"content": text}).raise_for_status()
        return model.call_args.args[0]

    def state(self):
        return self.admin.get("/api/admin/conversations/" + self.cid + "/profile").json()

    def test_spontaneous_intent_name_completion_and_return(self):
        prompt = self.send("Quero valores dos ingressos", [{"objective_id": self.reason,
            "value": "valores dos ingressos", "evidence": "Quero valores dos ingressos"}], self.name)
        self.assertIn("Nome ainda não informado pela pessoa", prompt)
        self.assertNotIn("Contato atual: NomeDoCanal", prompt)
        self.assertEqual(self.state()["missing"], [self.name])
        self.send("Adalberto", [{"objective_id": self.name, "value": "Adalberto", "evidence": "Adalberto"}])
        self.assertTrue(self.state()["completed"])
        self.assertEqual(self.admin.get("/api/admin/conversations").json()[0]["name"], "Adalberto")
        prompt = self.send("Oi de novo")
        self.assertIn('"completed": true', prompt)
        self.assertEqual(self.state()["askable"], [])
        self.objective("Novo objetivo cadastrado depois", False)
        self.assertTrue(self.state()["completed"])
        self.assertEqual(self.state()["askable"], [])

    def test_ignored_question_not_repeated_or_forced(self):
        self.send("Oi", asked=self.name)
        self.assertNotIn(self.name, self.state()["askable"])
        self.send("Quero os preços", asked=self.name)
        self.send("Prefiro falar de ingressos", asked=self.name)
        self.send("Não vou dizer meu nome")
        state = self.state()
        field = next(f for f in state["fields"] if f["id"] == self.name)
        self.assertEqual(field["attempts"], 2)
        self.assertNotIn(self.name, state["askable"])
        self.assertFalse(state["completed"])

    def test_evidence_and_tenant_authorization(self):
        foreign = self.other.post("/api/admin/onboarding", json={"title": "Segredo",
            "description": "Objetivo da outra empresa"})
        foreign.raise_for_status()
        fid = self.other.get("/api/admin/onboarding").json()[0]["id"]
        self.send("Oi", [{"objective_id": fid, "value": "Oi", "evidence": "Oi"},
                         {"objective_id": self.name, "value": "Inventado", "evidence": "Inventado"},
                         {"objective_id": [], "value": "Oi", "evidence": "Oi"}])
        self.assertTrue(all(not f["value"] for f in self.state()["fields"]))
        self.assertEqual(self.other.get("/api/admin/conversations/" + self.cid + "/profile").status_code, 404)
        self.assertEqual(self.other.delete("/api/admin/onboarding/" + self.name).status_code, 404)
        self.assertEqual(self.other.put("/api/admin/onboarding/" + self.name,
            json={"title": "Ataque", "description": "Troca"}).status_code, 404)

    def test_human_intervention_discards_profile_and_response(self):
        def intervene(_):
            self.admin.post("/api/admin/conversations/" + self.cid + "/claim").raise_for_status()
            return {"reply": "Olá, Adalberto", "action": "none", "image_id": None,
                "profile_updates": [{"objective_id": self.name, "value": "Adalberto", "evidence": "Adalberto"}]}
        self.send("Adalberto", effect=intervene)
        self.assertTrue(all(not f["value"] for f in self.state()["fields"]))
        self.assertFalse(self.state()["completed"])
