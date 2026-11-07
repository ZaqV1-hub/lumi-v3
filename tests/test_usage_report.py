import tempfile
import os
import unittest
from unittest.mock import patch
from datetime import datetime,timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select
from app import main
from app.db import Base,Session
from app.seed import seed
from app.models import User,Tenant,Contact,Conversation,Message
from app.console_models import ConsoleAccount
from app.usage_models import ModelCall,ResponseRun
from app.usage import record,usage_scope


class UsageReportTest(unittest.TestCase):
    def setUp(self):
        self.previous=Session.kw['bind'];self.folder=tempfile.TemporaryDirectory();self.engine=create_engine('sqlite:///'+self.folder.name+'/usage.db')
        Base.metadata.create_all(self.engine);Session.configure(bind=self.engine);seed()
        with Session.begin() as db:
            self.tid=db.scalar(select(Tenant.id).where(Tenant.slug=='rincao'));self.other=db.scalar(select(Tenant.id).where(Tenant.slug=='breve'))
            operator=db.scalar(select(User).where(User.email=='ana@breve.local'));db.add(ConsoleAccount(user_id=operator.id,role='brevia'))
        self.http=TestClient(main.app);self.customer=TestClient(main.app)
        for http,email in [(self.http,'ana@breve.local'),(self.customer,'isaque@rincao.local')]:http.post('/api/login',json={'email':email,'password':'demo1234'}).raise_for_status()
        self.params={'tenant':self.tid,'start_date':'2026-10-10','end_date':'2026-10-10'}

    def tearDown(self):
        self.http.close();self.customer.close();Session.configure(bind=self.previous);self.engine.dispose();self.folder.cleanup()

    def message(self,tid=None,hour=4,duration=3000):
        created=datetime(2026,10,10,hour,0,tzinfo=timezone.utc)
        with Session.begin() as db:
            contact=Contact(tenant_id=tid or self.tid,name='QA',role='cliente');db.add(contact);db.flush()
            chat=Conversation(tenant_id=contact.tenant_id,contact_id=contact.id);db.add(chat);db.flush()
            message=Message(tenant_id=chat.tenant_id,conversation_id=chat.id,sender='cliente',content='QA',created_at=created);db.add(message);db.flush()
            db.add(ResponseRun(message_id=message.id,tenant_id=chat.tenant_id,conversation_id=chat.id,status='completed',duration_ms=duration))
            return {'tenant_id':chat.tenant_id,'conversation_id':chat.id,'message_id':message.id,'created_at':created}

    def call(self,message,model='gpt-6.1-terra',provider='codex',incoming=100,cached=20,outgoing=10,cost=.5,duration=1000):
        with Session.begin() as db:db.add(ModelCall(**message,provider=provider,model=model,status='completed',duration_ms=duration,input_tokens=incoming,cached_tokens=cached,output_tokens=outgoing,estimated_usd=cost))

    def test_brevia_only_and_conversation_scope_cannot_be_bypassed(self):
        self.assertEqual(self.customer.get('/api/admin/usage').status_code,403)
        self.assertEqual(self.customer.get('/api/admin/usage',params={'tenant':self.tid}).status_code,403)
        self.assertEqual(self.customer.get('/api/admin/usage',params={'tenant':self.other}).status_code,403)
        self.assertEqual(self.http.get('/api/admin/usage').status_code,403)
        other=self.message(self.other);self.call(other)
        self.assertEqual(self.http.get('/api/admin/usage',params={**self.params,'conversation_id':other['conversation_id']}).status_code,404)

    def test_filters_charts_and_response_times_use_the_same_cohort(self):
        first=self.message();self.call(first);self.call(first,incoming=200,cached=40,outgoing=20,duration=2000)
        self.call(first,model='base',provider='faster-whisper-local',incoming=None,cached=None,outgoing=None,duration=500)
        second=self.message(hour=5,duration=9000);self.call(second,model='gpt-6.1-sol',provider='openai',incoming=200,cached=0,outgoing=40,cost=.02)
        self.call(self.message(hour=2),incoming=17,outgoing=3)
        self.call(self.message(self.other),model='gpt-6-luna',incoming=9999)
        response=self.http.get('/api/admin/usage',params=self.params)
        self.assertEqual(response.headers['cache-control'],'no-store')
        data=response.json()
        self.assertEqual(data['calls'],4);self.assertEqual(data['messages'],2)
        self.assertEqual(data['input_tokens'],500);self.assertEqual(data['cached_tokens'],60);self.assertEqual(data['output_tokens'],70)
        self.assertAlmostEqual(data['estimated_api_usd'],.02)
        self.assertEqual(data['average_response_ms'],6000);self.assertEqual(data['p95_response_ms'],9000)
        self.assertEqual(len(data['daily']),1);self.assertEqual(data['daily'][0]['input_tokens'],500)
        self.assertNotIn('gpt-6-luna',data['available_models']);self.assertEqual(len(data['by_model']),3)
        filtered=self.http.get('/api/admin/usage',params={**self.params,'model':'gpt-6.1-terra'}).json()
        self.assertEqual(filtered['calls'],2);self.assertEqual(filtered['input_tokens'],300);self.assertEqual(filtered['messages'],1)
        self.assertEqual(filtered['average_response_ms'],3000);self.assertEqual(filtered['daily'][0]['average_response_ms'],3000)
        self.assertEqual(filtered['estimated_api_usd'],0)
        previous=self.http.get('/api/admin/usage',params={**self.params,'start_date':'2026-10-09','end_date':'2026-10-09'}).json()
        self.assertEqual(previous['input_tokens'],17)

    def test_invalid_period_and_empty_model_are_handled_without_fake_values(self):
        self.assertEqual(self.http.get('/api/admin/usage',params={**self.params,'start_date':'2026-10-11'}).status_code,422)
        self.assertEqual(self.http.get('/api/admin/usage',params={**self.params,'start_date':'2020-01-01'}).status_code,422)
        data=self.http.get('/api/admin/usage',params={**self.params,'model':'not-used'}).json()
        self.assertEqual(data['calls'],0);self.assertIsNone(data['average_response_ms']);self.assertIsNone(data['daily'][0]['average_response_ms'])
        self.assertEqual(data['estimated_api_usd'],0)

    def test_totals_are_not_truncated_to_recent_table_limit(self):
        message=self.message()
        with Session.begin() as db:db.add_all([ModelCall(**message,provider='codex',model='gpt-6.1-terra',status='completed',duration_ms=10,input_tokens=1,cached_tokens=0,output_tokens=1,estimated_usd=.1) for _ in range(1001)])
        data=self.http.get('/api/admin/usage',params=self.params).json()
        self.assertEqual(data['calls'],1001);self.assertEqual(len(data['recent']),50)
        self.assertEqual(data['input_tokens'],1001);self.assertEqual(data['daily'][0]['input_tokens'],1001)
        self.assertEqual(data['estimated_api_usd'],0)

    def test_openai_model_and_unpriced_usage_are_explicit(self):
        message = self.message()
        with usage_scope(message['tenant_id'], message['conversation_id'], message['message_id']):
            record('openai', 'gpt-6.1-terra', 'completed', 10, usage={
                'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10,
                'reasoning_output_tokens': 3})
        with Session.begin() as db:
            row = db.scalar(select(ModelCall).where(ModelCall.message_id == message['message_id']))
            self.assertIsNone(row.estimated_usd)
            self.assertEqual(row.reasoning_tokens, 3)
            row.created_at = message['created_at']
        from app.tenant_ai import TenantAI
        with Session.begin() as db:
            db.add(TenantAI(tenant_id=message['tenant_id'], provider='openai', model='configured-api-model'))
        data = self.http.get('/api/admin/usage', params=self.params).json()
        self.assertEqual(data['configured_provider'], 'openai')
        self.assertEqual(data['configured_model'], 'configured-api-model')
        self.assertEqual(data['messages_without_complete_cost'], 1)
        self.assertIsNone(data['estimated_api_usd'])
        self.assertIsNone(data['by_model'][0]['estimated_api_usd'])
        self.assertIsNone(data['recent'][0]['estimated_usd'])

    def test_verified_openai_cost_reaches_report_without_charging_codex_or_mixing_tenants(self):
        usage = {'input_tokens': 12000, 'cached_input_tokens': 4000, 'output_tokens': 1000,
                 'reasoning_output_tokens': 900, 'cache_write_tokens': 7000,
                 'cache_write_30m_tokens': 3000, 'cache_write_12h_tokens': 4000,
                 'service_tier': 'default'}
        first, incomplete, other = self.message(), self.message(), self.message(self.other)
        for message, provider, model in [(first, 'openai', 'gpt-6-luna'),
                                         (first, 'codex_gateway', 'gpt-6-luna'),
                                         (incomplete, 'openai', 'unknown-model'),
                                         (other, 'openai', 'gpt-6-luna')]:
            with usage_scope(message['tenant_id'], message['conversation_id'], message['message_id']):
                record(provider, model, 'completed', 10, usage=usage)
        with Session.begin() as db:
            rows = list(db.scalars(select(ModelCall)))
            for row in rows:
                row.created_at = first['created_at']
            priced = next(r for r in rows if r.tenant_id == self.tid and r.provider == 'openai' and r.model == 'gpt-6-luna')
            self.assertAlmostEqual(priced.estimated_usd, 0.002015)
            self.assertEqual(priced.reasoning_tokens, 900)
            self.assertIn('2026-11-07', priced.price_reference)
            self.assertIn('https://developers.openai.com/api/docs/pricing', priced.price_reference)
            self.assertIn('service_tier=default', priced.price_reference)
            self.assertIn('cache_write_30m_tokens=3000', priced.price_reference)
            self.assertIn('cache_write_12h_tokens=4000', priced.price_reference)
            self.assertIn('não é fatura', priced.price_reference)
        data = self.http.get('/api/admin/usage', params=self.params).json()
        self.assertEqual(data['calls'], 3)
        self.assertAlmostEqual(data['estimated_api_usd'], 0.002015)
        self.assertEqual(data['messages_without_complete_cost'], 1)
        codex = next(row for row in data['recent'] if row['provider'] == 'codex_gateway')
        self.assertEqual(codex['estimated_usd'], 0)
        unknown = next(row for row in data['recent'] if row['model'] == 'unknown-model')
        self.assertIsNone(unknown['estimated_usd'])
