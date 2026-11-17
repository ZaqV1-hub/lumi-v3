"""Durable calling state; all data is synthetic and all databases disposable."""
import hashlib
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker


class CallingStateTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        # Set safe defaults before app.db can initialize its engine.
        from unittest.mock import patch
        self.environment = patch.dict(os.environ, {
            'LUMI_DATA_DIR': self.folder.name, 'LOCALAPPDATA': self.folder.name,
        })
        self.environment.start()
        previous_url = os.environ.pop('DATABASE_URL', None)
        self.addCleanup(self.environment.stop)
        if previous_url is not None:
            self.addCleanup(os.environ.__setitem__, 'DATABASE_URL', previous_url)
        from app.db import Base
        from app.models import Contact, Conversation, LoginSession, Tenant, User
        from app.media_models import ConversationControl
        from app.whatsapp.models import Channel, Chat
        from app.whatsapp import calling, calling_setup
        from app.whatsapp.calling_models import CallOperation, CallPermission
        self.calling = calling
        self.setup = calling_setup
        self.Operation = CallOperation
        self.Permission = CallPermission
        self.engine = create_engine('sqlite:///' + self.folder.name + '/calling.db')
        self.addCleanup(self.engine.dispose)
        if self.engine.dialect.name == 'sqlite':
            @event.listens_for(self.engine, 'connect')
            def foreign_keys(connection, _):
                connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(self.engine, expire_on_commit=False)
        with self.session.begin() as db:
            db.add_all([Tenant(id='tenant', name='Demo', slug='calling-demo', identity='', personality=''),
                        Tenant(id='other', name='Other', slug='other-demo', identity='', personality='')])
            db.flush()
            db.add(LoginSession(token_hash='a' * 64, user_id='operator'))
            db.add_all([User(id='operator', tenant_id='tenant', name='Operator', email='operator@example.invalid', salt='', password_hash=''),
                        User(id='operator2', tenant_id='tenant', name='Operator2', email='operator2@example.invalid', salt='', password_hash=''),
                        Contact(id='contact', tenant_id='tenant', name='Demo'),
                        Contact(id='contact2', tenant_id='tenant', name='Demo2'),
                        Channel(phone_number_id='channel', tenant_id='tenant')])
            db.flush()
            for cid, contact in [('conversation', 'contact'), ('conversation2', 'contact2')]:
                db.add(Conversation(id=cid, tenant_id='tenant', contact_id=contact, status='humano'))
            db.flush()
            for cid, recipient in [('conversation', '5511000000001'), ('conversation2', '5511000000002')]:
                db.add(Chat(id=cid, phone_number_id='channel', sender=recipient, token='synthetic'))
                db.add(ConversationControl(conversation_id=cid, operator_id='operator'))
            self.setup.set_channel_enabled(db, tenant_id='tenant', phone_number_id='channel', enabled=True)
            for recipient in ['5511000000001', '5511000000002']:
                self.calling.update_permission(db, tenant_id='tenant', phone_number_id='channel', recipient=recipient,
                    state='granted', observed_at=self.calling.now()-timedelta(seconds=2), permanent=True)

    def reserve(self, db, **kwargs):
        args = dict(tenant_id='tenant', conversation_id='conversation', operator_id='operator',
                    idempotency_key='key', tab_token='synthetic-tab', session_hash='a' * 64,
                    offer_sdp='synthetic SDP')
        args.update(kwargs)
        return self.calling.reserve_call(db, **args)

    def test_disabled_default_and_wrong_tenant(self):
        from app.whatsapp.calling_models import CallingChannel
        with self.session.begin() as db:
            db.delete(db.get(CallingChannel, 'channel'))
        with self.session.begin() as db:
            self.assertFalse(self.calling.channel_enabled(db, tenant_id='tenant', phone_number_id='channel'))
            with self.assertRaises(HTTPException) as error:
                self.reserve(db)
            self.assertEqual(error.exception.status_code, 409)
        with self.session.begin() as db:
            with self.assertRaises(HTTPException) as error:
                self.reserve(db, tenant_id='other')
            self.assertEqual(error.exception.status_code, 404)

    def test_replay_and_parameter_conflict(self):
        with self.session.begin() as db:
            first = self.reserve(db)
            self.assertTrue(first.is_new)
        with self.session.begin() as db:
            replayed = self.reserve(db)
            self.assertEqual(replayed.id, first.id)
            self.assertFalse(replayed.is_new)
        with self.session.begin() as db:
            with self.assertRaises(HTTPException) as error:
                self.reserve(db, offer_sdp='different SDP')
            self.assertEqual(error.exception.status_code, 409)
        with self.session() as db:
            row = db.get(self.Operation, first.id)
            self.assertEqual(row.tab_token_hash, hashlib.sha256(b'synthetic-tab').hexdigest())
            self.assertEqual(row.session_hash, 'a' * 64)
            self.assertNotIn('synthetic SDP', str(row.__dict__))

    def test_requires_human_owner_and_writable_account(self):
        from app.models import Conversation
        from app.console_models import ConsoleAccount
        with self.session.begin() as db:
            with self.assertRaises(HTTPException):
                self.reserve(db, operator_id='operator2')
            db.get(Conversation, 'conversation').status = 'lumi'
        with self.session.begin() as db:
            with self.assertRaises(HTTPException):
                self.reserve(db)
            db.get(Conversation, 'conversation').status = 'humano'
            db.add(ConsoleAccount(user_id='operator', role='leitura'))
        with self.session.begin() as db:
            with self.assertRaises(HTTPException) as error:
                self.reserve(db)
            self.assertEqual(error.exception.status_code, 403)

    def test_uncertain_keeps_reservation_and_terminal_purges_sdp(self):
        with self.session.begin() as db:
            op = self.reserve(db)
            self.calling.update_operation(db, op, state='uncertain', external_id='external', answer_sdp='private SDP')
        with self.session.begin() as db:
            self.assertTrue(self.calling.has_active_call(db, tenant_id='tenant', conversation_id='conversation'))
            with self.assertRaises(HTTPException):
                self.reserve(db, idempotency_key='second')
        event = self.calling.NormalizedCallEvent(event_id='ended', kind='call', state='ended',
            external_id='external', occurred_at=self.calling.now())
        from app.whatsapp.models import Channel
        with self.session.begin() as db:
            self.assertTrue(self.calling.apply_call_event(db, channel=db.get(Channel, 'channel'), event=event))
            self.assertFalse(self.calling.apply_call_event(db, channel=db.get(Channel, 'channel'), event=event))
            self.assertFalse(self.calling.has_active_call(db, tenant_id='tenant', conversation_id='conversation'))
            self.assertIsNone(db.get(self.Operation, op.id).answer_sdp)
        with self.session.begin() as db:
            newer = self.reserve(db, idempotency_key='new')
            self.calling.update_operation(db, newer, external_id='new-external')
            late = self.calling.NormalizedCallEvent(event_id='late', kind='call', state='accepted',
                external_id='external', answer_sdp='private late SDP', occurred_at=self.calling.now())
            self.assertFalse(self.calling.apply_call_event(db, channel=db.get(Channel, 'channel'), event=late))
            self.assertEqual(db.get(self.Operation, op.id).state, 'ended')
            self.assertIsNone(db.get(self.Operation, op.id).answer_sdp)
            self.assertEqual(newer.state, 'reserved')

    def test_permission_expiration_and_stale_query_cannot_undo_revocation(self):
        now = self.calling.now()
        with self.session.begin() as db:
            self.calling.update_permission(db, tenant_id='tenant', phone_number_id='channel', recipient='5511000000001',
                state='granted', observed_at=now, expires_at=now-timedelta(seconds=1))
            self.assertEqual(self.calling.permission_state(db, tenant_id='tenant', phone_number_id='channel', recipient='5511000000001'), 'expired')
            with self.assertRaises(HTTPException):
                self.reserve(db)
            self.calling.update_permission(db, tenant_id='tenant', phone_number_id='channel', recipient='5511000000001',
                state='revoked', observed_at=now+timedelta(seconds=1))
            self.calling.update_permission(db, tenant_id='tenant', phone_number_id='channel', recipient='5511000000001',
                state='granted', observed_at=now, permanent=True)
            self.assertEqual(self.calling.permission_state(db, tenant_id='tenant', phone_number_id='channel', recipient='5511000000001'), 'revoked')

    def test_concurrent_operator_reservations_use_distinct_connections(self):
        barrier = threading.Barrier(2)
        def reserve(cid):
            with self.session.begin() as db:
                barrier.wait(timeout=5)
                try:
                    return self.reserve(db, conversation_id=cid, idempotency_key=cid).id
                except HTTPException as error:
                    return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ['conversation', 'conversation2']))
        self.assertEqual(results.count(409), 1)
        with self.session() as db:
            self.assertEqual(len(list(db.scalars(select(self.Operation)))), 1)

    def test_migration_repeat_preserves_existing_data_and_rejects_wrong_channel(self):
        from app.models import Conversation
        from app.whatsapp.models import Channel
        with self.session() as db:
            before = [(row.id, row.contact_id, row.status) for row in db.scalars(select(Conversation).order_by(Conversation.id))]
            channel_before = db.get(Channel, 'channel').token_env
        self.setup.prepare_schema(self.engine)
        self.setup.prepare_schema(self.engine)
        with self.session.begin() as db:
            after = [(row.id, row.contact_id, row.status) for row in db.scalars(select(Conversation).order_by(Conversation.id))]
            self.assertEqual(after, before)
            self.assertEqual(db.get(Channel, 'channel').token_env, channel_before)
            with self.assertRaises(HTTPException):
                self.setup.set_channel_enabled(db, tenant_id='other', phone_number_id='channel', enabled=True)

    def test_reserve_rejects_missing_or_expired_session(self):
        with self.session.begin() as db:
            with self.assertRaises(HTTPException) as error:
                self.reserve(db, session_hash='b' * 64)
            self.assertEqual(error.exception.status_code, 403)
            with self.assertRaises(HTTPException) as error:
                self.reserve(db, session_expires_at=self.calling.now()-timedelta(seconds=1))
            self.assertEqual(error.exception.status_code, 403)

    def test_heartbeat_rejects_other_tab_revoked_session_and_stale_owner(self):
        from app.media_models import ConversationControl
        from app.models import LoginSession
        with self.session.begin() as db:
            op = self.reserve(db)
        args = dict(tenant_id='tenant', operation_id=op.id, operator_id='operator',
                    tab_token='synthetic-tab', session_hash='a'*64, browser_state='connected')
        with self.session.begin() as db:
            with self.assertRaises(HTTPException):
                self.calling.heartbeat(db, **{**args, 'tab_token': 'other-tab'})
            updated = self.calling.heartbeat(db, **args)
            self.assertEqual(updated.state, 'reserved')
            self.assertEqual(updated.browser_state, 'connected')
            self.assertIsNotNone(updated.connected_at)
            self.assertGreater(updated.version, op.version)
            db.delete(db.get(LoginSession, 'a'*64))
        with self.session.begin() as db:
            with self.assertRaises(HTTPException):
                self.calling.heartbeat(db, **args)
            db.add(LoginSession(token_hash='a'*64, user_id='operator'))
            db.get(ConversationControl, 'conversation').operator_id = 'operator2'
        with self.session.begin() as db:
            with self.assertRaises(HTTPException):
                self.calling.heartbeat(db, **args)

    def test_permission_event_same_second_revocation_wins(self):
        from app.whatsapp.models import Channel
        instant = self.calling.now()+timedelta(seconds=1)
        with self.session.begin() as db:
            self.calling.update_permission(db, tenant_id='tenant', phone_number_id='channel', recipient='5511000000001',
                state='granted', observed_at=instant, permanent=True)
            event = self.calling.NormalizedCallEvent(event_id='revoke', kind='permission', state='revoked',
                recipient='5511000000001', occurred_at=instant)
            self.assertTrue(self.calling.apply_call_event(db, channel=db.get(Channel, 'channel'), event=event))
            self.assertEqual(self.calling.permission_state(db, tenant_id='tenant', phone_number_id='channel', recipient='5511000000001'), 'revoked')

    def test_permission_revocation_wins_query_microseconds_in_both_orders(self):
        instant = self.calling.now().replace(microsecond=0)+timedelta(seconds=2)
        query_started = instant+timedelta(milliseconds=500)
        for recipient, states in [('5511000000001', ['granted', 'revoked']),
                                  ('5511000000002', ['revoked', 'granted'])]:
            with self.subTest(states=states), self.session.begin() as db:
                for state in states:
                    self.calling.update_permission(db, tenant_id='tenant', phone_number_id='channel', recipient=recipient,
                        state=state, observed_at=query_started if state == 'granted' else instant,
                        permanent=state == 'granted')
                self.assertEqual(self.calling.permission_state(db, tenant_id='tenant', phone_number_id='channel', recipient=recipient), 'revoked')

    def test_permission_reservation_uncertain_is_not_repeated(self):
        args = dict(tenant_id='tenant', conversation_id='conversation', operator_id='operator', idempotency_key='permission')
        with self.session.begin() as db:
            self.calling.update_permission(db, tenant_id='tenant', phone_number_id='channel',
                recipient='5511000000001', state='absent', observed_at=self.calling.now())
            op = self.calling.reserve_permission(db, **args)
            self.calling.update_operation(db, op, state='uncertain')
        with self.session.begin() as db:
            replay = self.calling.reserve_permission(db, **args)
            self.assertEqual(replay.id, op.id)
            self.assertFalse(replay.is_new)
            with self.assertRaises(HTTPException):
                self.calling.reserve_permission(db, **{**args, 'idempotency_key': 'retry'})

    def test_concurrent_same_conversation_replays_once(self):
        barrier = threading.Barrier(2)
        def reserve(_):
            with self.session.begin() as db:
                barrier.wait(timeout=5)
                op = self.reserve(db)
                return op.id, op.is_new
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, range(2)))
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sum(item[1] for item in results), 1)

    def test_orphan_answer_reconciles_only_after_exact_external_binding(self):
        from app.whatsapp.models import Channel
        from app.whatsapp.calling_models import CallEvent
        with self.session.begin() as db:
            op = self.reserve(db)
        answer = self.calling.NormalizedCallEvent(event_id='early', kind='call', state='accepted',
            external_id='external', recipient='5511000000001', answer_sdp='private answer', occurred_at=self.calling.now())
        with self.session.begin() as db:
            self.calling.apply_call_event(db, channel=db.get(Channel, 'channel'), event=answer)
            self.assertEqual(db.get(self.Operation, op.id).state, 'reserved')
            self.assertIsNotNone(db.get(CallEvent, ('channel', 'early')))
        with self.session.begin() as db:
            current = db.get(self.Operation, op.id)
            self.calling.update_operation(db, current, state='initiating', external_id='external')
            self.assertEqual(current.state, 'accepted')
            self.assertEqual(current.answer_sdp, 'private answer')
            saved_event = db.get(CallEvent, ('channel', 'early'))
            self.assertTrue(saved_event.processed)
            self.assertIsNone(saved_event.answer_sdp)

    def test_database_rejects_second_active_conversation_even_different_operator(self):
        from sqlalchemy.exc import IntegrityError
        with self.session.begin() as db:
            first = self.reserve(db)
        with self.session.begin() as db:
            with self.assertRaises(IntegrityError):
                with db.begin_nested():
                    db.add(self.Operation(tenant_id='tenant', conversation_id='conversation', operator_id='operator2',
                        phone_number_id='channel', recipient='5511000000001', kind='call', idempotency_key='second', arguments_hash='b'*64))
                    db.flush()

    def test_absent_schema_reads_disabled_until_explicit_migration(self):
        from app.db import Base
        from app.whatsapp.calling_models import CALLING_TABLES
        Base.metadata.drop_all(self.engine, tables=list(reversed(CALLING_TABLES)))
        with self.session() as db:
            self.assertFalse(self.calling.channel_enabled(db, tenant_id='tenant', phone_number_id='channel'))
            self.assertFalse(self.calling.has_active_call(db, tenant_id='tenant', conversation_id='conversation'))
            self.assertEqual(self.calling.permission_state(db, tenant_id='tenant', phone_number_id='channel', recipient='5511000000001'), 'unknown')
        self.assertFalse(any(self.setup.inspect_schema(self.engine).values()))
        self.setup.prepare_schema(self.engine)
        self.setup.prepare_schema(self.engine)
        self.assertTrue(all(self.setup.inspect_schema(self.engine).values()))
        with self.session() as db:
            self.assertFalse(self.calling.channel_enabled(db, tenant_id='tenant', phone_number_id='channel'))

    def test_orphan_terminal_before_answer_does_not_reopen_or_retain_sdp(self):
        from app.whatsapp.models import Channel
        from app.whatsapp.calling_models import CallEvent
        instant = self.calling.now()
        with self.session.begin() as db:
            op = self.reserve(db)
            self.calling.apply_call_event(db, channel=db.get(Channel, 'channel'), event=self.calling.NormalizedCallEvent(
                event_id='early-end', kind='call', state='ended', external_id='external', occurred_at=instant))
            self.calling.apply_call_event(db, channel=db.get(Channel, 'channel'), event=self.calling.NormalizedCallEvent(
                event_id='late-answer', kind='call', state='accepted', external_id='external', answer_sdp='private',
                occurred_at=instant+timedelta(seconds=1)))
            self.calling.update_operation(db, op, external_id='external')
            self.assertEqual(op.state, 'ended')
            self.assertIsNone(op.answer_sdp)
            self.assertTrue(all(row.answer_sdp is None for row in db.scalars(select(CallEvent))))

    def test_wrong_channel_and_recipient_events_never_transition_call(self):
        from app.whatsapp.models import Channel
        with self.session.begin() as db:
            db.add(Channel(phone_number_id='other-channel', tenant_id='other'))
            db.flush()
            self.setup.set_channel_enabled(db, tenant_id='other', phone_number_id='other-channel', enabled=True)
            op = self.reserve(db)
            self.calling.update_operation(db, op, external_id='external')
            for channel, recipient in [('other-channel', '5511000000001'), ('channel', '5511000000002')]:
                self.assertFalse(self.calling.apply_call_event(db, channel=db.get(Channel, channel), event=self.calling.NormalizedCallEvent(
                    event_id=channel, kind='call', state='ended', external_id='external', operation_id=op.id,
                    recipient=recipient, occurred_at=self.calling.now())))
            self.assertTrue(op.active)

    def test_expired_orphan_sdp_is_purged_without_releasing_operation(self):
        from app.whatsapp.models import Channel
        from app.whatsapp.calling_models import CallEvent
        with self.session.begin() as db:
            op = self.reserve(db)
            self.calling.apply_call_event(db, channel=db.get(Channel, 'channel'), event=self.calling.NormalizedCallEvent(
                event_id='orphan', kind='call', state='accepted', external_id='unknown',
                answer_sdp='private orphan', occurred_at=self.calling.now()))
            db.get(CallEvent, ('channel', 'orphan')).received_at = self.calling.now()-timedelta(minutes=10)
        with self.session.begin() as db:
            self.assertEqual(self.calling.purge_expired_event_sdp(db), 1)
            self.assertIsNone(db.get(CallEvent, ('channel', 'orphan')).answer_sdp)
            self.assertTrue(db.get(self.Operation, op.id).active)

    def test_release_lock_serializes_against_reserve(self):
        from app.media_models import ConversationControl
        acquired = threading.Event()
        attempting = threading.Event()
        def release():
            with self.session.begin() as db:
                conversation = self.calling.lock_conversation(db, 'tenant', 'conversation')
                acquired.set()
                attempting.wait(timeout=5)
                conversation.status = 'lumi'
                db.get(ConversationControl, 'conversation').operator_id = None
        def reserve():
            acquired.wait(timeout=5)
            with self.session.begin() as db:
                attempting.set()
                try:
                    self.reserve(db)
                except HTTPException as error:
                    return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            releasing = pool.submit(release)
            reservation = pool.submit(reserve)
            releasing.result(timeout=10)
            self.assertEqual(reservation.result(timeout=10), 409)

    def test_concurrent_operator_calls_across_channels_use_unique_database_index(self):
        from app.whatsapp.models import Channel, Chat
        with self.session.begin() as db:
            db.add(Channel(phone_number_id='channel2', tenant_id='tenant'))
            db.flush()
            db.get(Chat, 'conversation2').phone_number_id = 'channel2'
            db.flush()
            self.setup.set_channel_enabled(db, tenant_id='tenant', phone_number_id='channel2', enabled=True)
            self.calling.update_permission(db, tenant_id='tenant', phone_number_id='channel2', recipient='5511000000002',
                state='granted', observed_at=self.calling.now(), permanent=True)
        self.test_concurrent_operator_reservations_use_distinct_connections()

    def test_duplicate_concurrent_events_transition_once(self):
        from app.whatsapp.models import Channel
        from app.whatsapp.calling_models import CallEvent
        with self.session.begin() as db:
            op = self.reserve(db)
            self.calling.update_operation(db, op, external_id='external')
        event = self.calling.NormalizedCallEvent(event_id='terminal', kind='call', state='ended',
            external_id='external', occurred_at=self.calling.now())
        barrier = threading.Barrier(2)
        def deliver(_):
            with self.session.begin() as db:
                barrier.wait(timeout=5)
                return self.calling.apply_call_event(db, channel=db.get(Channel, 'channel'), event=event)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(deliver, range(2))), 1)
        with self.session() as db:
            self.assertEqual(len(list(db.scalars(select(CallEvent)))), 1)

    def test_old_nonterminal_event_cannot_move_call_backward(self):
        with self.session.begin() as db:
            op = self.reserve(db)
            instant = self.calling.now()
            self.calling.update_operation(db, op, state='accepted', event_at=instant)
            self.assertFalse(self.calling.update_operation(db, op, state='ringing', event_at=instant-timedelta(seconds=1)))
            self.assertFalse(self.calling.update_operation(db, op, state='initiating'))
            self.assertEqual(op.state, 'accepted')

    def test_late_connect_answer_preserves_accepted_state(self):
        with self.session.begin() as db:
            op = self.reserve(db)
            instant = self.calling.now()
            self.calling.update_operation(db, op, state='accepted', event_at=instant)
            self.assertTrue(self.calling.update_operation(db, op, state='initiating', answer_sdp='private answer',
                external_id='external', event_at=instant-timedelta(seconds=1)))
            self.assertEqual(op.state, 'accepted')
            self.assertEqual(op.answer_sdp, 'private answer')
            self.assertEqual(self.calling.utc(op.event_at), self.calling.utc(instant))

    def test_disable_refuses_active_and_uncertain_calls(self):
        with self.session.begin() as db:
            op = self.reserve(db)
            for state in ['reserved', 'uncertain']:
                self.calling.update_operation(db, op, state=state)
                with self.assertRaises(HTTPException) as error:
                    self.setup.set_channel_enabled(db, tenant_id='tenant', phone_number_id='channel', enabled=False)
                self.assertEqual(error.exception.status_code, 409)
                self.assertTrue(self.calling.channel_enabled(db, tenant_id='tenant', phone_number_id='channel'))
            self.calling.update_operation(db, op, state='ended')
            self.setup.set_channel_enabled(db, tenant_id='tenant', phone_number_id='channel', enabled=False)
            self.assertFalse(self.calling.channel_enabled(db, tenant_id='tenant', phone_number_id='channel'))


@unittest.skipUnless(os.getenv('LUMI_TEST_POSTGRES_URL'), 'PostgreSQL de teste não configurado')
class PostgresCallingStateTest(CallingStateTest):
    def setUp(self):
        from sqlalchemy import text
        from sqlalchemy.engine import make_url
        from unittest.mock import patch
        from uuid import uuid4
        url = make_url(os.environ['LUMI_TEST_POSTGRES_URL'])
        if url.get_backend_name() != 'postgresql' or url.host not in {'localhost', '127.0.0.1', '::1'}:
            raise RuntimeError('Use PostgreSQL local de teste explícito')
        admin = create_engine(url, isolation_level='AUTOCOMMIT', hide_parameters=True)
        name = 'lumi_calling_test_' + uuid4().hex
        with admin.connect() as db:
            db.execute(text('CREATE DATABASE ' + name))
        engine = create_engine(url.set(database=name), hide_parameters=True)
        def cleanup():
            engine.dispose()
            with admin.connect() as db:
                db.execute(text('DROP DATABASE ' + name + ' WITH (FORCE)'))
            admin.dispose()
        self.addCleanup(cleanup)
        with patch(__name__ + '.create_engine', return_value=engine):
            super().setUp()


if __name__ == '__main__':
    unittest.main()
