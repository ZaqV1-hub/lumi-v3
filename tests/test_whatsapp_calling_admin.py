"""Authorization and lifecycle of human calls; all contacts and media are synthetic."""
import hashlib
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

SDP = 'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=rtpmap:111 opus/48000/2\r\na=fingerprint:sha-256 AA:BB\r\na=ice-ufrag:synthetic\r\n'
GRANTED = {'state': 'granted', 'permanent': True, 'expires_at': None, 'can_call': True, 'can_request': False}
ABSENT = {'state': 'absent', 'permanent': False, 'expires_at': None, 'can_call': False, 'can_request': True}


class CallingAdminTest(unittest.TestCase):
    def setUp(self):
        from app import main
        from app.db import Base, Session
        from app.models import Contact, Conversation, Tenant, User
        from app.seed import seed
        from app.whatsapp.models import Channel, Chat

        self.folder = tempfile.TemporaryDirectory()
        self.previous = Session.kw['bind']
        self.engine = create_engine('sqlite:///' + self.folder.name + '/calling-admin.db')
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(lambda: Session.configure(bind=self.previous))
        seed()
        self.http = TestClient(main.app)
        self.other = TestClient(main.app)
        self.addCleanup(self.http.close)
        self.addCleanup(self.other.close)
        self.http.post('/api/login', json={'email': 'isaque@rincao.local', 'password': 'demo1234'}).raise_for_status()
        self.other.post('/api/login', json={'email': 'ana@breve.local', 'password': 'demo1234'}).raise_for_status()
        with Session.begin() as db:
            self.tid = db.scalar(select(Tenant.id).where(Tenant.slug == 'rincao'))
            self.uid = db.scalar(select(User.id).where(User.email == 'isaque@rincao.local'))
            contact = Contact(tenant_id=self.tid, name='Contato fictício', role='cliente')
            db.add(contact)
            db.flush()
            conversation = Conversation(tenant_id=self.tid, contact_id=contact.id)
            db.add(conversation)
            db.flush()
            self.cid = conversation.id
            db.add(Channel(phone_number_id='111', tenant_id=self.tid, token_env='CALLING_TEST_TOKEN'))
            db.flush()
            db.add(Chat(id=self.cid, phone_number_id='111', sender='5511000000001', token='synthetic-chat'))
        self.path = '/api/admin/conversations/' + self.cid + '/calling'
        self.headers = {'Origin': 'http://testserver', 'X-Calling-Tab': 'test-tab-token-' + 'a' * 40}
        self.session_hash = hashlib.sha256(self.http.cookies.get('lumi_session').encode()).hexdigest()

    def test_calling_requires_authenticated_tenant_scoped_session(self):
        from app import main
        with TestClient(main.app) as anonymous:
            self.assertEqual(anonymous.get(self.path).status_code, 401)
            self.assertEqual(anonymous.post(self.path + '/permission', json={'idempotency_key': 'test-1'}, headers=self.headers).status_code, 401)
        self.assertEqual(self.other.get(self.path).status_code, 404)
        self.assertEqual(self.http.get(self.path).status_code, 200)
        self.assertFalse(self.http.get(self.path).json()['enabled'])

    def test_read_only_and_foreign_origin_cannot_request_permission(self):
        from app.db import Session
        from app.console_models import ConsoleAccount
        payload = {'idempotency_key': 'test-permission'}
        with Session.begin() as db:
            db.add(ConsoleAccount(user_id=self.uid, role='leitura'))
        self.assertEqual(self.http.post(self.path + '/permission', json=payload, headers=self.headers).status_code, 403)
        with Session.begin() as db:
            db.get(ConsoleAccount, self.uid).role = 'admin'
        self.assertEqual(self.http.post(self.path + '/permission', json=payload,
                         headers={**self.headers, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.http.post(self.path + '/permission', json=payload).status_code, 403)

    def test_browser_cannot_supply_destination_or_video(self):
        payload = {'idempotency_key': 'test-call', 'sdp_offer': 'v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n'}
        self.assertEqual(self.http.post(self.path + '/calls', json=payload, headers=self.headers).status_code, 422)
        payload.update(to='5511000000002')
        self.assertEqual(self.http.post(self.path + '/calls', json=payload, headers=self.headers).status_code, 422)

    def enable(self):
        from app.db import Session
        from app.models import Message
        from app.whatsapp.calling_setup import set_channel_enabled
        with Session.begin() as db:
            set_channel_enabled(db, tenant_id=self.tid, phone_number_id='111', enabled=True)
            db.add(Message(tenant_id=self.tid, conversation_id=self.cid, sender='cliente', content='Mensagem fictícia recente'))
        self.http.post('/api/admin/conversations/' + self.cid + '/claim').raise_for_status()

    def start(self, key='test-call'):
        return self.http.post(self.path + '/calls', json={'idempotency_key': key, 'sdp_offer': SDP}, headers=self.headers)

    def test_start_replay_tab_ownership_and_release_block(self):
        from app.db import Session
        from app.models import Conversation
        self.enable()
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(GRANTED)), \
             patch('app.whatsapp.calling_graph.connect', return_value='wacid.synthetic') as connect:
            response = self.start()
            self.assertEqual(response.status_code, 200, response.text)
            call = response.json()
            replay = self.start()
            self.assertEqual(replay.json()['id'], call['id'])
            connect.assert_called_once_with('111', 'CALLING_TEST_TOKEN', '5511000000001', SDP, call['id'])
            self.assertEqual(self.http.post(self.path + '/calls', json={'idempotency_key': 'test-call', 'sdp_offer': SDP + 'a=sendrecv\r\n'}, headers=self.headers).status_code, 409)
            self.assertEqual(self.start('second-call').status_code, 409)
        url = self.path + '/calls/' + call['id']
        self.assertEqual(self.http.get(url, headers=self.headers).status_code, 200)
        self.assertEqual(self.http.get(url, headers={**self.headers, 'X-Calling-Tab': 'b' * 48}).status_code, 403)
        self.assertEqual(self.other.get(url, headers=self.headers).status_code, 404)
        self.assertEqual(self.http.post('/api/admin/conversations/' + self.cid + '/release').status_code, 409)
        with Session() as db:
            self.assertEqual(db.get(Conversation, self.cid).status, 'humano')
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_unknown_connect_result_is_not_retried_or_released(self):
        from app.whatsapp.calling_graph import GraphError
        self.enable()
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(GRANTED)), \
             patch('app.whatsapp.calling_graph.connect', side_effect=GraphError('service_unavailable', uncertain=True)) as connect:
            first = self.start().json()
            self.assertEqual(first['state'], 'uncertain')
            self.assertTrue(first['active'])
            self.assertEqual(self.start().json()['id'], first['id'])
            connect.assert_called_once()
        self.assertEqual(self.http.post('/api/admin/conversations/' + self.cid + '/release').status_code, 409)

    def test_lookup_original_attempt_recovers_terminal_and_enforces_ownership(self):
        from app.whatsapp.calling_graph import GraphError
        self.enable()
        url = self.path + '/calls/by-key/test-call'
        self.assertEqual(self.http.get(url, headers=self.headers).json(), {'call': None})
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(GRANTED)), \
             patch('app.whatsapp.calling_graph.connect', side_effect=GraphError('rejected')) as connect:
            original = self.start().json()
            recovered = self.http.get(url, headers=self.headers)
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json()['call']['id'], original['id'])
            self.assertEqual(recovered.json()['call']['state'], 'failed')
            self.assertFalse(recovered.json()['call']['active'])
            connect.assert_called_once()
        self.assertEqual(recovered.headers['cache-control'], 'no-store')
        self.assertEqual(self.http.get(url, headers={**self.headers, 'X-Calling-Tab': 'b' * 48}).status_code, 403)
        self.assertEqual(self.other.get(url, headers=self.headers).status_code, 404)
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(GRANTED)), \
             patch('app.whatsapp.calling_graph.connect') as connect:
            self.assertIsNone(self.http.get(self.path + '/calls/by-key/not-reserved', headers=self.headers).json()['call'])
            connect.assert_not_called()

    def test_permission_failure_never_uses_cached_grant(self):
        from app.db import Session
        from app.whatsapp import calling
        from app.whatsapp.calling_graph import GraphError
        self.enable()
        with Session.begin() as db:
            calling.update_permission(db, tenant_id=self.tid, phone_number_id='111', recipient='5511000000001',
                state='granted', permanent=True, observed_at=calling.now())
        with patch('app.whatsapp.calling_graph.get_permission', side_effect=GraphError('service_unavailable')), \
             patch('app.whatsapp.calling_graph.connect') as connect:
            self.assertEqual(self.start().status_code, 503)
            self.assertFalse(self.http.get(self.path).json()['can_call'])
            connect.assert_not_called()

    def test_granted_permission_disables_requests_even_if_graph_allows_them(self):
        self.enable()
        with patch('app.whatsapp.calling_graph.get_permission', return_value={**GRANTED, 'can_request': True}), \
             patch('app.whatsapp.calling_graph.request_permission') as send:
            status = self.http.get(self.path).json()
            self.assertEqual(status['permission']['state'], 'granted')
            self.assertTrue(status['can_call'])
            self.assertFalse(status['can_request_permission'])
            response = self.http.post(self.path + '/permission', json={'idempotency_key': 'consent'}, headers=self.headers)
            self.assertEqual(response.status_code, 409)
            send.assert_not_called()

    def test_permission_request_is_deduplicated_and_outside_window_is_blocked(self):
        from app.db import Session
        from app.models import Message, now
        from app.whatsapp.models import Outbox
        self.enable()
        with Session() as db:
            before_messages = len(list(db.scalars(select(Message))))
            before_outbox = len(list(db.scalars(select(Outbox))))
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(ABSENT)), \
             patch('app.whatsapp.calling_graph.request_permission', return_value='wamid.permission') as send:
            for _ in range(2):
                response = self.http.post(self.path + '/permission', json={'idempotency_key': 'consent'}, headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
            send.assert_called_once()
            with Session.begin() as db:
                for message in db.scalars(select(Message).where(Message.sender == 'cliente')):
                    message.created_at = now() - timedelta(hours=25)
            self.assertEqual(self.http.post(self.path + '/permission', json={'idempotency_key': 'later'}, headers=self.headers).status_code, 409)
            self.assertEqual(send.call_count, 1)
        with Session() as db:
            self.assertEqual(len(list(db.scalars(select(Message)))), before_messages)
            self.assertEqual(len(list(db.scalars(select(Outbox)))), before_outbox)

    def test_webhook_before_http_and_terminal_never_reopens(self):
        from app.db import Session
        from app.whatsapp import calling
        from app.whatsapp.models import Channel
        self.enable()
        def accept_then_end(phone, token, recipient, offer, opid):
            with Session.begin() as db:
                calling.apply_call_event(db, channel=db.get(Channel, phone), event=calling.NormalizedCallEvent(
                    event_id='end-before-http', kind='call', state='ended', occurred_at=calling.now(),
                    external_id='wacid.synthetic', operation_id=opid, recipient=recipient))
            return 'wacid.synthetic'
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(GRANTED)), \
             patch('app.whatsapp.calling_graph.connect', side_effect=accept_then_end):
            response = self.start()
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['state'], 'ended')
            self.assertFalse(response.json()['active'])
            self.assertIsNone(response.json()['answer_sdp'])
        self.assertEqual(self.http.post('/api/admin/conversations/' + self.cid + '/release').status_code, 200)

    def test_call_appears_once_in_admin_timeline_and_stays_out_of_client_history(self):
        from app.db import Session
        from app.models import Message, VisitorSession
        from app.whatsapp import calling
        from app.whatsapp.calling_models import CallOperation

        self.enable()
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(GRANTED)), \
             patch('app.whatsapp.calling_graph.connect', return_value='wacid.synthetic'):
            call_id = self.start().json()['id']
        with Session.begin() as db:
            call = db.get(CallOperation, call_id)
            calling.update_operation(db, call, state='accepted')
            call.connected_at = calling.now() - timedelta(seconds=18)
            calling.update_operation(db, call, state='ended')
            db.add(Message(tenant_id=self.tid, conversation_id=self.cid, sender='cliente',
                           content='Mensagem depois da chamada'))
            db.add(VisitorSession(token='synthetic-visitor', tenant_id=self.tid, conversation_id=self.cid))

        path = '/api/admin/conversations'
        detail = self.http.get(path + '/' + self.cid).json()['messages']
        listing = next(row for row in self.http.get(path).json() if row['id'] == self.cid)
        self.assertEqual(listing['messages'], detail)
        self.assertEqual([item.get('event_kind') for item in detail].count('whatsapp_call'), 1)
        self.assertEqual(detail[-2]['id'], f'call:{call_id}')
        self.assertIn('encerrada · 0:18', detail[-2]['content'])
        self.assertEqual(detail[-1]['content'], 'Mensagem depois da chamada')
        self.assertEqual(self.other.get(path + '/' + self.cid).status_code, 404)
        self.assertNotIn(f'call:{call_id}', [item['id'] for item in self.http.get('/api/client/synthetic-visitor').json()['messages']])

    def test_logout_and_expired_heartbeat_trigger_bounded_termination(self):
        from app.db import Session
        from app.models import now
        from app.whatsapp.calling_models import CallOperation
        from app.whatsapp.calling_reconcile import reconcile_once
        self.enable()
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(GRANTED)), \
             patch('app.whatsapp.calling_graph.connect', return_value='wacid.synthetic'):
            call = self.start().json()
        url = self.path + '/calls/' + call['id']
        self.assertEqual(self.http.post(url + '/heartbeat', json={'browser_state': 'connected'}, headers=self.headers).status_code, 200)
        self.http.post('/api/logout')
        self.assertEqual(self.http.get(url, headers=self.headers).status_code, 401)
        with patch('app.whatsapp.calling_graph.terminate') as terminate:
            for i in range(4):
                with Session.begin() as db:
                    db.get(CallOperation, call['id']).reconcile_after = now() - timedelta(seconds=1)
                reconcile_once()
            self.assertEqual(terminate.call_count, 3)
        with Session() as db:
            op = db.get(CallOperation, call['id'])
            self.assertTrue(op.active)
            self.assertEqual(op.state, 'uncertain')
            self.assertEqual(op.public_error, 'termination_unconfirmed')

    def test_cancel_before_external_id_still_terminates_when_id_arrives(self):
        from app.db import Session
        from app.whatsapp import calling
        from app.whatsapp.calling_models import CallOperation
        from app.whatsapp.calling_reconcile import reconcile_once
        from app.whatsapp.calling_graph import GraphError
        self.enable()
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(GRANTED)), \
             patch('app.whatsapp.calling_graph.connect', side_effect=GraphError('service_unavailable', uncertain=True)):
            call = self.start().json()
        url = self.path + '/calls/' + call['id']
        with patch('app.whatsapp.calling_graph.terminate') as terminate:
            self.http.post(url + '/terminate', json={'idempotency_key': 'end'}, headers=self.headers).raise_for_status()
            terminate.assert_not_called()
            with Session.begin() as db:
                calling.update_operation(db, db.get(CallOperation, call['id']), external_id='wacid.late')
            reconcile_once()
            terminate.assert_called_once_with('111', 'CALLING_TEST_TOKEN', 'wacid.late')

    def test_cancel_during_connect_survives_late_timeout_and_binding_with_healthy_lease(self):
        from app.db import Session
        from app.whatsapp import calling
        from app.whatsapp.models import Channel
        from app.whatsapp.calling_models import CallOperation
        from app.whatsapp.calling_graph import GraphError
        from app.whatsapp.calling_reconcile import reconcile_once
        self.enable()
        def cancel_before_timeout(phone, token, recipient, offer, opid):
            self.http.post(self.path + '/calls/' + opid + '/terminate',
                json={'idempotency_key': 'cancel'}, headers=self.headers).raise_for_status()
            raise GraphError('service_unavailable', uncertain=True)
        with patch('app.whatsapp.calling_graph.get_permission', return_value=dict(GRANTED)), \
             patch('app.whatsapp.calling_graph.connect', side_effect=cancel_before_timeout) as connect, \
             patch('app.whatsapp.calling_graph.terminate') as terminate:
            response = self.start()
            response.raise_for_status()
            call = response.json()
            terminate.assert_not_called()
            with Session.begin() as db:
                calling.apply_call_event(db, channel=db.get(Channel, '111'), event=calling.NormalizedCallEvent(
                    event_id='late-binding', kind='call', state='initiating', occurred_at=calling.now(),
                    operation_id=call['id'], external_id='wacid.late', recipient='5511000000001'))
            self.http.post(self.path + '/calls/' + call['id'] + '/heartbeat',
                json={'browser_state': 'connected'}, headers=self.headers).raise_for_status()
            with Session() as db:
                op = db.get(CallOperation, call['id'])
                self.assertGreater(calling.utc(op.lease_expires_at), calling.now())
                self.assertEqual(op.terminate_attempts, 0)
            reconcile_once()
            terminate.assert_called_once_with('111', 'CALLING_TEST_TOKEN', 'wacid.late')
            self.assertEqual(connect.call_count, 1)
            with Session() as db:
                self.assertTrue(db.get(CallOperation, call['id']).active)

    def test_history_is_limited_scoped_and_does_not_expose_media_or_session(self):
        from app.db import Session
        from app.models import Contact, Conversation, User, now
        from app.whatsapp.models import Channel
        from app.whatsapp.calling_models import CallOperation
        with Session.begin() as db:
            other_user = db.scalar(select(User).where(User.email == 'ana@breve.local'))
            contact = Contact(tenant_id=other_user.tenant_id, name='Outro contato fictício')
            db.add(contact)
            db.flush()
            other_conversation = Conversation(tenant_id=other_user.tenant_id, contact_id=contact.id)
            db.add(other_conversation)
            db.add(Channel(phone_number_id='222', tenant_id=other_user.tenant_id))
            db.flush()
            instant = now()
            for index in range(11):
                db.add(CallOperation(id='history-' + str(index), tenant_id=self.tid, conversation_id=self.cid,
                    operator_id=self.uid, phone_number_id='111', recipient='5511000000001', kind='call',
                    idempotency_key='history-' + str(index), arguments_hash='private-arguments', state='ended', active=False,
                    created_at=instant-timedelta(seconds=index), answer_sdp='private-media',
                    session_hash='private-session', tab_token_hash='private-tab'))
            db.add(CallOperation(id='foreign-history', tenant_id=other_user.tenant_id, conversation_id=other_conversation.id,
                operator_id=other_user.id, phone_number_id='222', recipient='5511000000002', kind='call',
                idempotency_key='foreign-history', arguments_hash='private-foreign', state='ended', active=False))
        response = self.http.get(self.path)
        response.raise_for_status()
        history = response.json()['history']
        self.assertEqual([op['id'] for op in history], ['history-' + str(index) for index in range(10)])
        self.assertTrue(all(op['operator_name'] and op['created_at'] for op in history))
        for private in ['private-', '5511000000001', 'foreign-history', 'answer_sdp', 'session_hash', 'tab_token_hash']:
            self.assertNotIn(private, response.text)
        self.assertEqual(self.other.get(self.path).status_code, 404)

    def test_history_is_empty_before_explicit_calling_migration(self):
        from app.db import Base
        from app.whatsapp.calling_models import CALLING_TABLES
        Base.metadata.drop_all(self.engine, tables=list(reversed(CALLING_TABLES)))
        response = self.http.get(self.path)
        response.raise_for_status()
        self.assertEqual(response.json()['history'], [])
        self.assertFalse(response.json()['enabled'])


from test_postgres_flows import postgres_case

PostgresCallingAdminTest = postgres_case(CallingAdminTest)
