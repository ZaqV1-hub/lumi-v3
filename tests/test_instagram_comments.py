import hashlib
import hmac
import json
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from app.db import Base, Session
from app.main import app as admin_app
from app.models import Tenant, KnowledgeItem, FeatureCall
from app.seed import seed
from app.instagram.models import Channel
from app.instagram.comment_models import CommentJob, CommentSettings
from app.instagram import comments, comment_graph, webhook
from app.whatsapp.webhook import app


class Queue:
    def __init__(self): self.jobs = []
    def submit(self, job): self.jobs.append(job)


class CommentTest(unittest.TestCase):
    def setUp(self):
        self.previous = Session.kw["bind"]
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + self.folder.name + "/comments.db")
        Base.metadata.create_all(self.engine); Session.configure(bind=self.engine); seed()
        with Session.begin() as db:
            self.tid = db.scalar(select(Tenant.id).where(Tenant.slug == "rincao"))
            db.add(Channel(profile_id="111", tenant_id=self.tid, token_env="TOKEN", secret_env="SECRET")); db.flush()
            db.add(CommentSettings(profile_id="111", enabled=True, instructions="Convide a continuar pelo direct, sem frase fixa."))
            db.add(KnowledgeItem(tenant_id=self.tid, title="Privado", content="SEGREDO-NAO-PUBLICO"))
        self.queue = Queue()
        self.event = {"id": "333", "from": {"id": "444"}, "media": {"id": "555"}, "text": "Quero ingresso"}

    def tearDown(self):
        Session.configure(bind=self.previous); self.engine.dispose(); self.folder.cleanup()

    def test_signed_comment_is_deduplicated_and_never_enters_dm_pipeline(self):
        body = {"object": "instagram", "entry": [{"id": "111", "changes": [{"field": "comments", "value": self.event}]}]}
        raw = json.dumps(body).encode()
        signature = "sha256=" + hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
        with TestClient(app) as http, patch.object(webhook, "value", return_value="secret"), patch.object(webhook, "pool", self.queue), patch.object(webhook, "receive") as dm:
            self.assertEqual(http.post("/webhooks/instagram", content=raw).status_code, 401)
            for _ in range(2):
                self.assertEqual(http.post("/webhooks/instagram", content=raw, headers={"x-hub-signature-256": signature}).status_code, 200)
            dm.assert_not_called()
        self.assertEqual(len(self.queue.jobs), 1)

    def test_one_inference_no_tools_private_context_or_duplicate_public_reply(self):
        comments.receive("111", self.event, self.queue)
        with patch.object(comment_graph, "publication", return_value="Publicação do clube"), patch.object(comments, "reply", return_value={"reply": "Pode nos chamar no direct para continuar!", "action": "none"}) as model:
            self.queue.jobs[0]()
            model.assert_called_once()
            self.assertEqual(model.call_args.kwargs["tools"], [])
            self.assertNotIn("SEGREDO-NAO-PUBLICO", model.call_args.args[0])
            self.assertIn("Convide a continuar pelo direct", model.call_args.args[0])
        with patch.object(comment_graph, "respond", return_value="999") as publish:
            self.assertTrue(comments.deliver_one()); self.assertFalse(comments.deliver_one())
            publish.assert_called_once()
        with Session() as db:
            self.assertEqual(db.get(CommentJob, ("111", "333")).status, "sent")
            self.assertEqual(db.scalar(select(func.count()).select_from(FeatureCall)), 0)

    def test_disabled_unknown_profile_self_echo_and_rate_limit(self):
        comments.receive("222", self.event, self.queue)
        comments.receive("111", {**self.event, "from": {"id": "111"}}, self.queue)
        with Session.begin() as db: db.get(CommentSettings, "111").enabled = False
        comments.receive("111", self.event, self.queue)
        self.assertEqual(len(self.queue.jobs), 0)
        with Session.begin() as db: db.get(CommentSettings, "111").enabled = True
        for i in range(5):comments.receive("111", {**self.event, "id": str(300+i)}, self.queue)
        self.assertEqual(len(self.queue.jobs), 3)

    def test_requested_tool_is_not_executed_and_ambiguous_send_is_not_retried(self):
        comments.receive("111", self.event, self.queue)
        with patch.object(comment_graph, "publication", return_value="Post"), patch.object(comments, "reply", return_value={"reply": "", "action": "call_tool"}):
            self.queue.jobs[0]()
        with Session() as db:self.assertEqual(db.get(CommentJob, ("111", "333")).status, "ignored")
        with Session.begin() as db:
            row=db.get(CommentJob,("111","333"));row.status="ready";row.response="Resposta"
        with patch.object(comment_graph,"respond",side_effect=TimeoutError) as publish:
            comments.deliver_one();comments.deliver_one();publish.assert_called_once()
        with Session() as db:self.assertEqual(db.get(CommentJob,("111","333")).status,"failed")

    def test_pause_prevents_prepared_reply_from_being_published(self):
        comments.receive("111", self.event, self.queue)
        with Session.begin() as db:
            db.get(CommentJob,("111","333")).status="ready"
            db.get(CommentSettings,"111").enabled=False
        with patch.object(comment_graph,"respond") as publish:
            comments.deliver_one();publish.assert_not_called()

    def test_reply_echo_with_another_scoped_sender_is_ignored(self):
        comments.receive("111", self.event, self.queue)
        with Session.begin() as db:
            row=db.get(CommentJob,("111","333"));row.reply_id="999";row.status="sent"
        comments.receive("111",{**self.event,"id":"999","from":{"id":"888"}},self.queue)
        comments.receive("111",{**self.event,"media":[]},self.queue)
        self.assertEqual(len(self.queue.jobs),1)

    def test_settings_require_tenant_access_and_meta_permission_before_activation(self):
        from app.main import app as admin_app
        from app.instagram import comment_admin
        from fastapi import HTTPException
        with TestClient(admin_app) as operator,TestClient(admin_app) as other:
            operator.post('/api/login',json={'email':'isaque@rincao.local','password':'demo1234'}).raise_for_status()
            other.post('/api/login',json={'email':'ana@breve.local','password':'demo1234'}).raise_for_status()
            url='/api/admin/instagram/comments/111'
            self.assertEqual(other.get(url).status_code,404)
            with patch.object(comment_admin,'check_access',side_effect=HTTPException(409,'Permissão ausente')) as check:
                self.assertEqual(other.put(url,json={'enabled':True,'instructions':'Teste'}).status_code,404)
                check.assert_not_called()
                self.assertEqual(operator.put(url,json={'enabled':True,'instructions':'Teste'}).status_code,409)
                operator.put(url,json={'enabled':False,'instructions':'Instruções salvas'}).raise_for_status()
            self.assertEqual(operator.get(url).json(),{'enabled':False,'instructions':'Instruções salvas'})
