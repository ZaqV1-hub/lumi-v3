import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.db import Base, Session
from app.models import Tenant
from app.whatsapp import config, webhook
from app.whatsapp.models import Channel


class WhatsAppSecretTest(unittest.TestCase):
    def setUp(self):
        self.previous = Session.kw['bind']
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + self.folder.name + '/secrets.db')
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        with Session.begin() as db:
            first = Tenant(name='Empresa A', slug='a', identity='A', personality='A')
            second = Tenant(name='Empresa B', slug='b', identity='B', personality='B')
            db.add_all([first, second]); db.flush()
            db.add_all([Channel(phone_number_id='111', tenant_id=first.id, token_env='TOKEN_A'),
                        Channel(phone_number_id='222', tenant_id=second.id, token_env='TOKEN_B')])
        self.path = Path(self.folder.name) / 'whatsapp.env'
        self.path.write_text('TOKEN_A_APP_SECRET=secret-a\nTOKEN_B_APP_SECRET=secret-b\n')
        self.path_patch = patch.object(config, 'config_path', return_value=self.path)
        self.path_patch.start()
        self.env_patch = patch.dict(os.environ, {'WHATSAPP_APP_SECRET': 'legacy'})
        self.env_patch.start()
        self.receive = patch.object(webhook, 'receive').start()
        self.delivery = patch.object(webhook, 'record_delivery').start()
        self.http = TestClient(webhook.app)

    def tearDown(self):
        self.http.close()
        patch.stopall()
        Session.configure(bind=self.previous)
        self.engine.dispose()
        self.folder.cleanup()

    def payload(self, *phones):
        return {'object': 'whatsapp_business_account', 'entry': [{'changes': [
            {'field': 'messages', 'value': {
                'metadata': {'phone_number_id': phone},
                'statuses': [{'id': 'response-' + phone, 'status': 'delivered'}],
                'messages': [{'id': 'message-' + phone, 'from': '5511999999999',
                              'type': 'text', 'text': {'body': 'Teste fictício'}}]}}
            for phone in phones]}]}

    def post(self, body, secret):
        raw = json.dumps(body).encode()
        signature = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return self.http.post('/webhooks/whatsapp', content=raw,
                              headers={'x-hub-signature-256': signature})

    def assert_not_processed(self):
        self.receive.assert_not_called()
        self.delivery.assert_not_called()

    def test_each_tenant_accepts_only_its_registered_app_secret(self):
        for phone, secret, other in [('111', 'secret-a', 'secret-b'), ('222', 'secret-b', 'secret-a')]:
            with self.subTest(phone=phone):
                self.assertEqual(self.post(self.payload(phone), other).status_code, 401)
                self.assert_not_processed()
                self.assertEqual(self.post(self.payload(phone), 'legacy').status_code, 401)
                self.assert_not_processed()
                self.assertEqual(self.post(self.payload(phone), secret).status_code, 200)
                self.assertEqual(self.receive.call_args.args[0], phone)
                self.assertEqual(self.delivery.call_args.args[0], phone)
                self.receive.reset_mock(); self.delivery.reset_mock()

    def test_mixed_apps_validate_entire_payload_before_any_delivery_or_message(self):
        for phones, signature in [(('111', '222'), 'secret-a'), (('222', '111'), 'secret-b')]:
            with self.subTest(phones=phones):
                self.assertEqual(self.post(self.payload(*phones), signature).status_code, 401)
                self.assert_not_processed()

    def test_explicit_empty_secret_does_not_fall_back_to_global_or_environment(self):
        for assignment in ['TOKEN_A_APP_SECRET=\n', 'TOKEN_A_APP_SECRET\n']:
            self.path.write_text(assignment)
            with patch.dict(os.environ, {'TOKEN_A_APP_SECRET': 'secret-a'}):
                self.assertEqual(self.post(self.payload('111'), 'legacy').status_code, 503)
                self.assertEqual(self.post(self.payload('111'), 'secret-a').status_code, 503)
            self.assert_not_processed()
        self.path.write_text('')
        with patch.dict(os.environ, {'TOKEN_A_APP_SECRET': ''}):
            self.assertEqual(self.post(self.payload('111'), 'legacy').status_code, 503)
        self.assert_not_processed()

    def test_channels_from_same_app_can_share_one_signed_batch(self):
        self.path.write_text('TOKEN_A_APP_SECRET=same-app\nTOKEN_B_APP_SECRET=same-app\n')
        self.assertEqual(self.post(self.payload('111', '222'), 'same-app').status_code, 200)
        self.assertEqual([call.args[0] for call in self.receive.call_args_list], ['111', '222'])
        self.assertEqual([call.args[0] for call in self.delivery.call_args_list], ['111', '222'])

    def test_missing_specific_secret_keeps_legacy_hml_support(self):
        self.path.write_text('')
        self.assertEqual(self.post(self.payload('111'), 'legacy').status_code, 200)
        self.assertEqual(self.receive.call_args.args[0], '111')
        self.assertEqual(self.post({}, 'legacy').status_code, 200)
        self.assertEqual(self.post({}, 'wrong').status_code, 401)

    def test_unknown_channel_is_never_processed_even_in_mixed_payload(self):
        self.assertEqual(self.post(self.payload('999'), 'legacy').status_code, 200)
        self.assert_not_processed()
        self.assertEqual(self.post(self.payload('111', '999'), 'secret-a').status_code, 200)
        self.assertEqual([call.args[0] for call in self.receive.call_args_list], ['111'])
        self.assertEqual([call.args[0] for call in self.delivery.call_args_list], ['111'])

    def test_channel_secret_works_without_global_and_request_cannot_supply_secret(self):
        with patch.dict(os.environ, {'WHATSAPP_APP_SECRET': ''}):
            body = self.payload('111')
            body['secret'] = 'attacker'
            body['entry'][0]['changes'][0]['value']['token_env'] = 'TOKEN_B'
            self.assertEqual(self.post(body, 'attacker').status_code, 401)
            self.assert_not_processed()
            self.assertEqual(self.post(body, 'secret-a').status_code, 200)

    def test_oversized_request_is_rejected_before_processing(self):
        response = self.http.post('/webhooks/whatsapp', content=b'x' * (1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)
        self.assert_not_processed()
