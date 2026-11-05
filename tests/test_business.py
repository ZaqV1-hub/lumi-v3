import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from app import main, client
from app.db import Base, Session
from app.seed import seed
from app.models import Contact, Tenant, User, VisitorSession
from app.console_models import ConsoleAccount
from app.business_setup import provision
from services.brevia.api import app as reports_app


class BusinessTest(unittest.TestCase):
    def setUp(self):
        self.previous=Session.kw['bind'];self.temp=tempfile.TemporaryDirectory()
        self.engine=create_engine('sqlite:///'+self.temp.name+'/business.db')
        Base.metadata.create_all(self.engine);Session.configure(bind=self.engine);seed()
        with Session.begin() as db:
            self.rincao=db.scalar(select(Tenant).where(Tenant.slug=='rincao')).id
            team=db.scalar(select(Tenant).where(Tenant.slug=='breve'));self.brevia=team.id
            actor=db.scalar(select(User).where(User.email=='ana@breve.local'));db.add(ConsoleAccount(user_id=actor.id,role='brevia'))
            provision(db,team,'administrador','all','http://127.0.0.1:8005','TEST_REPORT')
            provision(db,db.get(Tenant,self.rincao),'gestor','own','http://127.0.0.1:8005','TEST_REPORT')
        self.operator=TestClient(main.app);self.customer=TestClient(main.app);self.service=TestClient(reports_app)
        self.operator.post('/api/login',json={'email':'ana@breve.local','password':'demo1234'}).raise_for_status()
        self.customer.post('/api/login',json={'email':'isaque@rincao.local','password':'demo1234'}).raise_for_status()
        self.prefix='/api/console/business/clients/'+self.rincao
        self.env=patch.dict(os.environ,{'TEST_REPORT':'private-test-key','BREVIA_TOOLS_BINDINGS':json.dumps({self.rincao:'TEST_REPORT',self.brevia:'TEST_REPORT'})});self.env.start()

    def tearDown(self):
        self.env.stop();self.operator.close();self.customer.close();self.service.close()
        Session.configure(bind=self.previous);self.engine.dispose();self.temp.cleanup()

    def project(self,tid=None):
        r=self.operator.post('/api/console/business/clients/'+(tid or self.rincao)+'/projects',json={'name':'Projeto teste','summary':'Status confirmado'})
        r.raise_for_status();return r.json()['id']

    def contract(self,pid,tid=None):
        r=self.operator.post('/api/console/business/clients/'+(tid or self.rincao)+'/contracts',json={
            'project_id':pid,'title':'Contrato teste','kind':'Manutenção','included_minutes':2400,'amount_cents':720000})
        r.raise_for_status();return r.json()['id']

    def visitor_call(self,role='gestor',admin=False):
        if admin:
            started=self.operator.post('/api/console/business/chat').json();tid=self.brevia
        else:
            started=self.customer.post('/api/public/rincao/start',json={'name':'Visitante'}).json();tid=self.rincao
        with Session.begin() as db:
            session=db.get(VisitorSession,started['token'])
            from app.models import Conversation
            chat=db.get(Conversation,session.conversation_id);contact=db.get(Contact,chat.contact_id);contact.role=role
            return {'tenant_id':tid,'conversation_id':chat.id,'role':role,'context':{'contact_id':contact.id},
                'arguments':{'client':None,'start_date':None,'end_date':None}},started['token']

    def report(self,body,key='private-test-key'):
        return self.service.post('/reports/projects',headers={'Authorization':'Bearer '+key},json=body)

    def test_crud_totals_dates_and_tenant_boundaries(self):
        p=self.project();c=self.contract(p)
        for day,minutes in [('2026-10-01',120),('2026-10-31',60)]:
            self.operator.post(self.prefix+'/work-logs',json={'contract_id':c,'work_date':day,'minutes':minutes,'description':'Atividade confirmada'}).raise_for_status()
        self.operator.post(self.prefix+'/projects/'+p+'/updates',json={'content':'Entrega concluída'}).raise_for_status()
        result=self.operator.get(self.prefix).json()
        self.assertEqual(result['contracts'][0]['used_minutes'],180);self.assertEqual(result['contracts'][0]['remaining_minutes'],2220)
        self.assertEqual(len(result['updates']),1);self.assertEqual(result['updates'][0]['actor'],'Ana')
        self.assertEqual(self.customer.get(self.prefix).status_code,403)
        foreign=self.project(self.brevia)
        self.assertEqual(self.operator.post(self.prefix+'/contracts',json={'project_id':foreign,'title':'x','kind':'x'}).status_code,404)
        self.assertEqual(self.operator.post(self.prefix+'/work-logs',json={'contract_id':c,'work_date':'2026-10-01','minutes':-1,'description':'x'}).status_code,422)

    def test_manager_report_uses_own_scope_and_omits_internal_notes(self):
        self.contract(self.project());self.contract(self.project(self.brevia),self.brevia)
        self.operator.put(self.prefix,json={'notes':'INTERNAL-NOT-FOR-MODEL'}).raise_for_status()
        body,_=self.visitor_call();result=self.report(body);result.raise_for_status()
        self.assertEqual([r['client']['id'] for r in result.json()['reports']],[self.rincao])
        self.assertNotIn('INTERNAL-NOT-FOR-MODEL',result.text)
        for name in ('Clube Rincão', 'clube rincao', 'RINCÃO'):
            body['arguments']['client'] = name
            own = self.report(body)
            own.raise_for_status()
            self.assertEqual([r['client']['id'] for r in own.json()['reports']], [self.rincao])
        body['arguments']['client']='Breve';self.assertEqual(self.report(body).status_code,404)
        body['arguments']['client']=None;body['role']='administrador';self.assertEqual(self.report(body).status_code,403)
        self.assertEqual(self.report(body,'wrong-key').status_code,403)

    def test_brevia_admin_queries_multiple_clients_but_cliente_is_denied(self):
        body,_=self.visitor_call('administrador',True)
        response=self.report(body);response.raise_for_status()
        self.assertGreaterEqual(len(response.json()['reports']),2)
        body,_=self.visitor_call('cliente');self.assertEqual(self.report(body).status_code,403)

    def test_period_totals_and_full_contract_balance(self):
        c=self.contract(self.project())
        for day in ['2026-09-30','2026-10-01']:
            self.operator.post(self.prefix+'/work-logs',json={'contract_id':c,'work_date':day,'minutes':120,'description':'Trabalho'}).raise_for_status()
        body,_=self.visitor_call();body['arguments'].update(start_date='2026-10-01',end_date='2026-10-31')
        result=self.report(body).json()['reports'][0]
        self.assertEqual(result['hours']['period_used_minutes'],120)
        self.assertEqual(result['contracts'][0]['used_minutes'],240)
        body['arguments']['end_date']='2026-09-30';self.assertEqual(self.report(body).status_code,422)

    def test_role_instructions_are_scoped_and_cannot_grant_tools(self):
        url='/api/admin/role-instructions/gestor'
        self.customer.put(url,json={'instructions':'GESTOR-INSTRUCTIONS-ONLY'}).raise_for_status()
        self.assertEqual(self.customer.put('/api/admin/role-instructions/administrador',json={'instructions':'x'}).status_code,404)
        self.assertEqual(self.customer.put(url+'?tenant='+self.brevia,json={'instructions':'x'}).status_code,403)
        body,token=self.visitor_call('cliente')
        with patch.object(client,'reply',return_value={'reply':'Oi','action':'none'}) as model:
            self.customer.post('/api/client/'+token+'/messages',json={'content':'Oi'}).raise_for_status()
            self.assertNotIn('GESTOR-INSTRUCTIONS-ONLY',model.call_args.args[0])
            self.assertNotIn('consultar_projetos_contratos',[t['name'] for t in model.call_args.kwargs.get('tools',[])])
        self.operator.put('/api/admin/conversations/'+body['conversation_id']+'/role?tenant='+self.rincao,json={'role':'gestor'}).raise_for_status()
        with patch.object(client,'reply',return_value={'reply':'Oi','action':'none'}) as model:
            self.customer.post('/api/client/'+token+'/messages',json={'content':'Oi'}).raise_for_status()
            self.assertIn('GESTOR-INSTRUCTIONS-ONLY',model.call_args.args[0])
            self.assertIn('consultar_projetos_contratos',[t['name'] for t in model.call_args.kwargs['tools']])

    def test_management_chat_requires_owner_session_and_cannot_be_created_publicly(self):
        self.assertEqual(self.customer.post('/api/console/business/chat').status_code,403)
        _,token=self.visitor_call('administrador',True)
        self.assertEqual(self.operator.get('/api/client/'+token).status_code,200)
        self.assertEqual(self.customer.get('/api/client/'+token).status_code,403)
        anon=TestClient(main.app)
        try:
            self.assertEqual(anon.get('/api/client/'+token).status_code,401)
        finally:
            anon.close()
        self.operator.post('/api/logout');self.assertEqual(self.operator.get('/api/client/'+token).status_code,401)

    def test_internal_chat_does_not_enable_public_brevia_assistant(self):
        with Session.begin() as db:
            provision(db,db.get(Tenant,self.brevia),'administrador','all','http://127.0.0.1:8005','TEST_REPORT',enable_lumi=True)
        self.assertEqual(self.customer.post('/api/public/breve/start',json={'name':'Não autorizado'}).status_code,409)
        self.operator.post('/api/console/business/chat').raise_for_status()
        self.customer.post('/api/public/rincao/start',json={'name':'Cliente autorizado'}).raise_for_status()

    def test_private_role_simulation_is_owned_and_cannot_grant_global_access(self):
        roles=self.customer.get('/api/admin/simulations/roles').json()
        self.assertIn('gestor',[r['role'] for r in roles])
        self.assertNotIn('administrador',[r['role'] for r in roles])
        self.assertEqual(self.customer.post('/api/admin/simulations',json={'role':'administrador'}).status_code,403)
        response=self.customer.post('/api/admin/simulations',json={'role':'gestor'})
        response.raise_for_status();token=response.json()['token']
        self.customer.get('/api/client/'+token).raise_for_status()
        self.assertEqual(self.operator.get('/api/client/'+token).status_code,403)
        with TestClient(main.app) as anonymous:
            self.assertEqual(anonymous.get('/api/client/'+token).status_code,401)
            self.assertEqual(anonymous.post('/api/admin/simulations',json={'role':'gestor'}).status_code,401)

    def test_report_is_called_through_external_tool_and_logged(self):
        from app import tools
        _,token=self.visitor_call()
        answers=[{'reply':'','action':'call_tool','tool_call':{'name':'consultar_projetos_contratos','arguments':{'client':None,'start_date':None,'end_date':None}}},{'reply':'Relatório disponível','action':'none'}]
        def external(request,**kwargs):
            response=self.report(json.loads(request.data));response.raise_for_status()
            return io.BytesIO(response.content)
        with patch.object(client,'reply',side_effect=answers),patch.object(tools.urllib.request,'urlopen',side_effect=external):
            self.customer.post('/api/client/'+token+'/messages',json={'content':'Como está meu projeto?'}).raise_for_status()
        from app.models import FeatureCall
        with Session() as db:
            call=db.scalar(select(FeatureCall).where(FeatureCall.feature=='consultar_projetos_contratos'))
            self.assertTrue(json.loads(call.result)['data']['ok']);self.assertGreaterEqual(int(call.duration_ms),0)
