"""Signed Calling fixtures from docs/whatsapp-calling.md, with synthetic identities."""
import hashlib
import hmac
import json
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select


class CallingWebhookTest(unittest.TestCase):
    def setUp(self):
        from test_whatsapp_calling import CallingStateTest
        CallingStateTest.setUp(self)
        self.reserve = lambda db, **kw: CallingStateTest.reserve(self, db, **kw)
        from app.db import Session
        from app.whatsapp import webhook, calling_webhook
        from app.whatsapp.calling_models import CallEvent
        self.Session, self.webhook, self.adapter, self.Event = Session, webhook, calling_webhook, CallEvent
        previous = Session.kw['bind']
        Session.configure(bind=self.engine)
        self.addCleanup(Session.configure, bind=previous)
        self.receive = patch.object(webhook, 'receive').start()
        self.delivery = patch.object(webhook, 'record_delivery').start()
        self.reject = patch.object(calling_webhook.calling_graph, 'reject').start()
        self.secret = patch.object(webhook, 'app_secret', return_value='synthetic-secret').start()
        self.addCleanup(patch.stopall)
        self.http = TestClient(webhook.app)
        self.addCleanup(self.http.close)
        with self.session.begin() as db:
            self.op = self.reserve(db)
        self.stamp = str(int((self.calling.now()+timedelta(seconds=2)).timestamp()))

    def post(self, value, field='calls', secret='synthetic-secret', phone='channel'):
        body = {'object':'whatsapp_business_account','entry':[{'id':'waba-demo','changes':[
            {'field':field,'value':{'messaging_product':'whatsapp','metadata':{'phone_number_id':phone},**value}}]}]}
        raw = json.dumps(body).encode()
        return self.http.post('/webhooks/whatsapp', content=raw, headers={
            'x-hub-signature-256':'sha256='+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()})

    def call(self, event='connect', **kw):
        return {'id':'wacid.demo','event':event,'timestamp':self.stamp,'direction':'BUSINESS_INITIATED',
                'to':'5511000000001','from':'15555550101','biz_opaque_callback_data':self.op.id,**kw}

    def test_connect_before_http_response_status_terminal_and_replay(self):
        value = {'calls':[self.call(session={'sdp_type':'answer','sdp':'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'})]}
        self.assertEqual(self.post(value).status_code,200)
        self.assertEqual(self.post(value).status_code,200)
        with self.session.begin() as db:
            op = db.get(self.Operation,self.op.id)
            self.assertEqual(op.external_id,'wacid.demo')
            self.assertTrue(op.answer_sdp)
            self.calling.update_operation(db,op,state='initiating',external_id='wacid.demo')
        self.assertEqual(self.post({'statuses':[{'id':'wacid.demo','type':'call','status':'ACCEPTED','timestamp':self.stamp,
                                                'recipient_id':'5511000000001'}]}).status_code,200)
        terminal = {'calls':[self.call('terminate',status='COMPLETED')]}
        self.assertEqual(self.post(terminal).status_code,200)
        self.assertEqual(self.post(value).status_code,200)
        with self.session() as db:
            op = db.get(self.Operation,self.op.id)
            self.assertFalse(op.active)
            self.assertEqual(op.state,'ended')
            self.assertIsNone(op.answer_sdp)
            self.assertEqual(len(list(db.scalars(select(self.Event)))),3)
        self.receive.assert_not_called()
        self.delivery.assert_not_called()

    def test_permission_without_message_type_never_enters_chat(self):
        message = {'id':'wamid.reply','from':'5511000000001','timestamp':self.stamp,
                   'interactive':{'type':'call_permission_reply','call_permission_reply':{
                       'response':'reject','response_source':'automatic'}}}
        self.assertEqual(self.post({'messages':[message]},'messages').status_code,200)
        with self.session() as db:
            self.assertEqual(self.calling.permission_state(db,tenant_id='tenant',phone_number_id='channel',recipient='5511000000001'),'revoked')
        self.receive.assert_not_called()

    def test_permission_temporary_and_permanent_shapes(self):
        for permanent in [False,True]:
            with self.subTest(permanent=permanent):
                stamp = int(self.stamp)+(1 if permanent else 0)
                reply = {'response':'accept','is_permanent':permanent,'response_source':'user_action'}
                if not permanent:
                    reply['expiration_timestamp'] = str(stamp+604800)
                msg = {'id':'wamid.'+str(permanent),'from':'5511000000001','timestamp':str(stamp),
                       'interactive':{'type':'call_permission_reply','call_permission_reply':reply}}
                self.assertEqual(self.post({'messages':[msg]},'messages').status_code,200)
                with self.session() as db:
                    row = db.get(self.Permission,('tenant','channel','5511000000001'))
                    self.assertEqual(row.state,'granted')
                    self.assertEqual(row.permanent,permanent)
                    self.assertEqual(row.expires_at is None,permanent)

    def test_disabled_invalid_signature_and_wrong_recipient_have_no_effect(self):
        from app.whatsapp.calling_models import CallingChannel
        self.assertEqual(self.post({'calls':[self.call()]},secret='wrong').status_code,401)
        self.assertEqual(self.post({'calls':[self.call('terminate',status='FAILED',to='5511000000002')]}).status_code,200)
        with self.session.begin() as db:
            self.assertTrue(db.get(self.Operation,self.op.id).active)
            db.get(CallingChannel,'channel').enabled=False
        self.assertEqual(self.post({'calls':[self.call('terminate',status='COMPLETED')]}).status_code,200)
        with self.session() as db:
            self.assertEqual(list(db.scalars(select(self.Event))),[])
        self.receive.assert_not_called()
        self.reject.assert_not_called()

    def test_incoming_reject_is_durable_and_never_retries_timeout(self):
        from app.whatsapp.calling_graph import GraphError
        self.reject.side_effect = GraphError('service_unavailable',uncertain=True)
        inbound = self.call(direction='USER_INITIATED',session={'sdp_type':'offer','sdp':'v=0'})
        inbound.pop('biz_opaque_callback_data')
        with self.assertLogs('app.whatsapp.calling_webhook',level='WARNING') as logs:
            for _ in range(2):
                self.assertEqual(self.post({'calls':[inbound]}).status_code,200)
        self.assertEqual(len(logs.output),1)
        self.reject.assert_called_once()
        with self.session() as db:
            events = list(db.scalars(select(self.Event).where(self.Event.kind=='incoming')))
            self.assertEqual(len(events),1)
            self.assertEqual(events[0].state,'uncertain')
        self.receive.assert_not_called()

    def test_text_and_delivery_still_follow_existing_path(self):
        msg = {'id':'wamid.text','from':'5511000000001','type':'text','text':{'body':'synthetic'}}
        self.assertEqual(self.post({'messages':[msg],'statuses':[{'id':'wamid.sent','status':'delivered'}]},'messages').status_code,200)
        self.receive.assert_called_once()
        self.delivery.assert_called_once()

    def test_malformed_permission_is_consumed_without_chat_side_effect(self):
        msg = {'id':'wamid.bad','from':'5511000000001','timestamp':self.stamp,
               'interactive':{'type':'call_permission_reply','call_permission_reply':{'response':'accept','is_permanent':False}}}
        with self.assertLogs('app.whatsapp.calling_webhook',level='WARNING'):
            self.assertEqual(self.post({'messages':[msg]},'messages').status_code,200)
        self.receive.assert_not_called()

    def test_mixed_secret_batch_is_rejected_before_calls_or_messages(self):
        from app.whatsapp.models import Channel
        with self.session.begin() as db:
            db.add(Channel(phone_number_id='other-channel',tenant_id='other',token_env='OTHER_TOKEN'))
        self.secret.side_effect = lambda token=None: 'other-secret' if token == 'OTHER_TOKEN' else 'synthetic-secret'
        body = {'object':'whatsapp_business_account','entry':[{'changes':[
            {'field':'calls','value':{'metadata':{'phone_number_id':'channel'},'calls':[self.call('terminate',status='COMPLETED')]}},
            {'field':'messages','value':{'metadata':{'phone_number_id':'other-channel'},'messages':[]}}]}]}
        raw = json.dumps(body).encode()
        response = self.http.post('/webhooks/whatsapp',content=raw,headers={
            'x-hub-signature-256':'sha256='+hmac.new(b'synthetic-secret',raw,hashlib.sha256).hexdigest()})
        self.assertEqual(response.status_code,401)
        with self.session() as db:
            self.assertTrue(db.get(self.Operation,self.op.id).active)
            self.assertEqual(list(db.scalars(select(self.Event))),[])

    def test_no_correlation_does_not_bind_to_current_conversation(self):
        event = self.call('terminate',status='COMPLETED')
        event.pop('biz_opaque_callback_data')
        self.assertEqual(self.post({'calls':[event]}).status_code,200)
        with self.session() as db:
            op = db.get(self.Operation,self.op.id)
            self.assertTrue(op.active)
            self.assertIsNone(op.external_id)

    def test_answer_after_accepted_preserves_state_and_still_binds_media(self):
        self.assertEqual(self.post({'statuses':[{'id':'wacid.demo','type':'call','status':'ACCEPTED',
            'timestamp':str(int(self.stamp)+1),'recipient_id':'5511000000001',
            'biz_opaque_callback_data':self.op.id}]}).status_code,200)
        answer = 'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'
        self.assertEqual(self.post({'calls':[self.call(session={'sdp_type':'answer','sdp':answer})]}).status_code,200)
        with self.session() as db:
            op = db.get(self.Operation,self.op.id)
            self.assertEqual(op.state,'accepted')
            self.assertEqual(op.answer_sdp,answer)

    def test_business_status_rejected_and_failed_terminate_are_terminal(self):
        self.assertEqual(self.post({'statuses':[{'id':'wacid.demo','type':'call','status':'REJECTED',
            'timestamp':self.stamp,'recipient_id':'5511000000001','biz_opaque_callback_data':self.op.id}]}).status_code,200)
        self.assertEqual(self.post({'calls':[self.call('terminate',status='FAILED')],
            'errors':[{'code':138006,'message':'synthetic private error'}]}).status_code,200)
        with self.session() as db:
            self.assertFalse(db.get(self.Operation,self.op.id).active)
        self.receive.assert_not_called()

    def test_call_events_do_not_create_message_or_outbox(self):
        from app.models import Message
        from app.whatsapp.models import Outbox
        self.assertEqual(self.post({'calls':[self.call('terminate',status='COMPLETED')]}).status_code,200)
        with self.session() as db:
            self.assertEqual(list(db.scalars(select(Message))),[])
            self.assertEqual(list(db.scalars(select(Outbox))),[])
