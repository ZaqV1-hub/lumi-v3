import copy
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from services.scheduling import api, engine, store
from services.scheduling.google import GoogleCalendar, public_event
from services.scheduling.config import CalendarConfig


class SchedulingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = {"secret": "s"*40, "roles": ["cliente"], "mode": "demo", "calendar_id": "broker@example.test",
            "timezone": "America/Sao_Paulo", "duration_minutes": 30, "lead_minutes": 60, "horizon_days": 30,
            "hours": {"0": [["09:00", "12:00"], ["14:00", "18:00"]]}, "title": "Reunião de demonstração"}
        (root/"config.json").write_text(json.dumps({"t1": self.config, "t2": {**self.config, "secret":"z"*40}}), encoding="utf-8")
        self.env = patch.dict(os.environ, {"LUMI_SCHEDULING_CONFIG":str(root/"config.json"), "LUMI_SCHEDULING_DATA":str(root/"state")})
        self.env.start()
        self.now = patch.object(engine, "clock", return_value=datetime(2027,1,4,8,tzinfo=timezone.utc))
        self.now.start()
        self.http = TestClient(api.app)

    def tearDown(self):
        self.http.close(); self.now.stop(); self.env.stop(); self.temp.cleanup()

    def request(self, path, args, conversation="c1", message="m1", tenant="t1", secret=None, role="cliente"):
        return self.http.post(path, json={"tenant_id":tenant, "conversation_id":conversation, "role":role,
            "arguments":args, "context":{"message_id":message}},
            headers={"Authorization":"Bearer "+(secret or ("z"*40 if tenant=="t2" else "s"*40))})

    def slots(self, conversation="c1", tenant="t1"):
        return self.request("/availability", {"start_date":"2027-01-04", "end_date":"2027-01-04", "period":None}, conversation=conversation, tenant=tenant).json()

    def prepare(self, conversation="c1", tenant="t1"):
        slot = self.slots(conversation, tenant)["slots"][0]
        response = self.request("/prepare", {"slot_id":slot["slot_id"], "name":"Pessoa Teste", "email":"person@example.test", "topic":"Visita de demonstração"}, conversation=conversation, tenant=tenant)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()["ok"], response.json())
        return response.json()

    def test_demo_full_flow_confirm_only_later_message_and_duplicate(self):
        proposal = self.prepare(); self.assertEqual(proposal["status"],"awaiting_confirmation")
        args = {"proposal_id":proposal["proposal_id"]}
        self.assertEqual(self.request("/confirm",args).json()["error"],"aguardando_confirmacao_do_cliente")
        original = engine.DemoCalendar.create
        with patch.object(engine.DemoCalendar,"create", autospec=True, side_effect=original) as create:
            self.assertEqual(self.request("/confirm",args,message="m2").json()["status"],"confirmed")
            self.assertTrue(self.request("/confirm",args,message="m3").json()["simulated"])
            self.assertEqual(create.call_count,1)
        self.assertEqual(self.request("/status",args).json()["status"],"confirmed")

    def test_tenant_role_credential_and_conversation_cannot_bypass(self):
        args={"start_date":None,"end_date":None,"period":None}
        for kwargs in [{"tenant":"other"},{"secret":"wrong"},{"role":"administrador"}]:
            self.assertEqual(self.request("/availability",args,**kwargs).status_code,403)
        proposal=self.prepare();ref={"proposal_id":proposal["proposal_id"]}
        self.assertFalse(self.request("/confirm",ref,conversation="other",message="m2").json()["ok"])
        self.assertFalse(self.request("/status",ref,tenant="t2").json()["ok"])
        own_slot=self.slots()["slots"][0]["slot_id"]
        self.assertFalse(self.request("/prepare",{"slot_id":own_slot,"name":"Teste","email":"person@example.test","topic":"Visita"},conversation="other").json()["ok"])

    def test_calendar_overlap_across_conversations_and_tenants(self):
        a,b=self.prepare(),self.prepare("c2","t2")
        self.assertEqual(a["start"],b["start"])
        self.assertEqual(self.request("/confirm",{"proposal_id":a["proposal_id"]},message="m2").json()["status"],"confirmed")
        self.assertEqual(self.request("/confirm",{"proposal_id":b["proposal_id"]},conversation="c2",tenant="t2",message="m2").json()["error"],"horario_nao_disponivel")
        self.assertNotIn(engine.parse(a["start"]), [engine.parse(s["start"]) for s in self.slots("c2")["slots"]])

    def test_concurrent_confirmation_does_not_double_create(self):
        proposal=self.prepare();args={"proposal_id":proposal["proposal_id"]}
        original=engine.DemoCalendar.create
        with patch.object(engine.DemoCalendar,"create", autospec=True, side_effect=original) as create:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda n:self.request("/confirm",args,message="m"+str(n)).json(),[2,3]))
            self.assertEqual(create.call_count,1)
            self.assertTrue(all(r.get("status") in ("confirmed","pending_verification") for r in results),results)

    def test_timeout_recovers_by_stable_event_id_without_reinsertion(self):
        proposal=self.prepare();args={"proposal_id":proposal["proposal_id"]}
        events={}
        class LostResponse:
            def busy(self,*args):return []
            def create(self,booking):
                events[booking["event"]]={"id":booking["event"],"status":"confirmed","extendedProperties":{"private":{"lumi_booking":booking["id"]}}}
                raise TimeoutError()
            def get(self,event_id):return events.get(event_id)
        with patch.object(engine,"provider",return_value=LostResponse()):
            self.assertEqual(self.request("/confirm",args,message="m2").json()["status"],"confirmed")
            self.assertEqual(self.request("/confirm",args,message="m3").json()["status"],"confirmed")
            self.assertEqual(len(events),1)

    def test_missing_uncertain_result_does_not_repeat_write_or_release_slot(self):
        a,b=self.prepare(),self.prepare("c2")
        class Unknown:
            def busy(self,*args):return []
            def create(self,booking):raise TimeoutError()
            def get(self,event_id):return None
        with patch.object(engine,"provider",return_value=Unknown()):
            self.assertEqual(self.request("/confirm",{"proposal_id":a["proposal_id"]},message="m2").json()["status"],"pending_verification")
            self.assertEqual(self.request("/confirm",{"proposal_id":a["proposal_id"]},message="m3").json()["status"],"pending_verification")
            self.assertEqual(self.request("/confirm",{"proposal_id":b["proposal_id"]},conversation="c2",message="m2").json()["error"],"horario_nao_disponivel")

    def test_business_hours_expiration_and_validation_do_not_echo_values(self):
        slots=self.slots()["slots"]
        self.assertEqual(len(slots),14)
        self.assertTrue(all("T12:" not in s["start"] and "T13:" not in s["start"] for s in slots))
        response=self.request("/prepare",{"slot_id":slots[0]["slot_id"],"name":"Pessoa","email":"PRIVATE-BAD-VALUE","topic":"Visita"})
        self.assertEqual(response.status_code,422)
        self.assertNotIn("PRIVATE-BAD-VALUE",response.text)
        proposal=self.prepare()
        with patch.object(engine,"clock",return_value=datetime(2027,1,4,9,tzinfo=timezone.utc)):
            self.assertEqual(self.request("/confirm",{"proposal_id":proposal["proposal_id"]},message="m2").json()["error"],"proposta_expirada")
        self.assertFalse(self.request("/availability",{"start_date":"2028-01-01","end_date":"2028-01-01","period":None}).json()["ok"])

    def test_google_contract_uses_scoped_calendar_stable_id_and_explicit_invites(self):
        config=CalendarConfig.model_validate({**self.config,"mode":"google","token_file":"private.json","create_meet":True,"send_invites":True})
        google=GoogleCalendar(config)
        booking={"id":"p","event":"lumi123","start":"2027-01-04T12:00:00+00:00","end":"2027-01-04T12:30:00+00:00","name":"Teste","email":"person@example.test","topic":"Visita"}
        from unittest.mock import Mock
        response=Mock(status_code=200);response.json.return_value={"calendars":{config.calendar_id:{"errors":[{"reason":"forbidden"}]}}}
        with patch.object(google,"request",return_value=response) as req:
            with self.assertRaises(RuntimeError):google.busy(engine.parse(booking["start"]),engine.parse(booking["end"]))
            response.json.return_value={"id":booking["event"]}
            google.create(booking)
            self.assertIn("broker%40example.test/events",req.call_args.args[1])
            self.assertEqual(req.call_args.kwargs["params"],{"sendUpdates":"all","conferenceDataVersion":1})
            self.assertEqual(req.call_args.kwargs["json"]["id"],"lumi123")
        with self.assertRaises(RuntimeError):public_event({"id":"different","status":"confirmed"},booking)

    def test_editing_prepared_details_requires_a_new_confirmation_turn(self):
        proposal=self.prepare()
        db=store.connect()
        try:slot=db.execute("select slot from bookings where id=?",(proposal["proposal_id"],)).fetchone()[0]
        finally:db.close()
        edited=self.request("/prepare",{"slot_id":slot,"name":"Nome Corrigido","email":"new@example.test","topic":"Visita"},message="m2").json()
        self.assertEqual(edited["proposal_id"],proposal["proposal_id"])
        self.assertEqual(edited["email"],"new@example.test")
        self.assertEqual(self.request("/confirm",{"proposal_id":proposal["proposal_id"]},message="m2").json()["error"],"aguardando_confirmacao_do_cliente")

    def test_google_409_recovers_the_same_event_and_rejects_foreign_metadata(self):
        from unittest.mock import Mock
        config=CalendarConfig.model_validate({**self.config,"mode":"google","token_file":"private.json"})
        google=GoogleCalendar(config)
        booking={"id":"p","event":"lumi123","start":"2027-01-04T12:00:00+00:00","end":"2027-01-04T12:30:00+00:00","name":"Teste","email":"person@example.test","topic":"Visita"}
        existing={"id":"lumi123","status":"confirmed","extendedProperties":{"private":{"lumi_booking":"p"}}}
        collision=Mock(status_code=409)
        recovered=Mock(status_code=200);recovered.json.return_value=existing
        with patch.object(google,"request",side_effect=[collision,recovered]) as request:
            self.assertEqual(public_event(google.create(booking),booking)["status"],"confirmed")
            self.assertEqual([c.args[0] for c in request.call_args_list],["POST","GET"])
        existing["extendedProperties"]["private"]["lumi_booking"]="other"
        with self.assertRaises(RuntimeError):public_event(existing,booking)

    def test_participant_update_is_scoped_and_idempotent(self):
        proposal=self.prepare();ref={"proposal_id":proposal["proposal_id"]}
        self.request("/confirm",ref,message="m2")
        args={**ref,"emails":["guest@example.test"],"resend_invitations":True}
        self.assertFalse(self.request("/participants",args,conversation="other").json()["ok"])
        self.assertFalse(self.request("/participants",args,tenant="t2").json()["ok"])
        self.assertEqual(self.request("/participants",args,role="administrador").status_code,403)
        first=self.request("/participants",args,message="m3").json()
        second=self.request("/participants",args,message="m3").json()
        self.assertEqual(first,second);self.assertFalse(first["invitations_requested"])
        self.assertEqual(self.request("/participants",args,message="m4").json()["error"],"convite_solicitado_recentemente")
        db=store.connect()
        try:self.assertEqual(db.execute("select count(*) from participant_changes").fetchone()[0],1)
        finally:db.close()

    def test_google_guest_patch_preserves_guests_and_etag(self):
        from unittest.mock import Mock
        config=CalendarConfig.model_validate({**self.config,"mode":"google","token_file":"private.json","send_invites":True})
        google=GoogleCalendar(config)
        booking={"id":"p","event":"lumi123","start":"s","end":"e"}
        event={"id":"lumi123","status":"confirmed","etag":'"v1"',"attendees":[{"email":"old@example.test","responseStatus":"accepted"}],
            "extendedProperties":{"private":{"lumi_booking":"p","preserve":"yes"}}}
        response=Mock();response.json.return_value=event
        with patch.object(google,"get",return_value=event),patch.object(google,"request",return_value=response) as request:
            google.participants(booking,["new@example.test"],"operation",True)
            kwargs=request.call_args.kwargs
            self.assertEqual(kwargs["headers"],{"If-Match":'"v1"'})
            self.assertEqual(kwargs["params"]["sendUpdates"],"all")
            self.assertEqual(kwargs["json"]["attendees"],[{"email":"old@example.test","responseStatus":"accepted"},{"email":"new@example.test"}])
            self.assertNotIn("start",kwargs["json"]);self.assertNotIn("conferenceData",kwargs["json"])
            self.assertEqual(kwargs["json"]["extendedProperties"]["private"]["preserve"],"yes")

    def test_uncertain_guest_update_recovers_without_second_patch(self):
        from services.scheduling.config import settings
        from services.scheduling.api import ParticipantsCall
        from services.scheduling.participants import update
        from unittest.mock import Mock
        proposal=self.prepare();ref={"proposal_id":proposal["proposal_id"]}
        self.request("/confirm",ref,message="m2")
        config=settings()["t1"].model_copy(update={"mode":"google","send_invites":True})
        db=store.connect()
        try:
            db.execute("update bookings set scope=? where id=?",(config.scope,proposal["proposal_id"]));db.commit()
            booking=store.scoped(db,proposal["proposal_id"],"t1","c1")
        finally:db.close()
        event={"id":booking["event"],"status":"confirmed","extendedProperties":{"private":{"lumi_booking":booking["id"]}}}
        fake=Mock()
        def lost(_booking,emails,operation,resend):
            event["extendedProperties"]["private"]["lumi_participants_op"]=operation
            raise TimeoutError()
        fake.participants.side_effect=lost;fake.get.return_value=event
        call=ParticipantsCall(tenant_id="t1",conversation_id="c1",role="cliente",context={"message_id":"m3"},arguments={**ref,"emails":["guest@example.test"],"resend_invitations":True})
        with patch.object(engine,"provider",return_value=fake):
            self.assertEqual(update(config,call)["status"],"confirmed")
            self.assertTrue(update(config,call)["invitations_requested"])
            self.assertEqual(fake.participants.call_count,1)

    def test_concurrent_participant_requests_and_v1_migration_preserve_booking(self):
        proposal=self.prepare();ref={"proposal_id":proposal["proposal_id"]}
        self.request("/confirm",ref,message="m2")
        db=store.connect()
        try:
            db.execute("DROP TABLE participant_changes");db.execute("PRAGMA user_version=1");db.commit()
        finally:db.close()
        args={**ref,"emails":["guest@example.test"],"resend_invitations":False}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.request("/participants",args,message="m3").json(),[1,2]))
        self.assertTrue(all(r.get("status")=="confirmed" for r in results),results)
        db=store.connect()
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],3)
            self.assertEqual(db.execute("select count(*) from participant_changes").fetchone()[0],1)
            self.assertEqual(store.scoped(db,proposal["proposal_id"],"t1","c1")["state"],"confirmed")
        finally:db.close()


if __name__ == "__main__":
    unittest.main()
