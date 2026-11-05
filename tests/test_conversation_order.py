import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import create_engine
from app import main, admin
from app.db import Base, Session
from app.models import Tenant, Contact, Conversation, Message


class ConversationOrderTest(unittest.TestCase):
    def setUp(self):
        self.previous = Session.kw['bind']
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + self.folder.name + '/order.db')
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(Session.configure, bind=self.previous)
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        self.now = datetime.now(timezone.utc)
        with Session.begin() as db:
            for tid in ('a', 'b'):
                db.add(Tenant(id=tid, name=tid, slug=tid, identity='', personality=''))
            db.flush()
            for cid, tid, days in [('old', 'a', 10), ('new', 'a', 1), ('foreign', 'b', 0)]:
                db.add(Contact(id=cid, tenant_id=tid, name=cid, role='cliente'))
                db.flush()
                db.add(Conversation(id=cid, tenant_id=tid, contact_id=cid,
                    created_at=self.now-timedelta(days=days)))
        self.user = SimpleNamespace(tenant_id='a')

    def order(self):
        return [c['id'] for c in admin.conversations(self.user)]

    def test_new_message_moves_old_conversation_first_and_preserves_tenant_scope(self):
        self.assertEqual(self.order(), ['new', 'old'])
        with Session.begin() as db:
            db.add(Message(id='image', tenant_id='a', conversation_id='old', sender='cliente',
                content='[Imagem enviada]', created_at=self.now))
            db.add(Message(id='foreign-msg', tenant_id='b', conversation_id='foreign', sender='cliente',
                content='Outro tenant', created_at=self.now+timedelta(minutes=1)))
        self.assertEqual(self.order(), ['old', 'new'])
        with Session.begin() as db:
            db.add(Message(id='text', tenant_id='a', conversation_id='new', sender='cliente',
                content='Mensagem nova', created_at=self.now+timedelta(minutes=2)))
        self.assertEqual(self.order(), ['new', 'old'])

    def test_response_activity_and_equal_timestamps_have_stable_order(self):
        with Session.begin() as db:
            for cid in ('old', 'new'):
                db.add(Message(id='reply-'+cid, tenant_id='a', conversation_id=cid, sender='lumi',
                    content='Resposta', created_at=self.now))
        self.assertEqual(self.order(), ['new', 'old'])
        self.assertEqual(self.order(), ['new', 'old'])


if __name__ == '__main__':
    unittest.main()
