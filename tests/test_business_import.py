import unittest
from datetime import date
from app.business_import import import_records
from app.business_models import Contract, ImportedRecord, WorkLog
from app.models import User
from app.db import Session
from sqlalchemy import select
from tests import test_business as scenario


class BusinessImportTest(unittest.TestCase):
    setUp = scenario.BusinessTest.setUp
    tearDown = scenario.BusinessTest.tearDown
    def test_import_idempotence_and_manual_edit_conflict(self):
        from app.business_models import Project
        entries=[{'kind':'project','source_url':'https://app.notion.com/p/example-project','data':{'name':'Importado','summary':'Fonte revisada'}}]
        with Session.begin() as db:
            actor=db.scalar(select(User.id).where(User.email=='ana@breve.local'))
            first=import_records(db,self.rincao,actor,entries);self.assertEqual(first['created'],1)
            second=import_records(db,self.rincao,actor,entries);self.assertEqual(second['unchanged'],1)
            ref=db.get(ImportedRecord,(self.rincao,entries[0]['source_url'],'project'))
            db.get(Project,ref.record_id).summary='Editado pelo usuário';db.flush()
            entries[0]['data']['summary']='Nova origem'
            third=import_records(db,self.rincao,actor,entries);self.assertEqual(len(third['conflicts']),1)
            self.assertEqual(db.get(Project,ref.record_id).summary,'Editado pelo usuário')

    def test_opening_balance_is_not_duplicated_by_detailed_work(self):
        project='https://app.notion.com/p/project'
        contract='https://app.notion.com/p/contract'
        entries=[{'kind':'project','source_url':project,'data':{'name':'Projeto'}},
            {'kind':'contract','source_url':contract,'project_source':project,'data':{
                'title':'Outubro','kind':'Manutenção mensal','included_minutes':2400,
                'opening_used_minutes':2280,'opening_as_of':'2026-10-06','opening_note':'Fechamento confirmado na origem'}},
            {'kind':'work','source_url':'https://app.notion.com/p/work','contract_source':contract,'data':{
                'work_date':'2026-10-09','minutes':120,'description':'Atividade detalhada'}}]
        with Session.begin() as db:
            actor=db.scalar(select(User.id).where(User.email=='ana@breve.local'))
            self.assertEqual(import_records(db,self.rincao,actor,entries)['created'],3)
        data=self.operator.get(self.prefix).json();self.assertEqual(data['contracts'][0]['used_minutes'],2400)
        self.assertEqual(data['contracts'][0]['remaining_minutes'],0)
        from services.brevia.reports import opening_in_period
        from services.brevia.api import Arguments
        with Session() as db:
            c=db.get(Contract,data['contracts'][0]['id'])
            c.start_date=date(2026,10,1)
            self.assertEqual(opening_in_period(c,Arguments(start_date='2026-10-01',end_date='2026-10-31')),(2280,True))
            self.assertEqual(opening_in_period(c,Arguments(start_date='2026-10-07',end_date='2026-10-31')),(0,True))
            self.assertEqual(opening_in_period(c,Arguments(start_date='2026-10-03',end_date='2026-10-04')),(0,False))
        self.assertEqual(self.operator.post(self.prefix+'/work-logs',json={'contract_id':data['contracts'][0]['id'],
            'work_date':'2026-10-05','minutes':60,'description':'Duplicação'}).status_code,409)

    def test_import_cannot_link_a_foreign_tenant_reference(self):
        from app.models import User
        with Session.begin() as db:
            actor=db.scalar(select(User.id).where(User.email=='ana@breve.local'))
            project='https://app.notion.com/p/foreign'
            import_records(db,self.brevia,actor,[{'kind':'project','source_url':project,'data':{'name':'Outro'}}])
            with self.assertRaises(ValueError):
                import_records(db,self.rincao,actor,[{'kind':'contract','source_url':'https://app.notion.com/p/new',
                    'project_source':project,'data':{'title':'Falha','kind':'Manutenção'}}])
