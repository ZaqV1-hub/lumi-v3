import unittest
from unittest.mock import patch
from sqlalchemy import select
from test_attendance import AttendanceFixture

class ConsentTest(AttendanceFixture):
    def test_visible_mode_shows_number_without_request_and_preserves_tenant_scope(self):
        from app.contact_consent import public_contact,ensure_request,PhoneConsent,prompt_context
        from app.phone_visibility import PhoneVisibility
        from app.models import Message
        self.prepare()
        with self.Session.begin() as db:
            db.delete(db.get(PhoneConsent,self.mid))
            db.add(PhoneVisibility(tenant_id='t',mode='visible'));db.flush()
            self.assertEqual(public_contact(db,'t','c')['phone'],'+15550000001')
            self.assertIsNone(public_contact(db,'other','c')['phone'])
            self.assertEqual(public_contact(db,'t','c')['phone_consent'],'not_required')
            ensure_request(db,db.get(Message,'anchor'),'read');db.flush()
            self.assertEqual(len(list(db.scalars(select(PhoneConsent)))),0)
            self.assertEqual(prompt_context(db,'t','c'),'')

    def test_hidden_mode_hides_even_previously_authorized_number(self):
        from app.contact_consent import public_contact,PhoneConsent,may_send_request
        from app.phone_visibility import PhoneVisibility
        self.prepare()
        with self.Session.begin() as db:
            db.get(PhoneConsent,self.mid).granted=True
            db.add(PhoneVisibility(tenant_id='t',mode='hidden'));db.flush()
            self.assertIsNone(public_contact(db,'t','c')['phone'])
            self.assertEqual(public_contact(db,'t','c')['phone_consent'],'hidden')
            self.assertFalse(may_send_request(db,self.mid,'t'))
            self.assertTrue(may_send_request(db,'anchor','t'))

    def test_visible_mode_does_not_expose_another_tenants_channel(self):
        from app.contact_consent import public_contact
        from app.phone_visibility import PhoneVisibility
        from app.whatsapp.models import Channel
        self.prepare()
        with self.Session.begin() as db:
            db.add(PhoneVisibility(tenant_id='t',mode='visible'))
            db.get(Channel,'111111').tenant_id='other';db.flush()
            self.assertIsNone(public_contact(db,'t','c')['phone'])

    def test_disabling_consent_cancels_queued_request_without_sending(self):
        from app.phone_visibility import PhoneVisibility
        from app.whatsapp.models import Outbox
        from app.whatsapp.bridge import deliver_one
        self.prepare()
        with self.Session.begin() as db:
            db.add(PhoneVisibility(tenant_id='t',mode='visible'))
            db.get(Outbox,self.mid).status='pending'
        with patch('app.whatsapp.bridge.send') as send:
            self.assertTrue(deliver_one())
            send.assert_not_called()
        with self.Session() as db:
            self.assertEqual(db.get(Outbox,self.mid).status,'cancelled')

    def test_only_brevia_changes_visibility_and_normal_save_preserves_it(self):
        from types import SimpleNamespace
        from fastapi import HTTPException
        from app.attendance import PolicyInput,save_policy,get_policy
        operator=SimpleNamespace(tenant_id='t',console_role='admin')
        with self.assertRaises(HTTPException) as error:
            save_policy(PolicyInput(phone_visibility='visible'),operator)
        self.assertEqual(error.exception.status_code,403)
        owner=SimpleNamespace(tenant_id='t',console_role='brevia')
        result=save_policy(PolicyInput(phone_visibility='visible'),owner)
        self.assertEqual(result['phone_visibility'],'visible')
        self.assertFalse(result['phone_consent'])
        save_policy(PolicyInput(phone_visibility='visible',timeout_enabled=True),operator)
        self.assertEqual(get_policy(operator)['phone_visibility'],'visible')
        with self.assertRaises(HTTPException):
            save_policy(PolicyInput(phone_visibility='hidden'),operator)

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
