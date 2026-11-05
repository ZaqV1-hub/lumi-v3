import copy
import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from app import main, client
from app.db import Base, Session
from app.models import Tenant, Contact, Conversation, Message, MessageAuthor
from app.seed import seed
from app.instagram import bridge, webhook, graph
from app.instagram.models import Channel, Chat, Inbox, Outbox, MediaAccess
from app.whatsapp.webhook import app as receiver


class Queue:
    def __init__(self): self.jobs = []
    def submit(self, job): self.jobs.append(job)


class InstagramTest(unittest.TestCase):
    def setUp(self):
        self.previous = Session.kw['bind']
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + self.folder.name + '/instagram.db')
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        seed()
        with Session.begin() as db:
            self.tid = db.scalar(select(Tenant).where(Tenant.slug == 'rincao')).id
            self.other = db.scalar(select(Tenant).where(Tenant.slug == 'breve')).id
            db.add_all([Channel(profile_id='111', tenant_id=self.tid, token_env='IG_TOKEN', secret_env='IG_SECRET'),
                        Channel(profile_id='222', tenant_id=self.other, token_env='IG_OTHER', secret_env='OTHER_SECRET')])
        self.http = TestClient(receiver)
        self.queue = Queue()
        self.values = patch.object(webhook, 'value', side_effect=lambda name: {'IG_SECRET':'secret', 'OTHER_SECRET':'other', 'INSTAGRAM_VERIFY_TOKEN':'verify'}.get(name, ''))
        self.values.start()
        self.pool = patch.object(webhook, 'pool', self.queue)
        self.pool.start()

    def tearDown(self):
        self.values.stop(); self.pool.stop(); self.http.close()
        Session.configure(bind=self.previous)
        self.engine.dispose(); self.folder.cleanup()

    def payload(self, mid='ig.test', profile='111'):
        return {'object':'instagram','entry':[{'id':profile,'messaging':[{
            'timestamp':int(datetime.now(timezone.utc).timestamp()*1000),
            'sender':{'id':'999'},'recipient':{'id':profile},'message':{'mid':mid,'text':'Quero saber sobre o clube'}}]}]}

    def post(self, payload, secret='secret'):
        raw = json.dumps(payload).encode()
        return self.http.post('/webhooks/instagram', content=raw, headers={
            'x-hub-signature-256':'sha256='+hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()})

    def test_signature_routing_dedup_echo_and_unknown_profile(self):
        self.assertEqual(self.http.get('/admin').status_code, 404)
        self.assertEqual(self.http.get('/webhooks/instagram', params={'hub.mode':'subscribe','hub.verify_token':'verify','hub.challenge':'42'}).text, '42')
        payload = self.payload()
        self.assertEqual(self.post(payload, 'wrong').status_code, 401)
        self.assertEqual(self.post(payload).status_code, 200)
        self.assertEqual(self.post(payload).status_code, 200)
        echo = self.payload('echo');echo['entry'][0]['messaging'][0]['message']['is_echo']=True
        self.post(echo)
        self.post(self.payload('unknown', '333'))
        self.assertEqual(self.post(self.payload('forged', '222')).status_code, 401)
        self.assertEqual(len(self.queue.jobs), 1)
        with Session() as db:
            chat = db.scalar(select(Chat))
            conversation = db.get(Conversation, chat.id)
            contact = db.get(Contact, conversation.contact_id)
            self.assertEqual((conversation.tenant_id, contact.role), (self.tid, 'cliente'))
            self.assertEqual(db.scalar(select(func.count()).select_from(Inbox)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Message)), 1)

    def test_human_attendance_does_not_run_model_and_delivers_operator(self):
        self.post(self.payload())
        with Session.begin() as db:
            chat = db.scalar(select(Chat));cid=chat.id
            db.get(Conversation, cid).status = 'humano'
        self.post(self.payload('second'))
        self.assertEqual(len(self.queue.jobs), 1)
        with Session.begin() as db:
            message = Message(tenant_id=self.tid, conversation_id=cid, sender='humano', content='Estou por aqui')
            db.add(message);db.flush();mid=message.id
            db.add(MessageAuthor(message_id=mid, name='Operador'))
        with patch.object(bridge, 'send', return_value='ig.response') as send:
            self.assertTrue(bridge.deliver_one())
            self.assertEqual(send.call_args.args[:4], ('111','IG_TOKEN','999','𝗢𝗽𝗲𝗿𝗮𝗱𝗼𝗿\nEstou por aqui'))
        with Session.begin() as db:
            self.assertEqual(db.get(Outbox, mid).status, 'sent')
            db.get(Chat, cid).last_incoming_at = datetime.now(timezone.utc)-timedelta(hours=25)
            second = Message(tenant_id=self.tid, conversation_id=cid, sender='humano', content='Fora da janela')
            db.add(second);db.flush();second_id=second.id
        with patch.object(bridge, 'send') as send:
            bridge.deliver_one();send.assert_not_called()
        with Session() as db:self.assertEqual(db.get(Outbox, second_id).status, 'failed')

    def test_media_caption_and_unsupported_gallery(self):
        payload = self.payload()
        message=payload['entry'][0]['messaging'][0]['message']
        message['text']='Veja este ingresso'
        message['attachments']=[{'type':'image','payload':{'url':'https://scontent.cdninstagram.com/image'}}]
        attachment={'kind':'image','data':b'jpeg','mime':'image/jpeg','caption':message['text']}
        with patch.object(bridge, 'download_media', return_value=(b'jpeg','image/jpeg')) as download, patch('app.incoming.validated_file', return_value=attachment), patch.object(client, 'reply', return_value={'reply':'Recebi a imagem.','action':'none'}):
            self.assertEqual(self.post(payload).status_code, 200)
            download.assert_not_called()
            self.queue.jobs[0]()
            from app.incoming_models import IncomingAttachment
            with Session() as db:
                stored = db.scalar(select(IncomingAttachment))
                self.assertEqual(stored.caption, 'Veja este ingresso')
                self.assertEqual(stored.data, b'jpeg')
        gallery=copy.deepcopy(payload);gallery['entry'][0]['messaging'][0]['message']['mid']='gallery'
        gallery['entry'][0]['messaging'][0]['message']['attachments']*=2
        self.post(gallery)
        with Session() as db:self.assertEqual(db.get(Inbox, ('111','gallery')).status,'unsupported')

    def test_media_url_does_not_fetch_arbitrary_or_private_hosts(self):
        for url in ['http://scontent.cdninstagram.com/x','https://localhost/x','https://cdninstagram.com.evil.test/x','https://user@cdninstagram.com/x']:
            with self.assertRaises(ValueError):graph.media_url(url)
        with patch.object(graph.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):graph.media_url('https://scontent.cdninstagram.com/x')

    def test_full_text_response_uses_common_pipeline(self):
        self.post(self.payload())
        with patch.object(client, 'reply', return_value={'reply':'Posso ajudar com os ingressos.', 'action':'none'}) as model:
            self.queue.jobs[0]()
            model.assert_called_once()
        with Session() as db:
            self.assertEqual(db.get(Inbox, ('111','ig.test')).status, 'done')
            message=db.scalar(select(Message).where(Message.sender=='lumi'))
            self.assertEqual(message.tenant_id,self.tid)
            self.assertEqual(db.get(Outbox,message.id).status,'pending')

    def test_media_capability_expires_and_checks_asset_tenant(self):
        from app.instagram.media import public_image
        from app.media_models import ImageAsset, MessageImage
        self.post(self.payload())
        with Session.begin() as db:
            chat=db.scalar(select(Chat))
            image=ImageAsset(tenant_id=self.tid,name='Foto',description='Foto do local',when_to_use='Quando solicitada',data=b'jpeg')
            db.add(image);db.flush();image_id=image.id
            message=Message(tenant_id=self.tid,conversation_id=chat.id,sender='lumi',content='A foto')
            db.add(message);db.flush();mid=message.id
            db.add(MessageImage(message_id=mid,image_id=image.id));db.flush()
            with patch('app.instagram.media.value',return_value='https://receiver.example'):
                url=public_image(db,mid)
        path=url.removeprefix('https://receiver.example')
        self.assertEqual(self.http.get(path).content,b'jpeg')
        with Session.begin() as db:db.get(ImageAsset,image_id).tenant_id=self.other
        self.assertEqual(self.http.get(path).status_code,404)
        with Session.begin() as db:
            db.get(ImageAsset,image_id).tenant_id=self.tid
            db.get(MediaAccess,path.rsplit('/',1)[1]).expires_at=datetime.now(timezone.utc)-timedelta(minutes=1)
        self.assertEqual(self.http.get(path).status_code,404)

    def test_graph_host_and_message_request(self):
        import httpx
        original=httpx.Client
        requests=[]
        def respond(request):
            requests.append(request)
            return httpx.Response(200,json={'message_id':'test.sent'})
        config={'IG_TOKEN':'test-token','IG_TOKEN_GRAPH_HOST':'graph.facebook.com'}
        with patch.object(graph,'value',side_effect=lambda name:config.get(name,'')), patch.object(graph.httpx,'Client',side_effect=lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs)):
            self.assertEqual(graph.send('111','IG_TOKEN','999','Resposta'),'test.sent')
        self.assertEqual(requests[0].url.host,'graph.facebook.com')
        self.assertEqual(json.loads(requests[0].content),{'recipient':{'id':'999'},'message':{'text':'Resposta'}})
        with patch.object(graph,'value',side_effect=lambda name:'https://evil.test' if name.endswith('_GRAPH_HOST') else 'x'):
            with self.assertRaises(RuntimeError):graph.send('111','IG_TOKEN','999','Resposta')

    def test_private_token_validation_rejects_other_tenant_and_masks_token(self):
        import httpx
        from pathlib import Path
        from unittest.mock import AsyncMock
        from app.instagram import admin
        customer=TestClient(main.app)
        customer.post('/api/login',json={'email':'isaque@rincao.local','password':'demo1234'}).raise_for_status()
        token='test-private-token-never-returned'
        path=Path(self.folder.name)/'private.env'
        with patch.object(admin,'config_path',return_value=path),patch.object(admin.httpx,'AsyncClient') as client:
            get=AsyncMock(return_value=httpx.Response(200,json={'id':'111','username':'test_profile'}))
            client.return_value.__aenter__.return_value.get=get
            denied=customer.post('/api/admin/instagram/token',json={'profile_id':'222','token':token})
            self.assertEqual(denied.status_code,404);get.assert_not_called()
            saved=customer.post('/api/admin/instagram/token',json={'profile_id':'111','token':token})
            self.assertEqual(saved.status_code,200)
            self.assertNotIn(token,saved.text)
            self.assertIn(token,path.read_text())
            self.assertIn('graph.facebook.com',path.read_text())
            get.return_value=httpx.Response(200,json={'id':'222','username':'wrong_profile'})
            invalid=customer.post('/api/admin/instagram/token',json={'profile_id':'111','token':'different-private-token-value'})
            self.assertEqual(invalid.status_code,400)
            self.assertNotIn('different-private-token-value',path.read_text())
        customer.close()

    def test_audio_m4a_with_generic_mime_and_safe_redirect(self):
        import io
        import av
        import numpy as np
        import httpx
        from app.incoming import validated_file
        from app.audio import decode
        output=io.BytesIO()
        with av.open(output,mode='w',format='mp4') as container:
            stream=container.add_stream('aac',rate=16000)
            frame=av.AudioFrame.from_ndarray(np.zeros((1,16000),dtype=np.float32),format='fltp',layout='mono')
            frame.sample_rate=16000
            for packet in stream.encode(frame):container.mux(packet)
            for packet in stream.encode(None):container.mux(packet)
        binary=output.getvalue();original=httpx.Client;requests=[]
        def respond(request):
            requests.append(request)
            if len(requests)==1:return httpx.Response(302,headers={'location':'https://scontent.cdninstagram.com/voice.m4a'})
            return httpx.Response(200,content=binary,headers={'content-type':'application/octet-stream'})
        with patch.object(graph.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),patch.object(graph.httpx,'Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(respond),**kw)):
            data,mime=graph.download_media('https://lookaside.fbsbx.com/voice','audio')
        self.assertEqual(len(requests),2)
        attachment=validated_file(data,mime)
        self.assertEqual((attachment['kind'],attachment['mime']),('audio','audio/mp4'))
        samples,seconds=decode(attachment['data'])
        self.assertGreater(seconds,.9)

    def test_redirect_to_private_host_is_not_followed(self):
        import httpx
        original=httpx.Client;requests=[]
        def respond(request):
            requests.append(request)
            return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
        with patch.object(graph.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),patch.object(graph.httpx,'Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(respond),**kw)):
            with self.assertRaises(ValueError):graph.download_media('https://lookaside.fbsbx.com/voice','audio')
        self.assertEqual(len(requests),1)

    def test_media_failure_is_visible_and_does_not_leak_signed_url(self):
        import httpx
        payload=self.payload('failed-audio')
        message=payload['entry'][0]['messaging'][0]['message']
        message.pop('text')
        message['attachments']=[{'type':'audio','payload':{'url':'https://lookaside.fbsbx.com/voice?signature=secret-value'}}]
        request=httpx.Request('GET',message['attachments'][0]['payload']['url'])
        response=httpx.Response(403,request=request)
        with patch.object(bridge,'download_media',side_effect=httpx.HTTPStatusError('secret-value',request=request,response=response)):
            self.assertEqual(self.post(payload).status_code,200)
            self.post(payload)
            self.queue.jobs[0]()
        with Session() as db:
            row=db.get(Inbox,('111','failed-audio'))
            self.assertIn('HTTP 403',row.error)
            self.assertNotIn('secret-value',row.error)
            self.assertEqual(db.scalar(select(func.count()).select_from(Message)),2)
            self.assertEqual(db.scalar(select(func.count()).select_from(Outbox)),1)


if __name__ == '__main__': unittest.main()
