import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select
from app import main,client
from app.db import Base,Session
from app.seed import seed
from app.models import User,Tenant,Message
from app.console_models import ConsoleAccount,ConsoleAudit
from app.usage_models import ModelCall


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        self.previous=Session.kw['bind'];self.folder=tempfile.TemporaryDirectory()
        self.engine=create_engine('sqlite:///'+self.folder.name+'/console.db');Base.metadata.create_all(self.engine);Session.configure(bind=self.engine);seed()
        with Session.begin() as db:
            self.rincao=db.scalar(select(Tenant.id).where(Tenant.slug=='rincao'))
            self.breve=db.scalar(select(Tenant.id).where(Tenant.slug=='breve'))
            operator=db.scalar(select(User).where(User.email=='ana@breve.local'));self.operator_id=operator.id
            db.add(ConsoleAccount(user_id=operator.id,role='brevia'))
            self.rincao_id=db.scalar(select(User.id).where(User.email=='isaque@rincao.local'))
        self.operator=TestClient(main.app);self.customer=TestClient(main.app)
        self.operator.post('/api/login',json={'email':'ana@breve.local','password':'demo1234'}).raise_for_status()
        self.customer.post('/api/login',json={'email':'isaque@rincao.local','password':'demo1234'}).raise_for_status()

    def tearDown(self):
        self.operator.close();self.customer.close();Session.configure(bind=self.previous);self.engine.dispose();self.folder.cleanup()

    def create_access(self,role='admin'):
        response=self.operator.post('/api/console/users',json={'name':'Pessoa teste','email':'pessoa@example.test','tenant_id':self.rincao,'role':role})
        self.assertEqual(response.status_code,200);self.assertEqual(response.headers['cache-control'],'no-store')
        return response.json()

    def test_console_and_tenant_scope_are_server_enforced_and_tab_local(self):
        for path in ['/api/console/overview','/api/console/users','/api/console/issues','/api/console/audit']:
            self.assertEqual(self.customer.get(path).status_code,403)
        self.assertEqual(self.customer.get('/api/admin/settings',params={'tenant':self.breve}).status_code,403)
        self.assertEqual(self.operator.get('/api/admin/settings').status_code,403)
        first=self.operator.get('/api/admin/settings',params={'tenant':self.rincao}).json()
        other=self.operator.get('/api/admin/settings',params={'tenant':self.breve}).json()
        self.assertNotEqual(first['identity'],other['identity'])
        self.assertEqual(first,self.operator.get('/api/admin/settings',params={'tenant':self.rincao}).json())
        self.assertEqual(self.customer.get('/api/admin/settings').json(),first)
        self.assertEqual(self.operator.get('/api/admin/settings',params={'tenant':'missing'}).status_code,404)
        with Session() as db:self.assertEqual(db.get(User,self.operator_id).tenant_id,self.breve)

    def test_assistant_display_name_is_scoped_to_the_selected_tenant(self):
        with Session.begin() as db:
            db.get(Tenant, self.breve).identity = "Nome da assistente: Ana\nIdentidade de teste."
        self.assertEqual(self.operator.get('/api/me', params={'tenant':self.breve}).json()['assistant_name'], 'Ana')
        self.assertEqual(self.operator.get('/api/me', params={'tenant':self.rincao}).json()['assistant_name'], 'Lumi')
        self.assertEqual(self.customer.get('/api/me').json()['assistant_name'], 'Lumi')
        self.assertIn('<h1 id="assistantName">Ana</h1>', self.operator.get('/chat/breve').text)
        self.assertIn('<h1 id="assistantName">Lumi</h1>', self.customer.get('/chat/rincao').text)

    def test_temporary_password_requires_change_and_is_not_retrievable(self):
        access=self.create_access();temporary=access['temporary_password']
        self.assertNotIn(temporary,self.operator.get('/api/console/users').text)
        with Session() as db:
            self.assertNotEqual(db.get(User,access['id']).password_hash,temporary)
            self.assertTrue(db.get(ConsoleAccount,access['id']).must_change_password)
        http=TestClient(main.app)
        try:
            http.post('/api/login',json={'email':access['email'],'password':temporary}).raise_for_status()
            self.assertTrue(http.get('/api/me').json()['must_change_password'])
            self.assertEqual(http.get('/api/admin/settings').status_code,403)
            self.assertEqual(http.post('/api/password',json={'current_password':'wrong','password':'new-password-123'}).status_code,400)
            http.post('/api/password',json={'current_password':temporary,'password':'new-password-123'}).raise_for_status()
            self.assertEqual(http.get('/api/admin/settings').status_code,200)
            self.assertEqual(http.post('/api/login',json={'email':access['email'],'password':temporary}).status_code,401)
        finally:http.close()

    def test_read_only_blocks_every_admin_write_and_cannot_escalate(self):
        with Session.begin() as db:db.add(ConsoleAccount(user_id=self.rincao_id,role='leitura'))
        self.assertEqual(self.customer.get('/api/admin/settings').status_code,200)
        self.assertEqual(self.customer.post('/api/admin/knowledge',json={'title':'Teste','content':'Conteúdo'}).status_code,403)
        self.assertEqual(self.customer.post('/api/console/users',json={'name':'x','email':'x@example.test','tenant_id':self.breve,'role':'brevia'}).status_code,403)
        self.assertEqual(self.operator.post('/api/console/users',json={'name':'x','email':'x@example.test','tenant_id':self.breve,'role':'brevia'}).status_code,422)

    def test_disable_reset_and_role_change_revoke_sessions(self):
        self.operator.put('/api/console/users/'+self.rincao_id,json={'role':'admin','enabled':False}).raise_for_status()
        self.assertEqual(self.customer.get('/api/me').status_code,401)
        self.assertEqual(self.customer.post('/api/login',json={'email':'isaque@rincao.local','password':'demo1234'}).status_code,401)
        self.operator.put('/api/console/users/'+self.rincao_id,json={'role':'admin','enabled':True}).raise_for_status()
        self.customer.post('/api/login',json={'email':'isaque@rincao.local','password':'demo1234'}).raise_for_status()
        response=self.operator.post('/api/console/users/'+self.rincao_id+'/password');response.raise_for_status()
        self.assertEqual(self.customer.get('/api/me').status_code,401)
        self.assertEqual(self.operator.put('/api/console/users/'+self.operator_id,json={'role':'leitura','enabled':False}).status_code,403)

    def test_audit_has_actor_scope_and_actions_without_content_or_password(self):
        self.operator.get('/api/me',params={'tenant':self.rincao}).raise_for_status()
        self.operator.post('/api/admin/knowledge',params={'tenant':self.rincao},json={'title':'QA','content':'private-business-data'}).raise_for_status()
        access=self.create_access()
        rows=self.operator.get('/api/console/audit').json();self.assertTrue(any(row['action']=='tenant.view' and row['tenant_id']==self.rincao for row in rows))
        serialized=str(rows);self.assertNotIn('private-business-data',serialized);self.assertNotIn(access['temporary_password'],serialized)
        self.assertTrue(all(row['actor']=='Ana' for row in rows))

    def test_problems_are_persisted_and_automatic_detection_deduplicates(self):
        issue=self.customer.post('/api/admin/problems',json={'title':'Preciso de ajuda','description':'Um problema de teste','priority':'alta'}).json()
        self.assertEqual(issue['tenant_id'],self.rincao)
        self.operator.put('/api/console/issues/'+issue['id'],json={'status':'analise','note':'Investigação iniciada'}).raise_for_status()
        token=self.customer.post('/api/public/rincao/start',json={'name':'QA'}).json()['token']
        with patch.object(client,'reply',return_value={'reply':'QA','action':'none'}):self.customer.post('/api/client/'+token+'/messages',json={'content':'Oi'})
        with Session.begin() as db:
            message=db.scalar(select(Message).where(Message.sender=='cliente'));db.add(ModelCall(tenant_id=message.tenant_id,conversation_id=message.conversation_id,message_id=message.id,provider='codex',model='gpt-6.1-terra',status='failed',duration_ms=10))
        first=self.operator.get('/api/console/issues').json();second=self.operator.get('/api/console/issues').json();self.assertEqual(len(first),len(second));self.assertEqual(len(first),2)
        reported=next(row for row in first if row['id']==issue['id']);self.assertEqual(reported['status'],'analise');self.assertEqual(reported['notes'][0]['content'],'Investigação iniciada')
        detected=next(row for row in first if row['source']=='sistema');self.operator.put('/api/console/issues/'+detected['id'],json={'status':'resolvido'}).raise_for_status()
        self.assertEqual(next(row for row in self.operator.get('/api/console/issues').json() if row['id']==detected['id'])['status'],'resolvido')

    def test_real_metrics_do_not_invent_channel_cost_and_isolate_totals(self):
        token=self.customer.post('/api/public/rincao/start',json={'name':'QA'}).json()['token']
        with patch.object(client,'reply',return_value={'reply':'QA','action':'none'}):self.customer.post('/api/client/'+token+'/messages',json={'content':'Oi'})
        with Session.begin() as db:
            message=db.scalar(select(Message).where(Message.sender=='cliente'));db.add(ModelCall(tenant_id=message.tenant_id,conversation_id=message.conversation_id,message_id=message.id,provider='openai',model='gpt-6.1-terra',status='completed',duration_ms=10,estimated_usd=.02,input_tokens=123,output_tokens=10))
        data=self.operator.get('/api/console/overview').json();self.assertIsNone(data['channel_cost_usd']);self.assertAlmostEqual(data['current']['estimated_usd'],.02)
        self.assertEqual(next(row for row in data['tenants'] if row['id']==self.breve)['calls'],0)
        self.assertEqual(next(row for row in data['tenants'] if row['id']==self.rincao)['messages'],1)
        self.assertAlmostEqual(sum(sum(row['estimated_usd'] for row in day['tenants'].values()) for day in data['daily']),.02)

    def test_seed_does_not_restore_an_old_login_and_session_cookie_is_optional(self):
        with Session.begin() as db:db.get(User,self.rincao_id).email='new@example.test'
        seed()
        with Session() as db:self.assertIsNone(db.scalar(select(User).where(User.email=='isaque@rincao.local')))
        response=self.customer.post('/api/login',json={'email':'new@example.test','password':'demo1234','remember':False})
        self.assertEqual(response.status_code,200);self.assertNotIn('Max-Age',response.headers['set-cookie'])

    def test_remove_access_preserves_history_and_can_be_restored(self):
        self.operator.delete('/api/console/users/'+self.rincao_id).raise_for_status()
        self.assertNotIn(self.rincao_id,[row['id'] for row in self.operator.get('/api/console/users').json()])
        removed=self.operator.get('/api/console/users',params={'include_removed':'true'}).json()
        self.assertTrue(next(row for row in removed if row['id']==self.rincao_id)['removed'])
        self.assertEqual(self.customer.get('/api/me').status_code,401)
        with Session() as db:self.assertIsNotNone(db.get(User,self.rincao_id))
        self.operator.put('/api/console/users/'+self.rincao_id,json={'role':'admin','enabled':True}).raise_for_status()
        self.customer.post('/api/login',json={'email':'isaque@rincao.local','password':'demo1234'}).raise_for_status()
        self.assertEqual(self.customer.get('/api/me').status_code,200)

    def test_local_provisioning_is_explicit_and_does_not_move_users(self):
        from app.console_setup import provision
        provision('local@example.test','Operador','breve','brevia','local-password-123')
        http=TestClient(main.app)
        try:
            http.post('/api/login',json={'email':'local@example.test','password':'local-password-123'}).raise_for_status()
            self.assertEqual(http.get('/api/me').json()['role'],'brevia')
        finally:http.close()
        with self.assertRaises(ValueError):
            provision('local@example.test','Operador','rincao','admin','local-password-123')

    def test_duplicate_detection_does_not_abort_other_issue_writes(self):
        from app.console_issues import detected
        from app.console_models import ConsoleIssue
        with Session.begin() as db:
            for _ in range(2):detected(db,tenant_id=self.rincao,title='Falha QA',description='QA',source_key='qa:duplicate')
            self.assertEqual(len(list(db.scalars(select(ConsoleIssue)))),1)

    def test_one_admin_entry_selects_the_screen_without_client_redirects(self):
        http=TestClient(main.app)
        try:self.assertIn('id="em"',http.get('/admin').text)
        finally:http.close()
        self.assertIn('/static/console.js?v=',self.operator.get('/admin').text)
        self.assertIn('/static/admin.js?v=',self.customer.get('/admin').text)
        panel=self.operator.get('/admin',params={'tenant':self.rincao}).text
        self.assertEqual(panel.count('id="operatorBar"'),1)
        self.assertIn('Voltar ao console',panel)
        self.assertNotIn('/static/operator-workspace.js',panel)
        response=self.operator.get('/console',follow_redirects=False)
        self.assertEqual(response.status_code,307);self.assertEqual(response.headers['location'],'/admin')

    def test_archived_tenants_are_hidden_and_paused_lumi_never_runs_model(self):
        from app.tenant_runtime import TenantRuntime
        token=self.operator.post('/api/public/breve/start',json={'name':'QA'}).json()['token']
        with Session.begin() as db:
            db.add(TenantRuntime(tenant_id=self.breve,lumi_enabled=False))
            extra=Tenant(name='Arquivada',slug='archive-qa',identity='QA',personality='QA');db.add(extra);db.flush()
            db.add(TenantRuntime(tenant_id=extra.id,listed=False,lumi_enabled=False))
        self.assertEqual(self.operator.post('/api/public/breve/start',json={'name':'QA'}).status_code,409)
        with patch.object(client,'reply') as model:
            self.operator.post('/api/client/'+token+'/messages',json={'content':'Oi'}).raise_for_status()
            model.assert_not_called()
        self.assertEqual(self.operator.get('/api/client/'+token).json()['status'],'desativada')
        tenants=self.operator.get('/api/console/overview').json()['tenants']
        self.assertEqual(len(tenants),2)
        self.assertFalse(next(row for row in tenants if row['id']==self.breve)['lumi_enabled'])

    def test_local_codex_cost_is_zero_without_losing_tokens(self):
        token=self.customer.post('/api/public/rincao/start',json={'name':'QA'}).json()['token']
        with patch.object(client,'reply',return_value={'reply':'QA','action':'none'}):self.customer.post('/api/client/'+token+'/messages',json={'content':'Oi'})
        with Session.begin() as db:
            message=db.scalar(select(Message).where(Message.sender=='cliente'))
            db.add(ModelCall(tenant_id=message.tenant_id,conversation_id=message.conversation_id,message_id=message.id,provider='codex',model='gpt-6.1-terra',status='completed',duration_ms=10,estimated_usd=.5,input_tokens=123,output_tokens=10))
        overview=self.operator.get('/api/console/overview').json()
        self.assertEqual(overview['current']['estimated_usd'],0)
        self.assertEqual(overview['current']['input_tokens'],123)
        self.assertEqual(self.customer.get('/api/admin/usage').status_code,403)
        usage=self.operator.get('/api/admin/usage',params={'tenant':self.rincao}).json();self.assertEqual(usage['estimated_api_usd'],0)
