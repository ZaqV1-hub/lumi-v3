import unittest
import test_onboarding as existing


class ObjectiveOptionsTest(unittest.TestCase):
    setUp=existing.OnboardingTest.setUp
    tearDown=existing.OnboardingTest.tearDown
    objective=existing.OnboardingTest.objective
    send=existing.OnboardingTest.send
    state=existing.OnboardingTest.state

    def configure(self, oid, title, choices, allow_other=False):
        return self.admin.put('/api/admin/onboarding/'+oid,json={'title':title,'description':'Identificar somente esta informação',
            'required':True,'updates_name':False,'choices':choices,'allow_other':allow_other})

    def test_region_does_not_fill_product_and_alias_is_standardized(self):
        region=self.objective('Região desejada',False)
        self.configure(region,'Região desejada',[{'value':'Zona Sul','aliases':['Sul','região sul']}],True).raise_for_status()
        self.configure(self.reason,'Produto escolhido',[{'value':'Projeto Exemplo','aliases':['Exemplo']}]).raise_for_status()
        self.send('Sul, quero conhecer a empresa',[
            {'objective_id':region,'value':'Sul','evidence':'Sul'},
            {'objective_id':self.reason,'value':'Sul','evidence':'Sul'}])
        fields={f['id']:f for f in self.state()['fields']}
        self.assertEqual(fields[region]['value'],'Zona Sul');self.assertEqual(fields[self.reason]['value'],'')
        self.send('Quero o Exemplo',[{'objective_id':self.reason,'value':'Projeto Exemplo','evidence':'Quero o Exemplo'}])
        self.assertEqual(next(f['value'] for f in self.state()['fields'] if f['id']==self.reason),'Projeto Exemplo')

    def test_canonical_name_without_evidence_cannot_be_invented(self):
        self.configure(self.reason,'Produto escolhido',[{'value':'Projeto Exemplo','aliases':['Exemplo']}]).raise_for_status()
        self.send('Gosto da zona sul',[{'objective_id':self.reason,'value':'Projeto Exemplo','evidence':'zona sul'}])
        self.assertEqual(next(f['value'] for f in self.state()['fields'] if f['id']==self.reason),'')

    def test_options_are_tenant_scoped_and_retained_on_legacy_edit(self):
        self.configure(self.reason,'Motivo',[{'value':'Visita','aliases':['visitar']}]).raise_for_status()
        body={'title':'Motivo atualizado','description':'Descrição atualizada','required':True,'updates_name':False}
        self.assertEqual(self.other.put('/api/admin/onboarding/'+self.reason,json=body).status_code,404)
        self.admin.put('/api/admin/onboarding/'+self.reason,json=body).raise_for_status()
        row=next(f for f in self.admin.get('/api/admin/onboarding').json() if f['id']==self.reason)
        self.assertEqual(row['choices'][0]['value'],'Visita')

    def test_unknown_neighborhood_can_remain_free_when_configured(self):
        self.configure(self.reason,'Região',[{'value':'Zona Sul','aliases':['Sul']}],True).raise_for_status()
        self.send('Prefiro Bairro Exemplo',[{'objective_id':self.reason,'value':'Bairro Exemplo','evidence':'Prefiro Bairro Exemplo'}])
        self.assertEqual(next(f['value'] for f in self.state()['fields'] if f['id']==self.reason),'Bairro Exemplo')
