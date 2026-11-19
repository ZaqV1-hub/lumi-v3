import unittest
from unittest.mock import patch
from sqlalchemy import select
from test_attendance import AttendanceFixture

class ConsentTest(AttendanceFixture):
    def prepare(self):
        from app.attendance import AttendancePolicy
        from app.whatsapp.models import Chat,Channel,Outbox
        from app.models import Message
        from app.contact_consent import ensure_request,PhoneConsent
        with self.Session.begin() as db:
            db.get(AttendancePolicy,'t').phone_consent=True
            db.add(Channel(phone_number_id='111111',tenant_id='t',token_env='FAKE'));db.flush()
            db.add(Chat(id='c',phone_number_id='111111',sender='15550000001',token='test-token'));db.flush()
            ensure_request(db,db.get(Message,'anchor'),'sent');db.flush()
            row=db.scalar(select(PhoneConsent));self.mid=row.message_id;self.nonce=row.nonce
            sent=db.get(Outbox,self.mid)
            if not sent:sent=Outbox(message_id=self.mid);db.add(sent)
            sent.status='read';sent.external_id='meta-offer'
    def test_number_hidden_until_real_button_and_can_be_revoked(self):
        from app.contact_consent import public_contact,accept_button,PhoneConsentEvent
        self.prepare()
        def incoming(choice,external='meta-answer'):
            return {'type':'interactive','id':external,'context':{'id':'meta-offer'},'interactive':{'type':'button_reply','button_reply':{'id':'phone:'+self.nonce+':'+choice}}}
        with self.Session.begin() as db:
            self.assertIsNone(public_contact(db,'t','c')['phone'])
            self.assertIsNone(accept_button(db,'other','c',incoming('yes')))
            bad=incoming('yes');bad['context']['id']='another-offer';self.assertIsNone(accept_button(db,'t','c',bad))
            self.assertIsNotNone(accept_button(db,'t','c',incoming('yes')));db.flush()
            self.assertEqual(public_contact(db,'t','c')['phone'],'+15550000001')
            accept_button(db,'t','c',incoming('no','revoke'));db.flush()
            self.assertIsNone(public_contact(db,'t','c')['phone'])
            accept_button(db,'t','c',incoming('yes'));db.flush()
            self.assertIsNone(public_contact(db,'t','c')['phone'])
            self.assertEqual(len(list(db.scalars(select(PhoneConsentEvent)))),2)
    def test_no_consent_request_on_failed_delivery_and_no_repeat(self):
        from app.contact_consent import ensure_request,PhoneConsent
        from app.models import Message
        self.prepare()
        with self.Session.begin() as db:
            ensure_request(db,db.get(Message,'anchor'),'sent');ensure_request(db,db.get(Message,'anchor'),'failed');db.flush()
            self.assertEqual(len(list(db.scalars(select(PhoneConsent)))),1)

    def test_authorization_does_not_follow_a_changed_channel_identity(self):
        from app.contact_consent import public_contact, accept_button
        from app.whatsapp.models import Chat
        self.prepare()
        incoming={'type':'interactive','id':'approval','context':{'id':'meta-offer'},'interactive':{'type':'button_reply','button_reply':{'id':'phone:'+self.nonce+':yes'}}}
        with self.Session.begin() as db:
            accept_button(db,'t','c',incoming);db.flush()
            db.get(Chat,'c').sender='15550000003';db.flush()
            self.assertIsNone(public_contact(db,'t','c')['phone'])
            incoming['id']='different-identity'
            self.assertIsNone(accept_button(db,'t','c',incoming))
