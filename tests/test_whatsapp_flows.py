import base64
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select


class Pool:
    def __init__(self): self.jobs = []
    def submit(self, fn, *args): self.jobs.append((fn, args))
    def run(self):
        fn, args = self.jobs.pop(0)
        fn(*args)


class FlowTest(unittest.TestCase):
    def setUp(self):
        from app import main
        from app.db import Base, Session
        from app.models import Tenant
        from app.whatsapp import webhook
        from app.whatsapp.models import Channel
        self.Session = Session
        self.previous = Session.kw['bind']
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.engine = create_engine('sqlite:///' + self.folder.name + '/test.db')
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(Session.configure, bind=self.previous)
        self.tid = '11111111-1111-4111-8111-111111111111'
        with Session.begin() as db:
            db.add(Tenant(id=self.tid, name='Example', slug='flows-example', identity='', personality=''))
            db.add(Tenant(id='other', name='Other', slug='other', identity='', personality=''))
            db.flush()
            db.add(Channel(phone_number_id='12345', tenant_id=self.tid, token_env='EXAMPLE_TOKEN'))
        self.config = {'tenant_id':self.tid,'flow_id':'555','enabled':True,
            'private_key_path':str(Path(self.folder.name)/'key.pem')}
        path = Path(self.folder.name)/'flows.json'
        path.write_text(json.dumps({'12345':self.config}), encoding='utf-8')
        env = patch.dict(os.environ, {'LUMI_WHATSAPP_FLOWS_FILE':str(path)})
        env.start(); self.addCleanup(env.stop)
        self.pool = Pool()
        self.webhook = webhook

    def launch(self, event='initial'):
        from app.whatsapp.bridge import receive
        receive('12345', {'id':event,'from':'15550000001','type':'text','text':{'body':'Olá'}}, 'Example customer', self.pool)
        from app.whatsapp.flows.models import FlowLaunch
        from app.whatsapp.models import Chat
        with self.Session() as db:
            launch = db.scalar(select(FlowLaunch))
            self.token = launch.token
            self.sid = launch.session_id
            self.original = db.scalar(select(Chat.id))

    def exchange(self, action='INIT', data=None):
        from app.whatsapp.flows.runtime import exchange
        return exchange('12345', self.config, {'action':action,'flow_token':self.token,'data':data or {}}, self.pool)

    def test_launch_and_real_engine_replies_never_enter_whatsapp_outbox(self):
        from app.models import Message
        from app.whatsapp.models import Outbox
        from app.whatsapp.flows.models import FlowSession, FlowTurn
        self.launch()
        before = self.exchange()
        data = {'question':'Como funciona?', 'nonce':before['data']['nonce']}
        queued = self.exchange('data_exchange', data)
        self.assertFalse(queued['data']['can_ask'])
        self.exchange('data_exchange', data)  # Meta retry while the first inference is running.
        self.assertEqual(len(self.pool.jobs), 1)
        with patch('app.client.reply', return_value='Resposta fictícia confirmada.') as provider:
            self.pool.run()
            self.assertEqual(provider.call_count, 1)
        result = self.exchange()
        self.assertIn('Resposta fictícia confirmada.', result['data']['history'])
        self.assertTrue(result['data']['can_ask'])
        self.exchange('data_exchange', data)  # Retry after completion must also be idempotent.
        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(FlowTurn)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Outbox)), 1)  # Only the opener.
            cid = db.get(FlowSession, self.sid).conversation_id
            self.assertEqual(db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id==cid)), 2)

    def test_wrong_tenant_channel_expiry_and_disabled_config_fail_closed(self):
        from app.whatsapp.flows.runtime import exchange
        from app.whatsapp.flows.models import FlowSession
        from app.models import now
        from app.whatsapp.models import Channel
        self.launch()
        with self.assertRaises(HTTPException):
            exchange('12345', dict(self.config,tenant_id='other'), {'action':'INIT','flow_token':self.token}, self.pool)
        with self.Session.begin() as db: db.get(Channel,'12345').tenant_id='other'
        with self.assertRaises(HTTPException): self.exchange()
        with self.Session.begin() as db:
            db.get(Channel,'12345').tenant_id=self.tid
            db.get(FlowSession,self.sid).expires_at=now()-timedelta(seconds=1)
        with self.assertRaises(HTTPException): self.exchange()

    def test_human_claim_before_generation_prevents_ai_reply(self):
        from app.whatsapp.flows.models import FlowSession
        from app.models import Conversation, Message
        self.launch()
        initial=self.exchange()
        self.exchange('data_exchange', {'question':'Uma dúvida', 'nonce':initial['data']['nonce']})
        with self.Session.begin() as db:
            cid=db.get(FlowSession,self.sid).conversation_id
            db.get(Conversation,cid).status='humano'
        with patch('app.client.reply') as provider:
            self.pool.run(); provider.assert_not_called()
        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id==cid,Message.sender=='lumi')),0)

    def test_encrypted_signed_endpoint_roundtrip_and_tampering(self):
        from app.whatsapp.flows import routes
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        Path(self.config['private_key_path']).write_bytes(private.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        key=os.urandom(16);iv=os.urandom(16)
        payload=json.dumps({'version':'3.0','action':'ping'}).encode()
        encoded=lambda b:base64.b64encode(b).decode()
        envelope={'encrypted_aes_key':encoded(private.public_key().encrypt(key,padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))),
            'initial_vector':encoded(iv),'encrypted_flow_data':encoded(AESGCM(key).encrypt(iv,payload,None))}
        raw=json.dumps(envelope).encode()
        signature='sha256='+hmac.new(b'fake-app-secret',raw,hashlib.sha256).hexdigest()
        http=TestClient(self.webhook.app)
        with patch.object(routes,'process_pool',self.pool),patch.object(routes,'app_secret',return_value='fake-app-secret'):
            self.assertEqual(http.post('/webhooks/whatsapp/flows/12345',content=raw).status_code,403)
            result=http.post('/webhooks/whatsapp/flows/12345',content=raw,headers={'x-hub-signature-256':signature})
            self.assertEqual(result.status_code,200)
            plain=AESGCM(key).decrypt(bytes(v^255 for v in iv),base64.b64decode(result.text),None)
            self.assertEqual(json.loads(plain)['data']['status'],'active')
            self.assertEqual(http.post('/webhooks/whatsapp/flows/12345',content=raw+b' ',headers={'x-hub-signature-256':signature}).status_code,403)

    def test_unknown_billing_is_not_assumed_free(self):
        from app.whatsapp.bridge import record_delivery
        from app.whatsapp.flows.models import FlowPricing
        record_delivery('12345',{'id':'fake-delivery','status':'sent','pricing':{'category':'service','type':'regular'}})
        with self.Session() as db:self.assertIsNone(db.get(FlowPricing,'fake-delivery').billable)
        record_delivery('12345',{'id':'fake-delivery','status':'delivered','pricing':{'category':'service','type':'regular','billable':True}})
        record_delivery('12345',{'id':'fake-delivery','status':'read'})
        with self.Session() as db:self.assertTrue(db.get(FlowPricing,'fake-delivery').billable)

    def test_concurrent_retries_reserve_only_one_turn_and_interrupted_submission_is_not_retried(self):
        from app.whatsapp.flows.models import FlowTurn
        self.launch()
        data={'question':'Pergunta concorrente','nonce':self.exchange()['data']['nonce']}
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:self.exchange('data_exchange',data),range(2)))
        self.assertEqual(len(self.pool.jobs),1)
        with self.Session() as db:self.assertEqual(db.scalar(select(func.count()).select_from(FlowTurn)),1)
        with patch('app.client.reply',return_value='Resposta de teste.'):self.pool.run()
        data={'question':'Outra pergunta','nonce':self.exchange()['data']['nonce']}
        with patch.object(self.pool,'submit',side_effect=RuntimeError('test only')):
            response=self.exchange('data_exchange',data)
        self.assertIn('interrompida',response['data']['history'])
        self.exchange('data_exchange',data)
        self.assertEqual(len(self.pool.jobs),0)

    def test_disabled_endpoint_and_source_human_pause(self):
        from app.models import Conversation
        from app.whatsapp.flows import routes
        self.launch()
        with self.Session.begin() as db:db.get(Conversation,self.original).status='humano'
        with self.assertRaises(HTTPException):self.exchange()
        with patch.dict(os.environ,{'LUMI_WHATSAPP_FLOWS_FILE':''}),patch.object(routes,'process_pool',self.pool):
            self.assertEqual(TestClient(self.webhook.app).post('/webhooks/whatsapp/flows/12345',json={}).status_code,404)

    def test_health_only_configuration_does_not_intercept_incoming_messages(self):
        from app.whatsapp.flows import runtime
        from app.whatsapp.models import Channel
        with self.Session.begin() as db:
            with patch.object(runtime,'channel_config',return_value=dict(self.config,launch_enabled=False)):
                self.assertFalse(runtime.intercept(db,db.get(Channel,'12345'),None,{'type':'text'}))

    def test_response_waits_without_resubmitting_question_and_has_bounded_fallback(self):
        from app.whatsapp.flows import routes
        pending={'data':{'can_ask':False}}
        ready={'data':{'can_ask':True,'history':'Resposta pronta'}}
        payload={'action':'data_exchange','flow_token':'example-token','data':{'question':'Teste'}}
        with patch.object(routes,'exchange',side_effect=[pending,ready]) as exchange, \
            patch.object(routes,'channel_config',return_value=self.config):
            result=asyncio.run(routes.respond('12345',self.config,payload,self.pool))
        self.assertEqual(result,ready)
        self.assertEqual(exchange.call_count,2)
        self.assertEqual(exchange.call_args_list[1].args[2],{'action':'INIT','flow_token':'example-token'})
        with patch.object(routes,'exchange',return_value=pending) as exchange:
            self.assertEqual(asyncio.run(routes.respond('12345',self.config,payload,self.pool,budget=0)),pending)
            exchange.assert_called_once()

    def test_response_wait_rechecks_channel_configuration(self):
        from app.whatsapp.flows import routes
        with patch.object(routes,'exchange',return_value={'data':{'can_ask':False}}), \
            patch.object(routes,'channel_config',return_value=dict(self.config,tenant_id='other')):
            with self.assertRaises(HTTPException):
                asyncio.run(routes.respond('12345',self.config,{'action':'data_exchange'},self.pool))
