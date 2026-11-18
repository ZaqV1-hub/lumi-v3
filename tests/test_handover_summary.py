import os
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine

class BriefTest(unittest.TestCase):
    def setUp(self):
        from app import schema
        from app.db import Base, Session
        from app.models import Tenant, Contact, Conversation, Message
        from app.handover_summary import HandoverBrief
        self.Session=Session; self.previous=Session.kw["bind"]
        self.folder=tempfile.TemporaryDirectory(); self.engine=create_engine("sqlite:///"+self.folder.name+"/test.db")
        Base.metadata.create_all(self.engine); Session.configure(bind=self.engine)
        with Session.begin() as db:
            db.add_all([Tenant(id="t",name="Example",slug="example",identity="",personality=""),Tenant(id="other",name="Other",slug="other",identity="",personality="")]); db.flush()
            db.add(Contact(id="p",tenant_id="t",name="Example",role="cliente")); db.flush()
            db.add(Conversation(id="c",tenant_id="t",contact_id="p",status="aguardando")); db.flush()
            db.add_all([Message(id="question",tenant_id="t",conversation_id="c",sender="cliente",content="Não entendi como comprar dois ingressos para domingo."),Message(id="anchor",tenant_id="t",conversation_id="c",sender="lumi",content="Vou solicitar apoio.")])
    def tearDown(self):
        self.Session.configure(bind=self.previous); self.engine.dispose();self.folder.cleanup()
    def test_summary_is_scoped_and_cached_without_repeating_model(self):
        from app.handover_summary import summarize
        with patch("app.providers.reply",return_value={"action":"none","reply":"O cliente quer comprar dois ingressos para domingo, mas não entendeu como concluir a compra."}) as model:
            text=summarize("t","c","anchor");self.assertIn("não entendeu",text)
            self.assertEqual(text,summarize("t","c","anchor"));model.assert_called_once()
            with self.assertRaises(ValueError):summarize("other","c","anchor")
    def test_failure_uses_only_real_customer_context_and_masks_private_data(self):
        from app.handover_summary import summarize,clean
        with patch("app.providers.reply",side_effect=RuntimeError("unavailable")):
            self.assertIn("dois ingressos",summarize("t","c","anchor"))
        self.assertNotIn("example@sample.test",clean("example@sample.test https://example.test/private"))
        self.assertNotIn("12345678901",clean("CPF 12345678901"))
