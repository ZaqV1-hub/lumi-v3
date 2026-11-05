import io
import tempfile
import unittest
import wave
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select


def picture():
    out=io.BytesIO();Image.new('RGB',(20,20),'red').save(out,format='PNG');return out.getvalue()


def audio(seconds=1):
    out=io.BytesIO()
    with wave.open(out,'wb') as file:
        file.setnchannels(1);file.setsampwidth(2);file.setframerate(16000);file.writeframes(b'\0\0'*(16000*seconds))
    return out.getvalue()


class IncomingTest(unittest.TestCase):
    def setUp(self):
        from app import main
        from app.db import Base,Session
        from app.seed import seed
        self.session=Session;self.previous=Session.kw['bind'];self.folder=tempfile.TemporaryDirectory()
        self.engine=create_engine('sqlite:///'+self.folder.name+'/incoming.db')
        Base.metadata.create_all(self.engine);Session.configure(bind=self.engine);seed()
        self.http=TestClient(main.app);self.other=TestClient(main.app)
        for http,email in [(self.http,'isaque@rincao.local'),(self.other,'ana@breve.local')]:
            http.post('/api/login',json={'email':email,'password':'demo1234'}).raise_for_status()
        self.token=self.http.post('/api/public/rincao/start',json={'name':'Teste'}).json()['token']
        self.cid=self.http.get('/api/admin/conversations').json()[0]['id']

    def tearDown(self):
        self.http.close();self.other.close();self.session.configure(bind=self.previous)
        self.engine.dispose();self.folder.cleanup()

    def test_image_reaches_model_and_cannot_be_read_by_another_tenant_or_contact(self):
        from app import client
        with patch.object(client,'reply',return_value={'reply':'Vejo uma imagem.','action':'none'}) as model:
            from urllib.parse import quote
            caption='Essa é a foto: você consegue me explicar?'
            response=self.http.post('/api/client/'+self.token+'/attachments',content=picture(),headers={'Content-Type':'image/png','X-Lumi-Caption':quote(caption)})
            self.assertEqual(response.status_code,200)
            images=model.call_args.kwargs['images'];self.assertEqual(len(images),1)
            self.assertTrue(images[0].startswith(b'\xff\xd8'))
            self.assertIn(caption,model.call_args.args[0]);self.assertEqual(model.call_count,1)
        items=self.http.get('/api/client/'+self.token).json()['messages'];image=next(m for m in items if m['attachment_kind'])
        self.assertEqual(image['content'],caption)
        self.assertEqual(self.http.get(image['attachment_url']).status_code,200)
        path='/api/admin/conversations/'+self.cid+'/attachments/'+image['id']
        self.assertEqual(self.other.get(path).status_code,404)
        token2=self.http.post('/api/public/rincao/start',json={'name':'Outro'}).json()['token']
        self.assertEqual(self.http.get('/api/client/'+token2+'/attachments/'+image['id']).status_code,404)

    def test_audio_is_transcribed_before_model_and_profile_context(self):
        from app import client
        from app import audio as provider
        with patch.object(provider,'transcribe',return_value=('Meu nome é Carlos e quero conhecer o clube.',3.5)), \
                patch.object(client,'reply',return_value={'reply':'Olá, Carlos.','action':'none'}) as model:
            response=self.http.post('/api/client/'+self.token+'/attachments',content=audio(),headers={'Content-Type':'audio/wav'})
        self.assertEqual(response.status_code,200)
        self.assertIn('Meu nome é Carlos',model.call_args.args[0])
        item=next(m for m in self.http.get('/api/client/'+self.token).json()['messages'] if m['attachment_kind'])
        self.assertIn('Transcrição do áudio',item['content']);self.assertEqual(item['attachment_kind'],'audio')

    def test_human_conversation_saves_media_without_running_ai_or_transcription(self):
        from app import client
        from app import audio as provider
        self.http.post('/api/admin/conversations/'+self.cid+'/claim').raise_for_status()
        with patch.object(client,'reply') as model,patch.object(provider,'transcribe') as speech:
            response=self.http.post('/api/client/'+self.token+'/attachments',content=audio(),headers={'Content-Type':'audio/wav'})
        self.assertEqual(response.status_code,200);model.assert_not_called();speech.assert_not_called()

    def test_invalid_media_does_not_reach_model(self):
        from app import client
        with patch.object(client,'reply') as model:
            for mime,data in [('image/svg+xml',b'<svg></svg>'),('audio/wav',b'http://127.0.0.1/private')]:
                response=self.http.post('/api/client/'+self.token+'/attachments',content=data,headers={'Content-Type':mime})
                self.assertEqual(response.status_code,422)
            model.assert_not_called()

    def test_audio_decoder_limits_duration_and_rejects_playlists(self):
        from app.audio import decode
        samples,duration=decode(audio())
        self.assertAlmostEqual(duration,1,places=1)
        with self.assertRaises(ValueError):decode(audio(121))
        with self.assertRaises(ValueError):decode(b'#EXTM3U\nhttp://127.0.0.1/private')

    def test_whatsapp_media_uses_same_tenant_scoped_pipeline(self):
        from types import SimpleNamespace
        from app import client
        from app import audio as provider
        from app.whatsapp import bridge, graph
        from app.whatsapp.models import Channel, Inbox
        from app.models import Conversation
        with self.session.begin() as db:
            tid=db.get(Conversation,self.cid).tenant_id
            db.add(Channel(phone_number_id='11111',tenant_id=tid))
        pool=SimpleNamespace(submit=lambda job:job())
        with patch.object(graph,'download_media',return_value=(picture(),'image/png')), \
                patch.object(client,'reply',return_value={'reply':'Recebi.','action':'none'}) as model:
            bridge.receive('11111',{'id':'qa-image','from':'5511999999999','type':'image','image':{'id':'12345'}},'Teste',pool)
            self.assertTrue(model.call_args.kwargs['images'])
        with patch.object(graph,'download_media',return_value=(audio(),'audio/wav')), \
                patch.object(provider,'transcribe',return_value=('Gostaria de conhecer o clube.',2.0)), \
                patch.object(client,'reply',return_value={'reply':'Recebi.','action':'none'}):
            bridge.receive('11111',{'id':'qa-audio','from':'5511999999999','type':'audio','audio':{'id':'12345'}},'Teste',pool)
        with self.session() as db:
            self.assertEqual(db.get(Inbox,'qa-image').status,'done')
            self.assertEqual(db.get(Inbox,'qa-audio').status,'done')

    def test_usage_is_visible_only_to_its_tenant(self):
        from app.usage import usage_scope, record
        from app.models import Conversation, Message
        with self.session.begin() as db:
            chat=db.get(Conversation,self.cid);tid=chat.tenant_id
            message=Message(tenant_id=tid,conversation_id=self.cid,sender='cliente',content='Teste')
            db.add(message);db.flush();mid=message.id
        with usage_scope(tid,self.cid,mid):record('codex','gpt-6.1-sol','completed',100,usage={'input_tokens':1000,'cached_input_tokens':0,'output_tokens':100})
        self.assertEqual(self.http.get('/api/admin/usage').status_code,403)
        self.assertEqual(self.other.get('/api/admin/usage').status_code,403)
        from app.console_models import ConsoleAccount
        from app.models import User
        other_tid=self.other.get('/api/me').json()['tenant_id']
        with self.session.begin() as db:
            operator=db.scalar(select(User).where(User.email=='ana@breve.local'))
            db.add(ConsoleAccount(user_id=operator.id,role='brevia'))
        self.assertEqual(self.other.get('/api/admin/usage',params={'tenant':tid}).json()['calls'],1)
        self.assertEqual(self.other.get('/api/admin/usage',params={'tenant':other_tid}).json()['calls'],0)
        self.assertEqual(self.other.get('/api/admin/usage',params={'tenant':other_tid,'conversation_id':self.cid}).status_code,404)
