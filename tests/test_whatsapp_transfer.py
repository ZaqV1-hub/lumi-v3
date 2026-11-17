import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import sessionmaker


class ChannelTransferTest(unittest.TestCase):
    def setUp(self):
        from app.db import Base
        from app.models import Tenant, Contact, Conversation, VisitorSession, Message
        from app.whatsapp.models import Channel, Chat, Outbox
        from app.whatsapp import bridge
        self.engine = create_engine("sqlite://")
        @event.listens_for(self.engine, "connect")
        def fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine)
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=t, slug=t, name=t, identity="", personality="") for t in ["a", "b"]])
            db.flush()
            db.add(Contact(id="c", tenant_id="a", name="Teste", role="cliente"))
            db.flush()
            db.add(Conversation(id="v", tenant_id="a", contact_id="c", status="lumi"))
            db.add(Channel(phone_number_id="111", tenant_id="a", token_env="FAKE_TOKEN"))
            db.flush()
            db.add(Chat(id="v", phone_number_id="111", sender="5511999999999", token="old-session"))
            db.add(VisitorSession(token="old-session", tenant_id="a", conversation_id="v"))
            db.flush()
            db.add(Message(id="m", tenant_id="a", conversation_id="v", sender="lumi", content="Resposta antiga"))

    def tearDown(self):
        self.engine.dispose()

    def test_transfer_preserves_history_starts_separate_contact_and_can_return(self):
        from app.whatsapp.transfer import transfer_channel
        from app.whatsapp.bridge import bind_sender
        from app.whatsapp.models import Channel, Chat, ArchivedChat, Outbox
        from app.models import Message, Conversation, VisitorSession
        from app.channels import channel_name
        with self.sessions.begin() as db:
            result = transfer_channel(db, "111", "b")
            self.assertEqual(result, {"changed": True, "archived": 1, "restored": 0})
            self.assertEqual(db.get(Message, "m").tenant_id, "a")
            self.assertEqual(db.get(VisitorSession, "old-session").tenant_id, "a")
            self.assertIsNone(db.get(Chat, "v"))
            self.assertIsNotNone(db.get(ArchivedChat, "v"))
            self.assertEqual(channel_name(db, "v"), "whatsapp")
            self.assertEqual(db.get(Outbox, "m").status, "cancelled")
            new_token = bind_sender(db, db.get(Channel, "111"), "5511999999999", "Teste")
            self.assertNotEqual(new_token, "old-session")
            db.flush()
            visitor = db.get(VisitorSession, new_token)
            self.assertEqual(visitor.tenant_id, "b")
            self.assertNotEqual(db.get(Conversation, visitor.conversation_id).contact_id, "c")
        with self.sessions.begin() as db:
            result = transfer_channel(db, "111", "a")
            self.assertEqual(result["restored"], 1)
            self.assertEqual(bind_sender(db, db.get(Channel,"111"), "5511999999999", "Teste"), "old-session")
            self.assertEqual(db.get(Conversation,"v").status,"lumi")
            self.assertFalse(transfer_channel(db,"111","a")["changed"])

    def test_busy_transfer_leaves_binding_unchanged(self):
        from app.whatsapp.transfer import transfer_channel
        from app.media_models import ContactGate
        from app.whatsapp.models import Channel, Chat
        with self.sessions.begin() as db:
            db.add(ContactGate(contact_id="c",pending=1))
        with self.assertRaises(ValueError), self.sessions.begin() as db:
            transfer_channel(db,"111","b")
        with self.sessions() as db:
            self.assertEqual(db.get(Channel,"111").tenant_id,"a")
            self.assertIsNotNone(db.get(Chat,"v"))

    def test_invalid_binding_and_cross_tenant_delivery_are_rejected(self):
        from app.whatsapp.bridge import bind_sender, deliver_one
        from app.whatsapp.models import Channel, Outbox
        with self.sessions.begin() as db:
            db.get(Channel,"111").tenant_id="b"
        with self.sessions() as db, self.assertRaises(RuntimeError):
            bind_sender(db,db.get(Channel,"111"),"5511999999999","Teste")
        with patch("app.whatsapp.bridge.Session",self.sessions), patch("app.whatsapp.bridge.send") as send:
            self.assertTrue(deliver_one())
            send.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(Outbox,"m").status,"cancelled")
