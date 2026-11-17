import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


class ReplyDeliveryTest(unittest.TestCase):
    def setUp(self):
        from app.db import Base
        from app.models import Tenant, Contact, Conversation
        from app.reply_delivery import ReplyDelivery
        from app.whatsapp.models import Channel, Chat
        from app.whatsapp import bridge
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(Tenant(id='a', slug='a', name='A', identity='', personality=''))
        self.db.flush()
        self.db.add(Contact(id='c', tenant_id='a', name='Teste', role='cliente'))
        self.db.flush()
        self.db.add(Conversation(id='v', tenant_id='a', contact_id='c', status='lumi'))
        self.db.flush()
        self.db.add_all([ReplyDelivery(tenant_id='a', max_chars=200), Channel(phone_number_id='1', tenant_id='a')])
        self.db.flush()
        self.db.add(Chat(id='v', phone_number_id='1', sender='12345', token='t'))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_preserves_text_and_url(self):
        from app.reply_delivery import split_reply
        url = 'https://example.org/' + 'x' * 350
        text = 'Primeira frase. ' * 40 + '\n\nVeja ' + url + ' agora.'
        parts = split_reply(text, 200)
        self.assertGreater(len(parts), 1)
        self.assertEqual(' '.join(text.split()), ' '.join(' '.join(parts).split()))
        self.assertTrue(any(url in part for part in parts))
        self.assertEqual(split_reply('Resposta curta.', 200), ['Resposta curta.'])

    def test_queue_order_pause_and_opt_in(self):
        from app.models import Conversation
        from app.reply_delivery import save_reply, may_deliver, ReplyDelivery, ReplyPart
        from app.whatsapp.models import Outbox
        from app.media_models import ConversationControl
        rows = save_reply(self.db, 'a', 'v', 'Primeira frase. ' * 70, 0)
        self.db.commit()
        self.assertGreater(len(rows), 1)
        queued = self.db.scalars(select(Outbox).order_by(Outbox.created_at, Outbox.message_id)).all()
        self.assertEqual([r.id for r in rows], [r.message_id for r in queued])
        self.assertEqual([r.created_at for r in rows], [r.created_at for r in queued])
        self.assertTrue(all(may_deliver(self.db, r) for r in rows))
        self.db.get(Conversation, 'v').status = 'humano'
        self.assertTrue(all(not may_deliver(self.db, r) for r in rows))
        self.db.get(Conversation, 'v').status = 'lumi'
        self.db.add(ConversationControl(conversation_id='v', revision=1))
        self.db.flush()
        self.assertFalse(may_deliver(self.db, rows[-1]))
        self.db.delete(self.db.get(ReplyDelivery, 'a'))
        self.db.flush()
        legacy = save_reply(self.db, 'a', 'v', 'Longa. ' * 300, 1)
        self.assertEqual(len(legacy), 1)
        self.assertIsNone(self.db.get(ReplyPart, legacy[0].id))

    def test_typing_contract_failure_and_human_skip(self):
        from app.whatsapp.typing import notify_processing
        from app.models import Conversation
        receipt = dict(tenant_id='a', conversation_id='v', contact_id='c', revision=0, whatsapp_external_id='wamid.fake')
        with patch('app.whatsapp.typing.Session', sessionmaker(self.engine)), patch('app.whatsapp.typing.required', return_value='v23.0'), patch('app.whatsapp.typing.access_token', return_value='fake'), patch('app.whatsapp.typing.httpx.Client') as http:
            response = http.return_value.__enter__.return_value.post.return_value
            response.is_error = False
            response.json.return_value = {'success': True}
            notify_processing(receipt)
            payload = http.return_value.__enter__.return_value.post.call_args.kwargs['json']
            self.assertEqual(payload, {'messaging_product': 'whatsapp', 'status': 'read', 'message_id': 'wamid.fake', 'typing_indicator': {'type': 'text'}})
            response.is_error = True
            notify_processing(receipt)
            self.db.get(Conversation, 'v').status = 'humano'
            self.db.commit()
            http.reset_mock()
            notify_processing(receipt)
            http.assert_not_called()
