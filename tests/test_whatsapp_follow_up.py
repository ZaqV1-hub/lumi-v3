import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select

from app import client
from app.db import Base, Session
from app.documents import DocumentAsset, message_document
from app.models import Conversation, Message, Tenant
from app.whatsapp import bridge, follow_up, graph
from app.whatsapp.models import Channel, Outbox


class WhatsAppFollowUpTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        engine = create_engine("sqlite:///" + folder.name.replace("\\", "/") + "/test.db")
        self.addCleanup(engine.dispose)
        self.addCleanup(Session.configure, bind=Session.kw["bind"])
        Session.configure(bind=engine)
        Base.metadata.create_all(engine)
        with Session.begin() as db:
            tenant = Tenant(name="Empresa teste", slug="empresa", identity="Assistente", personality="Natural")
            other = Tenant(name="Outra", slug="outra", identity="Assistente", personality="Natural")
            db.add_all([tenant, other])
            db.flush()
            self.tid, self.other_tid = tenant.id, other.id
            channel = Channel(phone_number_id="12345", tenant_id=self.tid)
            other_channel = Channel(phone_number_id="54321", tenant_id=self.other_tid)
            db.add_all([channel, other_channel])
            db.flush()
            db.add(follow_up.FollowUpChannel(phone_number_id=channel.phone_number_id, tenant_id=self.tid))
            self.token = bridge.bind_sender(db, channel, "55510000", "Teste")
            self.other_token = bridge.bind_sender(db, other_channel, "55510000", "Teste")
            self.cid = db.scalar(select(Conversation.id).where(Conversation.tenant_id == self.tid))

    def answer(self, text, answer, token=None):
        receipt = client.receive_message(token or self.token, client.TextInput(content=text))
        with patch.object(client, "reply", return_value=answer) as model:
            client.process_message(receipt)
        return model

    def test_plain_greeting_gets_one_follow_up_five_minutes_after_acceptance(self):
        self.answer("Oi", "Olá, como posso ajudar?")
        self.answer("Oi", "Olá da outra empresa", self.other_token)
        sent_at = datetime.now(timezone.utc)
        with patch.object(bridge, "send", return_value="wamid.original"), patch.object(follow_up, "now", return_value=sent_at):
            self.assertTrue(bridge.deliver_one())
            self.assertTrue(bridge.deliver_one())
        with Session() as db:
            self.assertEqual(len(list(db.scalars(select(follow_up.FollowUp)))), 1)
        answer = {"action": "none", "reply": "Quer conhecer nossos empreendimentos?"}
        with patch.object(follow_up, "reply", return_value=answer) as model:
            follow_up.generate_due(clock=lambda: sent_at + timedelta(seconds=299), generate=model)
            model.assert_not_called()
            follow_up.generate_due(clock=lambda: sent_at + timedelta(seconds=300), generate=model)
            follow_up.generate_due(clock=lambda: sent_at + timedelta(seconds=310), generate=model)
            model.assert_called_once()
            self.assertIn('"mensagem": "Oi"', model.call_args.args[0])
        self.assertEqual(client.client_messages(self.token)["messages"][-1]["content"], answer["reply"])

    def test_confirmed_visit_stops_follow_up_until_customer_writes_again(self):
        from types import SimpleNamespace

        from app.admin import conversations
        from app.models import Feature, FeatureCall
        from app.visit_goal import VisitGoal

        with Session.begin() as db:
            db.add(Feature(tenant_id=self.tid, name="book_visit", description="", endpoint="", roles="cliente"))
            db.flush()
            db.add(VisitGoal(tenant_id=self.tid, feature="book_visit"))

        def record_confirmation(status):
            incoming_id = client.scoped_message_id(self.tid, self.cid)
            self.assertIsNotNone(incoming_id)
            with Session.begin() as db:
                db.add(FeatureCall(tenant_id=self.tid, conversation_id=self.cid, message_id=incoming_id,
                    feature="book_visit", parameters="{}", duration_ms="0",
                    result=json.dumps({"data": {"ok": True, "booking": {"booking_id": "demo", "status": status}}})))

        sent_at = datetime.now(timezone.utc)
        with patch.object(bridge, "send", side_effect=["wamid.pending", "wamid.confirmed", "wamid.new"]), \
             patch.object(follow_up, "now", return_value=sent_at):
            with patch.object(client, "reply", side_effect=lambda *a, **kw: (
                    record_confirmation("Pendente"), "Vou verificar a reserva.")[1]):
                client.process_message(client.receive_message(self.token, client.TextInput(content="Quero visitar")))
            self.assertTrue(bridge.deliver_one())
            with Session() as db:
                self.assertIsNotNone(db.scalar(select(follow_up.FollowUp)).due_at)
            operator = SimpleNamespace(id="operator", tenant_id=self.tid, console_role="brevia")
            self.assertFalse(conversations(operator)[0]["visit_confirmed"])

            def confirm(*args, **kwargs):
                record_confirmation("Confirmado")
                return "Visita confirmada."

            with patch.object(client, "reply", side_effect=confirm):
                client.process_message(client.receive_message(self.token, client.TextInput(content="Pode confirmar")))
            self.assertTrue(bridge.deliver_one())
            self.assertTrue(conversations(operator)[0]["visit_confirmed"])
            other_operator = SimpleNamespace(id="operator", tenant_id=self.other_tid, console_role="brevia")
            self.assertFalse(conversations(other_operator)[0]["visit_confirmed"])

            with patch.object(follow_up, "reply") as model:
                follow_up.generate_due(clock=lambda: sent_at + timedelta(minutes=5), generate=model)
                follow_up.generate_due(clock=lambda: sent_at + timedelta(minutes=5), generate=model)
                model.assert_not_called()

            self.answer("Qual o endereço?", "Segue o endereço da visita.")
            self.assertTrue(bridge.deliver_one())
        with patch.object(follow_up, "reply", return_value={"action": "none", "reply": "Quer ajuda com a rota?"}) as model:
            follow_up.generate_due(clock=lambda: sent_at + timedelta(minutes=5), generate=model)
            model.assert_called_once()

    def test_incoming_after_generation_cancels_outbox_delivery(self):
        self.answer("Oi", "Olá, como posso ajudar?")
        sent_at = datetime.now(timezone.utc)
        with patch.object(bridge, "send", return_value="wamid.original"), patch.object(follow_up, "now", return_value=sent_at):
            bridge.deliver_one()
        due = sent_at + timedelta(minutes=5)
        follow_up.generate_due(clock=lambda: due, generate=lambda *a, **kw: {"action": "none", "reply": "Retomada"})
        with Session.begin() as db:
            job = db.scalar(select(follow_up.FollowUp))
            follow_id = job.follow_up_id
            db.add(Message(tenant_id=self.tid, conversation_id=self.cid, sender="cliente",
                           content="Voltei", created_at=due + timedelta(seconds=1)))
        with patch.object(bridge, "send") as send:
            bridge.deliver_one()
            send.assert_not_called()
        with Session() as db:
            self.assertEqual(db.get(Outbox, follow_id).status, "cancelled")

    def test_requested_pdf_goes_through_outbox_as_native_document(self):
        with Session.begin() as db:
            document = DocumentAsset(tenant_id=self.tid, title="Book teste", filename="Book.pdf",
                                     description="Book comercial", data=b"%PDF-test")
            db.add(document)
            db.flush()
            document_id = document.id
        model = self.answer("Tem o book?", {"action": "send_document", "document_id": document_id, "reply": "Segue o book."})
        self.assertEqual(model.call_args.kwargs["document_ids"], [document_id])
        with patch.object(graph, "required", return_value="v23.0"), patch.object(graph, "access_token", return_value="test"):
            with patch.object(graph.httpx, "Client") as http:
                post = http.return_value.__enter__.return_value.post
                post.return_value.json.side_effect = [{"id": "123"}, {"messages": [{"id": "wamid.document"}]}]
                post.return_value.is_error = False
                self.assertTrue(bridge.deliver_one())
        self.assertEqual(post.call_args_list[0].kwargs["files"]["file"], ("Book.pdf", b"%PDF-test", "application/pdf"))
        self.assertEqual(post.call_args_list[1].kwargs["json"]["document"],
                         {"id": "123", "caption": "Segue o book.", "filename": "Book.pdf"})
        with Session() as db:
            mid = db.scalar(select(Outbox.message_id))
            self.assertIsNone(message_document(db, self.other_tid, self.cid, mid))
        self.assertEqual(client.client_messages(self.token)["messages"][-1]["attachment_kind"], "document")

    def test_provider_failure_retries_and_handover_during_generation_cancels(self):
        self.answer("Oi", "Olá, como posso ajudar?")
        sent_at = datetime.now(timezone.utc)
        with patch.object(bridge, "send", return_value="wamid.original"), patch.object(follow_up, "now", return_value=sent_at):
            bridge.deliver_one()
        due = sent_at + timedelta(minutes=5)
        with patch.object(follow_up, "reply", side_effect=TimeoutError) as model:
            with self.assertLogs(follow_up.log, "WARNING"):
                follow_up.generate_due(clock=lambda: due, generate=model)
            follow_up.generate_due(clock=lambda: due + timedelta(seconds=14), generate=model)
            model.assert_called_once()

        def take_over(*args, **kwargs):
            with Session.begin() as db:
                db.get(Conversation, self.cid).status = "humano"
            return {"action": "none", "reply": "Retomada"}

        follow_up.generate_due(clock=lambda: due + timedelta(seconds=15), generate=take_over)
        with Session() as db:
            job = db.scalar(select(follow_up.FollowUp))
            self.assertTrue(job.processed)
            self.assertIsNone(job.follow_up_id)

    def test_project_presentation_sends_captioned_photo_before_pdf_and_arms_one_follow_up(self):
        from app.media_models import ImageAsset

        with Session.begin() as db:
            image = ImageAsset(tenant_id=self.tid, name="Fachada", description="Projeto teste",
                               when_to_use="Apresentar o projeto", data=b"jpeg")
            document = DocumentAsset(tenant_id=self.tid, title="Book teste", filename="Book.pdf",
                                     description="Book do mesmo projeto", data=b"%PDF-test")
            db.add_all([image, document])
            db.flush()
            image_id, document_id = image.id, document.id
        self.answer("Quero conhecer esse projeto", {
            "action": "send_image_and_document", "image_id": image_id, "document_id": document_id,
            "image_intent": "send_catalog", "reply": "Conheça o projeto.",
        })
        with patch.object(bridge, "send", side_effect=["wamid.photo", "wamid.pdf"]) as send:
            self.assertTrue(bridge.deliver_one())
            with Session() as db:
                self.assertIsNone(db.scalars(select(follow_up.FollowUp)).one().due_at)
            self.assertTrue(bridge.deliver_one())
            self.assertFalse(bridge.deliver_one())
        self.assertEqual(send.call_args_list[0].args[3:], ("Conheça o projeto.", b"jpeg"))
        self.assertEqual(send.call_args_list[0].kwargs, {})
        self.assertEqual(send.call_args_list[1].args[3:], ("", None))
        self.assertEqual(send.call_args_list[1].kwargs, {"document": ("Book.pdf", b"%PDF-test")})
        with Session() as db:
            self.assertIsNotNone(db.scalars(select(follow_up.FollowUp)).one().due_at)
