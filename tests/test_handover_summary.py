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

    def prepare_alert(self):
        from app.whatsapp.models import Channel,Chat,Outbox
        from app.whatsapp.handover_alerts import HandoverAlert
        with self.Session.begin() as db:
            db.add(Channel(phone_number_id="111111",tenant_id="t",token_env="FAKE"));db.flush()
            db.add(Chat(id="c",phone_number_id="111111",sender="15550000001",token="fake-token"));db.flush()
            db.add(Outbox(message_id="anchor",status="sent"));db.flush()
            db.add(HandoverAlert(message_id="anchor",phone_number_id="111111",topic="ingressos",status="pending"))
        import json
        return patch.dict(os.environ,{"LUMI_HANDOVER_ALERTS":json.dumps({"t":{"phone_number_id":"111111","recipient":"15550000002","admin_url":"https://admin.example.test","template":"approved_test"}})})

    def test_alert_uses_summary_and_does_not_send_again(self):
        from app.whatsapp.handover_alerts import deliver_alert
        with self.prepare_alert(),patch("app.providers.reply",return_value={"action":"none","reply":"O cliente não sabe como concluir a compra de dois ingressos para domingo."}),patch("app.whatsapp.handover_alerts.send_handover_template",return_value="meta-example") as send:
            self.assertTrue(deliver_alert());self.assertFalse(deliver_alert());send.assert_called_once()
            self.assertIn("não sabe como concluir",send.call_args.args[4]);self.assertIn("conversation=c",send.call_args.args[5])

    def test_claim_during_summary_cancels_the_alert(self):
        from app.whatsapp.handover_alerts import deliver_alert
        from app.models import Conversation
        def claim(*args,**kwargs):
            with self.Session.begin() as db:db.get(Conversation,"c").status="humano"
            return "Resumo contextual da solicitação."
        with self.prepare_alert(),patch("app.whatsapp.handover_alerts.summarize",side_effect=claim),patch("app.whatsapp.handover_alerts.send_handover_template") as send:
            self.assertTrue(deliver_alert());send.assert_not_called()
