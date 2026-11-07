import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import client, main
from app.business_models import ManagementChat
from app.console_models import ConsoleAccount
from app.db import Base, Session
from app.incoming_models import IncomingAttachment
from app.media_models import ImageAsset, MessageImage
from app.models import Message, Tenant, User, VisitorSession
from app.seed import seed
from app.tenant_runtime import TenantChatPolicy


class PrivateSimulatorTest(unittest.TestCase):
    def setUp(self):
        self.previous = Session.kw['bind']
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + self.temp.name + '/private.db')
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        seed()
        self.env = patch.dict(os.environ, {'LUMI_PRIVATE_SIMULATOR': 'true'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.cleanup_db)
        self.anonymous = self.browser()
        self.owner = self.browser('isaque@rincao.local')
        self.foreign = self.browser('ana@breve.local')
        with Session() as db:
            self.tid = db.scalar(select(Tenant.id).where(Tenant.slug == 'rincao'))
            self.owner_id = db.scalar(select(User.id).where(User.email == 'isaque@rincao.local'))
            self.foreign_id = db.scalar(select(User.id).where(User.email == 'ana@breve.local'))
        # Create an existing token independently of the new protection.
        with patch.dict(os.environ, {'LUMI_PRIVATE_SIMULATOR': 'false'}):
            self.token = self.start(self.owner).json()['token']
        self.url = '/api/client/' + self.token
        with Session.begin() as db:
            visitor = db.get(VisitorSession, self.token)
            self.cid = visitor.conversation_id
            message = Message(tenant_id=self.tid, conversation_id=self.cid, sender='lumi', content='Mensagem de teste')
            image = ImageAsset(tenant_id=self.tid, name='Teste', description='Teste', when_to_use='Teste', data=b'image-test')
            db.add_all([message, image]); db.flush()
            db.add(MessageImage(message_id=message.id, image_id=image.id))
            db.add(IncomingAttachment(message_id=message.id, tenant_id=self.tid,
                conversation_id=self.cid, kind='image', mime='image/jpeg', data=b'attachment-test'))
            self.image_url = self.url + '/images/' + image.id
            self.attachment_url = self.url + '/attachments/' + message.id

    def cleanup_db(self):
        Session.configure(bind=self.previous)
        self.engine.dispose()
        self.temp.cleanup()

    def browser(self, email=None, scheme='http'):
        browser = TestClient(main.app, base_url=scheme + '://testserver')
        self.addCleanup(browser.close)
        if email:
            browser.post('/api/login', json={'email': email, 'password': 'demo1234'}).raise_for_status()
        return browser

    def start(self, browser):
        return browser.post('/api/public/rincao/start', json={'name': 'Teste'})

    def test_anonymous_cannot_start_or_access_simulator(self):
        self.assertEqual(self.start(self.anonymous).status_code, 401)
        page = self.anonymous.get('/chat/rincao', follow_redirects=False)
        self.assertIn(page.status_code, (401, 307))
        if page.status_code == 307:
            self.assertEqual(page.headers['location'], '/admin')

    def test_all_token_routes_require_session_and_same_tenant(self):
        for browser, expected in ((self.anonymous, 401), (self.foreign, 403)):
            for method, url, kwargs in (
                ('GET', self.url, {}), ('GET', self.image_url, {}),
                ('GET', self.attachment_url, {}),
                ('POST', self.url + '/messages', {'json': {'content': 'Oi'}}),
                ('POST', self.url + '/attachments', {'content': b'bad-image', 'headers': {'content-type': 'image/jpeg'}}),
            ):
                with self.subTest(method=method, url=url, expected=expected):
                    with patch.object(client, 'reply', return_value={'reply': 'Teste', 'action': 'none'}):
                        self.assertEqual(browser.request(method, url, **kwargs).status_code, expected)
        self.assertEqual(self.start(self.foreign).status_code, 403)
        self.assertEqual(self.foreign.get('/chat/rincao').status_code, 403)

    def test_authorized_user_can_start_read_media_and_send(self):
        self.assertEqual(self.start(self.owner).status_code, 200)
        self.assertEqual(self.owner.get('/chat/rincao').status_code, 200)
        self.assertEqual(self.owner.get(self.image_url).content, b'image-test')
        self.assertEqual(self.owner.get(self.attachment_url).content, b'attachment-test')
        with patch.object(client, 'reply', return_value={'reply': 'Resposta de teste', 'action': 'none'}):
            self.owner.post(self.url + '/messages', json={'content': 'Oi'}).raise_for_status()
        history = self.owner.get(self.url).json()['messages']
        self.assertIn('Resposta de teste', [m['content'] for m in history])

    def test_brevia_cross_tenant_still_preserves_management_owner(self):
        with Session.begin() as db:
            db.add(ConsoleAccount(user_id=self.foreign_id, role='brevia'))
        self.assertEqual(self.start(self.foreign).status_code, 200)
        self.assertEqual(self.foreign.get(self.url).status_code, 200)
        self.assertEqual(self.foreign.get('/chat/rincao').status_code, 200)
        with Session.begin() as db:
            db.add(ManagementChat(conversation_id=self.cid, actor_id=self.owner_id))
        self.assertEqual(self.foreign.get(self.url).status_code, 403)
        self.assertEqual(self.owner.get(self.url).status_code, 200)

    def test_readonly_cannot_start_or_send_and_password_change_blocks_access(self):
        with Session.begin() as db:
            db.add(ConsoleAccount(user_id=self.owner_id, role='leitura'))
            db.add(ConsoleAccount(user_id=self.foreign_id, role='leitura'))
        self.assertEqual(self.foreign.get(self.url).status_code, 403)
        self.assertEqual(self.foreign.get(self.attachment_url).status_code, 403)
        self.assertEqual(self.owner.get(self.url).status_code, 200)
        self.assertEqual(self.start(self.owner).status_code, 403)
        with patch.object(client, 'reply', return_value={'reply': 'Teste', 'action': 'none'}):
            self.assertEqual(self.owner.post(self.url + '/messages', json={'content': 'Oi'}).status_code, 403)
        with Session.begin() as db:
            account = db.get(ConsoleAccount, self.owner_id)
            account.role = 'admin'
            account.must_change_password = True
        self.assertEqual(self.start(self.owner).status_code, 403)
        self.assertEqual(self.owner.get(self.attachment_url).status_code, 403)
        self.assertEqual(self.owner.get('/chat/rincao').status_code, 403)

    def test_tenant_role_policy_remains_enforced(self):
        with Session.begin() as db:
            db.add(TenantChatPolicy(tenant_id=self.tid, allowed_roles='gestor'))
        self.assertEqual(self.start(self.owner).status_code, 409)
        self.assertEqual(self.owner.get(self.url).json()['status'], 'desativada')
        with patch.object(client, 'reply', side_effect=AssertionError('Provider must not run')):
            self.owner.post(self.url + '/messages', json={'content': 'Oi'}).raise_for_status()

    def test_default_keeps_public_simulator(self):
        os.environ.pop('LUMI_PRIVATE_SIMULATOR')
        self.assertEqual(self.start(self.anonymous).status_code, 200)
        self.assertEqual(self.anonymous.get('/chat/rincao').status_code, 200)
        self.assertEqual(self.anonymous.get(self.url).status_code, 200)
        self.assertEqual(self.anonymous.get(self.image_url).content, b'image-test')
        self.assertEqual(self.anonymous.get(self.attachment_url).content, b'attachment-test')

    def test_session_cookie_secure_matches_request_scheme(self):
        for scheme, secure in (('http', False), ('https', True)):
            with self.subTest(scheme=scheme):
                browser = self.browser(scheme=scheme)
                response = browser.post('/api/login', json={'email': 'isaque@rincao.local', 'password': 'demo1234'})
                response.raise_for_status()
                self.assertEqual('Secure' in response.headers['set-cookie'], secure)
                self.assertEqual(browser.get('/api/me').status_code, 200)
                response = browser.post('/api/logout')
                self.assertEqual('Secure' in response.headers['set-cookie'], secure)
                self.assertEqual(browser.get('/api/me').status_code, 401)
