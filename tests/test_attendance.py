import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from sqlalchemy import create_engine,select,func

class AttendanceFixture(unittest.TestCase):
    def setUp(self):
        from app import main
        from app.db import Base,Session
        from app.models import Tenant,Contact,Conversation,Message,Feature
        from app.attendance import AttendancePolicy,AttendanceRequest
        self.Session=Session;self.previous=Session.kw['bind'];self.folder=tempfile.TemporaryDirectory()
        self.engine=create_engine('sqlite:///'+self.folder.name+'/test.db');Base.metadata.create_all(self.engine);Session.configure(bind=self.engine)
        self.at=datetime.now(timezone.utc)
        with Session.begin() as db:
            db.add_all([Tenant(id='t',name='Example',slug='example',identity='',personality=''),Tenant(id='other',name='Other',slug='other',identity='',personality='')]);db.flush()
            db.add(Contact(id='p',tenant_id='t',name='Example',role='cliente'));db.flush()
            db.add(Conversation(id='c',tenant_id='t',contact_id='p',status='aguardando'));db.flush()
            db.add_all([Message(id='customer',tenant_id='t',conversation_id='c',sender='cliente',content='Quero falar com a equipe',created_at=self.at),Message(id='anchor',tenant_id='t',conversation_id='c',sender='lumi',content='Solicitação registrada',created_at=self.at)]);db.flush()
            db.add(Feature(id='handover',tenant_id='t',name='handover',description='',endpoint='native:assist',roles='cliente',enabled=True))
            db.add(AttendancePolicy(tenant_id='t',hours_enabled=False,timeout_enabled=True,timeout_minutes=10,timeout_mode='both'))
            db.add(AttendanceRequest(conversation_id='c',tenant_id='t',message_id='anchor',requested_at=self.at,available_since=self.at))
        self.calls=patch('app.whatsapp.calling.has_active_call',return_value=False);self.calls.start()
    def tearDown(self):
        self.calls.stop();self.Session.configure(bind=self.previous);self.engine.dispose();self.folder.cleanup()

class AttendanceTest(AttendanceFixture):
    def test_admin_policy_and_waiting_count_respect_tenant_and_readonly(self):
        import hashlib,time
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models import User,LoginSession
        from app.console_models import ConsoleAccount
        from app.attendance import AttendancePolicy
        token=str(int(time.time()))+'.isolated-test-session'
        with self.Session.begin() as db:
            db.add(User(id='operator',tenant_id='t',name='Operator',email='operator@example.test',salt='test',password_hash='test'));db.flush()
            db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),user_id='operator',last_activity=int(time.time())))
            db.add(ConsoleAccount(user_id='operator',role='admin',enabled=True,must_change_password=False))
        http=TestClient(app);self.addCleanup(http.close);http.cookies.set('lumi_session',token)
        self.assertEqual(http.get('/api/admin/attendance/waiting').json()['waiting_count'],1)
        self.assertEqual(http.get('/api/admin/attendance?tenant=other').status_code,403)
        self.assertEqual(http.put('/api/admin/attendance',json={'timeout_enabled':True,'timeout_minutes':12}).status_code,200)
        with self.Session.begin() as db:
            self.assertEqual(db.get(AttendancePolicy,'t').timeout_minutes,12)
            self.assertIsNone(db.get(AttendancePolicy,'other'))
            db.get(ConsoleAccount,'operator').role='leitura'
        self.assertEqual(http.put('/api/admin/attendance',json={}).status_code,403)

    def test_waiting_timeout_only_once_and_ai_still_active(self):
        from app.attendance_worker import process
        from app.models import Message,Conversation
        process('c',self.at+timedelta(minutes=9))
        process('c',self.at+timedelta(minutes=11));process('c',self.at+timedelta(minutes=20))
        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Message)),3)
            self.assertEqual(db.get(Conversation,'c').status,'aguardando')
    def test_claim_without_reply_returns_to_queue_but_not_during_call(self):
        from app.attendance_worker import process
        from app.models import Conversation
        from app.attendance import AttendanceRequest
        from app.media_models import ConversationControl
        with self.Session.begin() as db:
            db.get(Conversation,'c').status='humano';db.get(AttendanceRequest,'c').claimed_at=self.at
            db.add(ConversationControl(conversation_id='c',revision=1,operator_id='operator'))
        with patch('app.whatsapp.calling.has_active_call',return_value=True):process('c',self.at+timedelta(minutes=11))
        with self.Session() as db:self.assertEqual(db.get(Conversation,'c').status,'humano')
        process('c',self.at+timedelta(minutes=11))
        with self.Session() as db:
            self.assertEqual(db.get(Conversation,'c').status,'aguardando');self.assertIsNone(db.get(ConversationControl,'c').operator_id)
    def test_human_already_answered_does_not_expire(self):
        from app.attendance_worker import process
        from app.models import Conversation,Message
        from app.attendance import AttendanceRequest
        with self.Session.begin() as db:
            db.get(Conversation,'c').status='humano';db.get(AttendanceRequest,'c').claimed_at=self.at
            db.add(Message(tenant_id='t',conversation_id='c',sender='humano',content='Estou aqui',created_at=self.at+timedelta(seconds=10)))
        process('c',self.at+timedelta(minutes=20))
        with self.Session() as db:self.assertEqual(db.get(Conversation,'c').status,'humano')
    def test_schedule_supports_next_opening_and_overnight(self):
        from app.attendance import AttendancePolicy,schedule,PolicyInput
        from pydantic import ValidationError
        p=AttendancePolicy(hours_enabled=True,timezone='America/Sao_Paulo',windows=json.dumps([{'weekday':0,'start':'22:00','end':'02:00'}]))
        self.assertTrue(schedule(p,datetime(2030,1,8,3,0,tzinfo=timezone.utc))[0])
        opened,next_start=schedule(p,datetime(2030,1,8,6,0,tzinfo=timezone.utc));self.assertFalse(opened);self.assertIsNotNone(next_start)
        with self.assertRaises(ValidationError):PolicyInput(hours_enabled=True,windows=[])
        with self.assertRaises(ValidationError):PolicyInput(timezone='not-a-zone')
    def test_closed_business_defers_alert_until_open(self):
        from app.attendance import AttendancePolicy,AttendanceRequest
        from app.attendance_worker import process
        from app.whatsapp.handover_alerts import HandoverAlert
        from app.whatsapp.models import Channel
        monday=datetime(2030,1,7,10,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            policy=db.get(AttendancePolicy,'t');policy.hours_enabled=True;policy.windows=json.dumps([{'weekday':0,'start':'08:00','end':'18:00'}])
            row=db.get(AttendanceRequest,'c');row.available_since=None;row.requested_at=monday
            db.add(Channel(phone_number_id='111111',tenant_id='t',token_env='FAKE'));db.flush()
            db.add(HandoverAlert(message_id='anchor',phone_number_id='111111',topic='outro',status='deferred'))
        process('c',monday)
        with self.Session() as db:self.assertEqual(db.get(HandoverAlert,'anchor').status,'deferred')
        process('c',monday+timedelta(hours=1))
        with self.Session() as db:self.assertEqual(db.get(HandoverAlert,'anchor').status,'pending')
