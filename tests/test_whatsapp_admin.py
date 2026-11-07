import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
import httpx
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select


class WhatsappAdminTest(unittest.TestCase):
    def setUp(self):
        from app import main
        from app.db import Base, Session
        from app.seed import seed
        from app.models import Tenant
        from app.whatsapp.models import Channel
        self.session=Session;self.previous=Session.kw['bind']
        self.folder=tempfile.TemporaryDirectory()
        self.engine=create_engine('sqlite:///'+self.folder.name+'/test.db')
        Base.metadata.create_all(self.engine);Session.configure(bind=self.engine);seed()
        with Session.begin() as db:
            for slug,phone in [('rincao','111111'),('breve','222222')]:
                tid=db.scalar(select(Tenant.id).where(Tenant.slug==slug))
                db.add(Channel(tenant_id=tid,phone_number_id=phone))
        self.http=TestClient(main.app);self.other=TestClient(main.app)
        for http,email in [(self.http,'isaque@rincao.local'),(self.other,'ana@breve.local')]:
            http.post('/api/login',json={'email':email,'password':'demo1234'}).raise_for_status()
        self.path=Path(self.folder.name)/'private.env';self.path.touch()
        self.env=patch.dict(os.environ,{'WHATSAPP_GRAPH_VERSION':'v23.0'});self.env.start()

    def tearDown(self):
        self.http.close();self.other.close();self.env.stop()
        self.session.configure(bind=self.previous);self.engine.dispose();self.folder.cleanup()

    def test_token_is_tenant_scoped_validated_and_never_returned(self):
        from app.whatsapp import admin
        from app.whatsapp.models import Channel
        token='fake-sensitive-token-for-tests-only'
        with patch.object(admin,'config_path',return_value=self.path),patch.object(admin.httpx,'AsyncClient') as client:
            get=AsyncMock(return_value=httpx.Response(200,json={'id':'111111','display_phone_number':'+1 555 000 0000'}))
            client.return_value.__aenter__.return_value.get=get
            self.assertEqual(self.other.get('/api/admin/whatsapp/channels').json(),[{'phone_id':'222222'}])
            response=self.other.post('/api/admin/whatsapp/token',json={'phone_id':'111111','token':token})
            self.assertEqual(response.status_code,404);get.assert_not_called()
            self.assertNotIn(token,self.path.read_text())
            response=self.http.post('/api/admin/whatsapp/token',json={'phone_id':'111111','token':token})
            self.assertEqual(response.status_code,200);self.assertNotIn(token,response.text)
            self.assertIn('WHATSAPP_CHANNEL_TOKEN_111111',self.path.read_text())
            with self.session() as db:self.assertEqual(db.get(Channel,'111111').token_env,'WHATSAPP_CHANNEL_TOKEN_111111')

    def test_invalid_token_is_not_saved_or_echoed(self):
        from app.whatsapp import admin
        token='fake-sensitive-token-for-tests-only'
        with patch.object(admin,'config_path',return_value=self.path),patch.object(admin.httpx,'AsyncClient') as client:
            client.return_value.__aenter__.return_value.get=AsyncMock(return_value=httpx.Response(401,json={'error':{'message':token}}))
            response=self.http.post('/api/admin/whatsapp/token',json={'phone_id':'111111','token':token})
            self.assertEqual(response.status_code,400);self.assertNotIn(token,response.text)
            self.assertEqual(self.path.read_text(),'')

    def test_renewed_token_is_read_without_process_restart(self):
        from app.whatsapp import config
        self.path.write_text('CHANNEL_TOKEN=fresh-token\n')
        with patch.object(config,'config_path',return_value=self.path),patch.dict(os.environ,{'CHANNEL_TOKEN':'expired-token'}):
            self.assertEqual(config.access_token('CHANNEL_TOKEN'),'fresh-token')

    def test_token_renewal_preserves_specific_secret_without_changing_shared_channel(self):
        from app.whatsapp import admin, config
        from app.whatsapp.models import Channel
        for secret in ['custom-app-secret', '']:
            with self.subTest(secret_present=bool(secret)):
                with self.session.begin() as db:
                    db.get(Channel,'111111').token_env='CUSTOM_TOKEN'
                    db.get(Channel,'222222').token_env='CUSTOM_TOKEN'
                self.path.write_text('CUSTOM_TOKEN=old-shared-token\nCUSTOM_TOKEN_APP_SECRET='+secret+'\nWHATSAPP_APP_SECRET=wrong-global\n')
                token='fake-new-token-for-tests-only'
                with patch.object(admin,'config_path',return_value=self.path),patch.object(config,'config_path',return_value=self.path),patch.object(admin.httpx,'AsyncClient') as client:
                    client.return_value.__aenter__.return_value.get=AsyncMock(return_value=httpx.Response(200,json={'id':'111111'}))
                    response=self.http.post('/api/admin/whatsapp/token',json={'phone_id':'111111','token':token})
                    self.assertEqual(response.status_code,200)
                    self.assertNotIn(token,response.text)
                    self.assertEqual(config.app_secret('WHATSAPP_CHANNEL_TOKEN_111111'),secret)
                    self.assertEqual(config.app_secret('CUSTOM_TOKEN'),secret)
                    values=dotenv_values(self.path)
                    self.assertEqual(values['WHATSAPP_CHANNEL_TOKEN_111111_APP_SECRET'],secret)
                    self.assertEqual(values['CUSTOM_TOKEN'],'old-shared-token')
                    self.assertEqual(values['WHATSAPP_APP_SECRET'],'wrong-global')
                    with self.session() as db:
                        self.assertEqual(db.get(Channel,'111111').token_env,'WHATSAPP_CHANNEL_TOKEN_111111')
                        self.assertEqual(db.get(Channel,'222222').token_env,'CUSTOM_TOKEN')

    def test_renewal_rechecks_current_channel_reference_after_meta_validation(self):
        from app.whatsapp import admin, config
        from app.whatsapp.models import Channel
        self.path.write_text('LATEST_TOKEN_APP_SECRET=latest-app-secret\nWHATSAPP_APP_SECRET=wrong-global\n')
        async def validated(*args, **kwargs):
            with self.session.begin() as db:
                db.get(Channel,'111111').token_env='LATEST_TOKEN'
            return httpx.Response(200,json={'id':'111111'})
        with patch.object(admin,'config_path',return_value=self.path),patch.object(config,'config_path',return_value=self.path),patch.object(admin.httpx,'AsyncClient') as client:
            client.return_value.__aenter__.return_value.get=AsyncMock(side_effect=validated)
            response=self.http.post('/api/admin/whatsapp/token',json={'phone_id':'111111','token':'fake-new-token-for-tests-only'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(config.app_secret('WHATSAPP_CHANNEL_TOKEN_111111'),'latest-app-secret')

    def test_renewal_does_not_write_files_if_channel_moves_to_another_tenant(self):
        from app.whatsapp import admin, config
        from app.whatsapp.models import Channel
        original='WHATSAPP_APP_SECRET=legacy-test-secret\n'
        self.path.write_text(original)
        async def validated(*args, **kwargs):
            with self.session.begin() as db:
                db.get(Channel,'111111').tenant_id=db.get(Channel,'222222').tenant_id
            return httpx.Response(200,json={'id':'111111'})
        with patch.object(admin,'config_path',return_value=self.path),patch.object(config,'config_path',return_value=self.path),patch.object(admin.httpx,'AsyncClient') as client:
            client.return_value.__aenter__.return_value.get=AsyncMock(side_effect=validated)
            response=self.http.post('/api/admin/whatsapp/token',json={'phone_id':'111111','token':'fake-new-token-for-tests-only'})
            self.assertEqual(response.status_code,404)
            self.assertEqual(self.path.read_text(),original)

    def test_renewal_refuses_destination_credential_shared_with_another_channel(self):
        from app.whatsapp import admin, config
        from app.whatsapp.models import Channel
        original='WHATSAPP_CHANNEL_TOKEN_111111=other-channel-token\n'
        self.path.write_text(original)
        with self.session.begin() as db:
            db.get(Channel,'222222').token_env='WHATSAPP_CHANNEL_TOKEN_111111'
        with patch.object(admin,'config_path',return_value=self.path),patch.object(config,'config_path',return_value=self.path),patch.object(admin.httpx,'AsyncClient') as client:
            client.return_value.__aenter__.return_value.get=AsyncMock(return_value=httpx.Response(200,json={'id':'111111'}))
            response=self.http.post('/api/admin/whatsapp/token',json={'phone_id':'111111','token':'fake-new-token-for-tests-only'})
            self.assertEqual(response.status_code,409)
            self.assertEqual(self.path.read_text(),original)
            with self.session() as db:
                self.assertEqual(db.get(Channel,'111111').token_env,'WHATSAPP_ACCESS_TOKEN')

    def test_registration_scoped_verified_only_and_pin_not_returned(self):
        from app.whatsapp import registration
        state={'id':'111111','status':'PENDING','platform_type':'NOT_APPLICABLE','code_verification_status':'VERIFIED'}
        with patch.object(registration,'access_token',return_value='private-token'),patch.object(registration.httpx,'AsyncClient') as client:
            api=client.return_value.__aenter__.return_value
            api.get=AsyncMock(return_value=httpx.Response(200,json=state))
            api.post=AsyncMock(return_value=httpx.Response(200,json={'success':True}))
            denied=self.other.post('/api/admin/whatsapp/registration/111111',json={'pin':'654321'})
            self.assertEqual(denied.status_code,404);api.post.assert_not_called()
            invalid=self.http.post('/api/admin/whatsapp/registration/111111',json={'pin':'abcdef'})
            self.assertEqual(invalid.status_code,400);api.post.assert_not_called()
            registered=self.http.post('/api/admin/whatsapp/registration/111111',json={'pin':'654321'})
            self.assertEqual(registered.status_code,200)
            self.assertNotIn('654321',registered.text)
            self.assertEqual(api.post.call_args.kwargs['json'],{'messaging_product':'whatsapp','pin':'654321'})
            self.assertEqual(self.path.read_text(),'')
            api.post.reset_mock()
            api.get.return_value=httpx.Response(200,json={**state,'platform_type':'CLOUD_API','status':'CONNECTED'})
            protected=self.http.post('/api/admin/whatsapp/registration/111111',json={'pin':'654321'})
            self.assertEqual(protected.status_code,409);api.post.assert_not_called()
