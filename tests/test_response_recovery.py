import json
import subprocess
import unittest
from unittest.mock import patch
from sqlalchemy import select
import test_incoming as incoming_tests
from test_incoming import picture
from app import client, providers
from app.db import Session
from app.models import Message, Conversation, FeatureCall
from app.media_models import ImageAsset
from app.usage_models import ResponseRun
from app.spam import control


class ResponseRecoveryTest(unittest.TestCase):
    setUp = incoming_tests.IncomingTest.setUp
    tearDown = incoming_tests.IncomingTest.tearDown

    def catalog(self):
        with Session.begin() as db:
            tid=db.get(Conversation,self.cid).tenant_id
            row=ImageAsset(tenant_id=tid,name='Foto de teste',description='Foto do local',when_to_use='Quando solicitada',data=picture())
            db.add(row);db.flush();return row.id

    def send_image(self):
        return self.http.post('/api/client/'+self.token+'/attachments',content=picture(),headers={
            'content-type':'image/png','x-lumi-caption':'Explique esta imagem'})

    def test_interpretation_does_not_send_catalog_image_even_if_action_is_inconsistent(self):
        image=self.catalog()
        with patch.object(client,'reply',return_value={'reply':'Vejo uma rede de pontos. Quer uma foto do local?',
            'action':'send_image','image_id':image,'image_intent':'inspect_received'}):self.send_image().raise_for_status()
        items=self.http.get('/api/client/'+self.token).json()['messages']
        self.assertIsNone(items[-1]['image_id']);self.assertIn('rede de pontos',items[-1]['content'])
        with Session() as db:
            audit=db.scalar(select(FeatureCall).where(FeatureCall.conversation_id==self.cid))
            self.assertFalse(json.loads(audit.result)['accepted'])

    def test_explicit_catalog_request_with_received_image_still_works(self):
        image=self.catalog()
        with patch.object(client,'reply',return_value={'reply':'Segue a foto que você pediu.',
            'action':'send_image','image_id':image,'image_intent':'inspect_and_send_catalog'}):self.send_image().raise_for_status()
        self.assertEqual(self.http.get('/api/client/'+self.token).json()['messages'][-1]['image_id'],image)

    def test_missing_catalog_intent_is_also_rejected_without_an_attachment(self):
        image=self.catalog()
        with patch.object(client,'reply',return_value={'reply':'Posso ajudar?','action':'send_image','image_id':image}):
            self.http.post('/api/client/'+self.token+'/messages',json={'content':'Olá'}).raise_for_status()
        self.assertIsNone(self.http.get('/api/client/'+self.token).json()['messages'][-1]['image_id'])

    def test_catalog_attachment_is_visible_to_model_only_in_its_own_conversation(self):
        image = self.catalog()
        send = {'reply': 'Aqui está a planta.', 'action': 'send_image',
                'image_id': image, 'image_intent': 'send_catalog'}
        with patch.object(client, 'reply', return_value=send):
            self.http.post('/api/client/'+self.token+'/messages',
                           json={'content': 'Mostre a planta'}).raise_for_status()
        other_token = self.http.post('/api/public/rincao/start', json={'name': 'Outro'}).json()['token']
        for token, should_see_history in [(self.token, True), (other_token, False)]:
            with patch.object(client, 'reply', return_value={'reply': 'Entendi.', 'action': 'none'}) as model:
                self.http.post('/api/client/'+token+'/messages',
                               json={'content': 'Gostei dessa planta'}).raise_for_status()
            marker = 'Imagens do catálogo já anexadas pela Lumi no histórico acima: ' + image
            self.assertEqual(marker in model.call_args.args[0], should_see_history)

    def test_unavailable_image_recovers_the_answer_without_sending_or_promising_an_image(self):
        image = self.catalog()
        with Session.begin() as db:
            db.get(ImageAsset, image).enabled = False
        first = {'reply': 'Segue a foto da piscina.', 'action': 'send_image',
                 'image_id': image, 'image_intent': 'send_catalog'}
        repaired = {'reply': 'O local tem piscina e academia.', 'action': 'none'}
        with patch.object(client, 'reply', side_effect=[first, repaired]) as model:
            self.http.post('/api/client/'+self.token+'/messages', json={'content': 'Tem piscina e academia?'}).raise_for_status()
        items = self.http.get('/api/client/'+self.token).json()['messages']
        self.assertEqual([m['sender'] for m in items], ['cliente', 'lumi'])
        self.assertEqual(items[-1]['content'], repaired['reply'])
        self.assertIsNone(items[-1]['image_id'])
        self.assertNotIn('tools', model.call_args.kwargs)
        with Session() as db:
            audit = db.scalar(select(FeatureCall).where(FeatureCall.conversation_id == self.cid))
            self.assertEqual(json.loads(audit.result), {'accepted': False, 'reason': 'unavailable'})

    def test_invalid_image_repair_cannot_execute_a_second_business_operation(self):
        first = {'reply': '', 'action': 'call_tool', 'tool_call': {'name': 'reserve', 'arguments': {}}}
        unavailable = {'reply': 'Reserva confirmada. Segue a imagem.', 'action': 'send_image',
                       'image_id': 'missing', 'image_intent': 'send_catalog'}
        repaired = {'reply': 'Reserva confirmada para amanhã às 14h.', 'action': 'none'}
        with patch.object(client, 'execute_tool', return_value={'reservation_id': 'confirmed'}) as execute, \
                patch.object(client, 'reply', side_effect=[first, unavailable, repaired]) as model:
            self.http.post('/api/client/'+self.token+'/messages', json={'content': 'Confirmo a visita'}).raise_for_status()
            execute.assert_called_once()
        self.assertIn('confirmed', model.call_args.args[0])
        self.assertEqual(self.http.get('/api/client/'+self.token).json()['messages'][-1]['content'], repaired['reply'])

    def test_image_repair_is_bounded_and_rejects_another_action(self):
        first = {'reply': 'Segue a foto.', 'action': 'send_image', 'image_id': None, 'image_intent': 'send_catalog'}
        with patch.object(client, 'reply', return_value=first) as model:
            response = self.http.post('/api/client/'+self.token+'/messages', json={'content': 'Envie a foto'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(model.call_count, 2)
        items = self.http.get('/api/client/'+self.token).json()['messages']
        self.assertEqual([m['sender'] for m in items], ['cliente'])
        self.assertEqual(items[0]['response_status'], 'failed')

    def test_handover_during_image_repair_discards_the_reply(self):
        first = {'reply': 'Segue a foto.', 'action': 'send_image', 'image_id': 'missing', 'image_intent': 'send_catalog'}
        def pause(*args, **kwargs):
            with Session.begin() as db:
                db.get(Conversation, self.cid).status = 'humano'
                control(db, self.cid).revision += 1
            return {'reply': 'Há piscina.', 'action': 'none'}
        with patch.object(client, 'reply', side_effect=lambda *args, **kwargs: first if model.call_count == 1 else pause()) as model:
            self.http.post('/api/client/'+self.token+'/messages', json={'content': 'Tem piscina?'}).raise_for_status()
        items = self.http.get('/api/client/'+self.token).json()['messages']
        self.assertEqual([m['sender'] for m in items], ['cliente'])

    def test_foreign_image_is_rejected_before_text_recovery(self):
        image = self.catalog()
        foreign_token = self.other.post('/api/public/breve/start', json={'name': 'Outro'}).json()['token']
        first = {'reply': 'Segue a foto.', 'action': 'send_image', 'image_id': image, 'image_intent': 'send_catalog'}
        repaired = {'reply': 'Não tenho essa foto disponível.', 'action': 'none'}
        with patch.object(client, 'reply', side_effect=[first, repaired]) as model:
            self.other.post('/api/client/'+foreign_token+'/messages', json={'content': 'Quero uma foto'}).raise_for_status()
        item = self.other.get('/api/client/'+foreign_token).json()['messages'][-1]
        self.assertEqual(item['content'], repaired['reply'])
        self.assertIsNone(item['image_id'])
        self.assertNotIn(image, model.call_args.args[0])

    def test_catalog_disable_before_persistence_never_sends_a_false_caption(self):
        image = self.catalog()
        def disable(db, *args, **kwargs):
            db.get(ImageAsset, image).enabled = False
        first = {'reply': 'Segue a foto.', 'action': 'send_image', 'image_id': image, 'image_intent': 'send_catalog'}
        with patch.object(client, 'reply', return_value=first), patch.object(client, 'save_profile', side_effect=disable):
            response = self.http.post('/api/client/'+self.token+'/messages', json={'content': 'Quero uma foto'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual([m['sender'] for m in self.http.get('/api/client/'+self.token).json()['messages']], ['cliente'])

    def test_initial_timeout_retries_only_inference_and_saves_one_response(self):
        with patch.object(client,'reply',side_effect=[subprocess.TimeoutExpired('fake',35),{'reply':'Como posso ajudar?','action':'none'}]) as model,patch.object(client,'execute_tool') as execute:
            self.http.post('/api/client/'+self.token+'/messages',json={'content':'Quero comprar'}).raise_for_status()
            self.assertEqual(model.call_count,2);execute.assert_not_called()
        items=self.http.get('/api/client/'+self.token).json()['messages']
        self.assertEqual([m['sender'] for m in items],['cliente','lumi'])

    def test_two_timeouts_are_visible_and_next_turn_keeps_unanswered_request(self):
        with patch.object(client,'reply',side_effect=subprocess.TimeoutExpired('fake',35)) as model:
            self.assertEqual(self.http.post('/api/client/'+self.token+'/messages',json={'content':'Quero comprar ingressos'}).status_code,503)
            self.assertEqual(model.call_count,2)
        items=self.http.get('/api/client/'+self.token).json()['messages']
        self.assertEqual(items[0]['response_status'],'failed')
        with patch.object(client,'reply',return_value={'reply':'Vamos continuar.','action':'none'}) as model:
            self.http.post('/api/client/'+self.token+'/messages',json={'content':'Qual a próxima data?'}).raise_for_status()
            self.assertIn('resposta anterior não concluída',model.call_args.args[0])
            self.assertIn('Quero comprar ingressos',model.call_args.args[0])

    def test_handover_during_timeout_cancels_retry(self):
        def pause(*args,**kwargs):
            with Session.begin() as db:
                db.get(Conversation,self.cid).status='humano';control(db,self.cid).revision+=1
            raise subprocess.TimeoutExpired('fake',35)
        with patch.object(client,'reply',side_effect=pause) as model:
            self.http.post('/api/client/'+self.token+'/messages',json={'content':'Teste'}).raise_for_status()
            self.assertEqual(model.call_count,1)

    def test_timeout_after_a_tool_does_not_repeat_the_operation_or_inference(self):
        tool={'name':'lookup','description':'Consulta de teste','parameters':{'type':'object','properties':{}}}
        first={'reply':'','action':'call_tool','tool_call':{'name':'lookup','arguments':{}}}
        with patch.object(client,'available_tools',return_value=[tool]),patch.object(client,'execute_tool',return_value={'ok':True}) as execute,patch.object(client,'reply',side_effect=[first,subprocess.TimeoutExpired('fake',35)]) as model:
            self.assertEqual(self.http.post('/api/client/'+self.token+'/messages',json={'content':'Consulte por favor'}).status_code,503)
            execute.assert_called_once();self.assertEqual(model.call_count,2)

    def test_codex_timeout_is_bounded_configuration(self):
        with patch.dict('os.environ',{'LUMI_CODEX_TIMEOUT_SECONDS':'900'}):self.assertEqual(providers.codex_timeout(),120)
        with patch.dict('os.environ',{'LUMI_CODEX_TIMEOUT_SECONDS':'invalid'}):self.assertEqual(providers.codex_timeout(),35)
