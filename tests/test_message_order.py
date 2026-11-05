import io
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from sqlalchemy import create_engine, select
from app import main, client
from app.db import Base, Session
from app.models import Tenant, Message
from app.media_models import ContactGate
from app.seed import seed
from app.whatsapp import bridge as whatsapp
from app.whatsapp.models import Channel as WhatsAppChannel, Chat as WhatsAppChat
from app.instagram import bridge as instagram
from app.instagram.models import Channel as InstagramChannel, Chat as InstagramChat


class MessageOrderTest(unittest.TestCase):
    def setUp(self):
        self.previous = Session.kw['bind']
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + self.folder.name + '/order.db')
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(Session.configure, bind=self.previous)
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        seed()
        with Session.begin() as db:
            tid = db.scalar(select(Tenant).where(Tenant.slug == 'rincao')).id
            db.add(WhatsAppChannel(phone_number_id='111', tenant_id=tid))
            db.add(InstagramChannel(profile_id='222', tenant_id=tid, token_env='TEST_IG_TOKEN'))
        self.jobs = []
        self.pool = SimpleNamespace(submit=self.jobs.append)

    def receive(self, channel, mid, text, media=None, sender='999'):
        if channel == 'whatsapp':
            incoming = {'id': mid, 'from': sender, 'type': media or 'text'}
            incoming[media or 'text'] = {'id': 'media', 'caption': text} if media else {'body': text}
            whatsapp.receive('111', incoming, 'Teste', self.pool)
        else:
            message = {'mid': mid, 'text': text}
            if media:
                message['attachments'] = [{'type': media, 'payload': {'url': 'https://lookaside.fbsbx.com/media'}}]
            instagram.receive('222', {'sender': {'id': sender}, 'recipient': {'id': '222'},
                'timestamp': int(datetime.now(timezone.utc).timestamp()*1000), 'message': message}, self.pool)

    def check_slow_media(self, channel, media):
        from app import audio
        from app.whatsapp import graph
        entered, release, text_started = threading.Event(), threading.Event(), threading.Event()
        image = io.BytesIO()
        Image.new('RGB', (10, 10), 'red').save(image, format='PNG')
        attachment = {'kind': media, 'mime': 'image/jpeg' if media == 'image' else 'audio/wav',
            'data': image.getvalue() if media == 'image' else b'audio', 'caption': 'Primeira pergunta'}

        def download(*args):
            entered.set()
            if not release.wait(10):
                raise TimeoutError('Teste não liberou a mídia')
            return attachment['data'], attachment['mime']

        def answer(prompt, **kwargs):
            return {'reply': 'Resposta ' + str(model.call_count), 'action': 'none'}

        target = graph if channel == 'whatsapp' else instagram
        with patch.object(target, 'download_media', side_effect=download), \
                patch('app.incoming.validated_file', return_value=attachment), \
                patch.object(audio, 'transcribe', return_value=('Primeiro áudio', 1.0)), \
                patch.object(client, 'reply', side_effect=answer) as model, \
                ThreadPoolExecutor(max_workers=3) as workers:
            self.receive(channel, channel + media + '-1', 'Primeira pergunta', media)
            self.assertFalse(entered.is_set(), 'A admissão não deve baixar a mídia')
            first = workers.submit(self.jobs[-1])
            try:
                self.assertTrue(entered.wait(5))
                self.receive(channel, channel + media + '-2', 'Segunda pergunta')
                text_job = self.jobs[-1]

                def start_text():
                    text_started.set()
                    text_job()

                second = workers.submit(start_text)
                self.assertTrue(text_started.wait(5))
                # Outro contato não deve esperar pelo download deste contato.
                self.receive(channel, channel + media + '-other', 'Outra conversa', sender='888')
                self.jobs[-1]()
                self.assertEqual(model.call_count, 1)
            finally:
                release.set()
            first.result(timeout=10)
            second.result(timeout=10)
            self.assertEqual(model.call_count, 3)
            first_prompt = model.call_args_list[1].args[0]
            next_prompt = model.call_args_list[2].args[0]
            self.assertNotIn('Segunda pergunta', first_prompt)
            self.assertIn('Segunda pergunta', next_prompt)
            self.assertIn('Resposta 2', next_prompt)
        chat_type = WhatsAppChat if channel == 'whatsapp' else InstagramChat
        with Session() as db:
            chat = db.scalar(select(chat_type).where(chat_type.sender == '999'))
            replies = list(db.scalars(select(Message.content).where(Message.conversation_id == chat.id,
                Message.sender == 'lumi').order_by(Message.created_at)))
            self.assertEqual(replies, ['Resposta 2', 'Resposta 3'])
            self.assertTrue(all(g.pending == 0 for g in db.scalars(select(ContactGate))))

    def test_whatsapp_image_before_text(self):
        self.check_slow_media('whatsapp', 'image')

    def test_whatsapp_audio_before_text(self):
        self.check_slow_media('whatsapp', 'audio')

    def test_instagram_image_before_text(self):
        self.check_slow_media('instagram', 'image')

    def test_instagram_audio_before_text(self):
        self.check_slow_media('instagram', 'audio')

    def test_download_failure_releases_next_message(self):
        from app.whatsapp import graph
        self.receive('whatsapp', 'bad-image', 'Imagem', 'image')
        self.receive('whatsapp', 'next-text', 'Texto seguinte')
        with patch.object(graph, 'download_media', side_effect=TimeoutError), \
                patch.object(client, 'reply', return_value={'reply': 'Respondi ao texto.', 'action': 'none'}) as model:
            self.jobs[0]()
            self.jobs[1]()
            model.assert_called_once()
        with Session() as db:
            self.assertEqual(db.scalar(select(ContactGate)).pending, 0)


if __name__ == '__main__':
    unittest.main()
