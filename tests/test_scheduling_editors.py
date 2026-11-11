import json
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import httpx
from tests import test_scheduling as base
from contextlib import closing
from services.scheduling import engine, store
from services.scheduling.google import GoogleCalendar


class EditorTest(base.SchedulingTest):
    def setUp(self):
        super().setUp()
        path=Path(self.temp.name)/"config.json"
        configs=json.loads(path.read_text())
        for value in configs.values(): value["editor_roles"]=["corretor"]
        path.write_text(json.dumps(configs))

    def booking(self):
        p=self.prepare()
        self.request("/confirm",{"proposal_id":p["proposal_id"]},message="m2")
        return p["proposal_id"]

    def test_editor_permissions_and_scope(self):
        bid=self.booking()
        args={"proposal_id":bid,"description":"Interesse em dois dormitórios"}
        self.assertEqual(self.request("/description",args).status_code,403)
        self.assertEqual(self.request("/agenda",{"start_date":"2027-01-04","end_date":"2027-01-04"}).status_code,403)
        self.assertEqual(self.slots()["ok"],True)
        self.assertEqual(self.request("/participants",{"proposal_id":bid,"emails":[],"resend_invitations":True},role="corretor").status_code,403)
        self.assertEqual(self.request("/confirm",{"proposal_id":bid},role="corretor").status_code,403)
        self.assertEqual(self.request("/description",args,role="corretor",tenant="t2").json()["ok"],False)
        self.assertEqual(self.request("/description",args,role="corretor",secret="wrong").status_code,403)
        self.assertEqual(self.request("/description",{**args,"start":"tomorrow"},role="corretor").status_code,422)
        out=self.request("/description",args,role="corretor",conversation="broker").json()
        self.assertTrue(out["description_updated"])
        with closing(store.connect()) as db, db:
            row=db.execute("SELECT * FROM bookings WHERE id=?",(bid,)).fetchone()
            self.assertEqual(row["topic"],args["description"])
        listing=self.request("/agenda",{"start_date":"2027-01-04","end_date":"2027-01-04"},role="corretor").json()
        self.assertEqual(listing["meetings"][0]["proposal_id"],bid)
        self.assertTrue(listing["context_reference"])
        self.assertFalse(listing["meetings"][0]["description_truncated"])
        other=self.request("/agenda",{"start_date":"2027-01-04","end_date":"2027-01-04"},role="corretor",tenant="t2").json()
        self.assertEqual(other["meetings"],[])

    def test_google_patch_description_only(self):
        booking={"id":"b1","event":"e1","start":"2027-01-04T14:00:00Z","end":"2027-01-04T14:30:00Z"}
        event={"id":"e1","status":"confirmed","etag":"v1","extendedProperties":{"private":{"lumi_booking":"b1","other":"keep"}},"attendees":[{"email":"guest@example.test"}]}
        from services.scheduling.config import CalendarConfig
        provider=GoogleCalendar(CalendarConfig.model_validate(self.config))
        response=httpx.Response(200,json=event,request=httpx.Request("PATCH","https://example.test"))
        with patch.object(provider,"get",return_value=event),patch.object(provider,"request",return_value=response) as request:
            provider.description(booking,"Nova descrição","op1")
            payload=request.call_args.kwargs
            self.assertEqual(set(payload["json"]),{"description","extendedProperties"})
            self.assertEqual(payload["headers"],{"If-Match":"v1"})
            self.assertEqual(payload["params"],{"sendUpdates":"none"})

    def test_uncertain_description_is_recovered_without_second_patch(self):
        bid=self.booking()
        args={"proposal_id":bid,"description":"Nova descrição"}
        path=Path(self.temp.name)/"config.json"
        configs=json.loads(path.read_text()); configs["t1"].update(mode="google",token_file="mock.json")
        path.write_text(json.dumps(configs))
        # Booking scope changes only in this isolated fake fixture.
        with closing(store.connect()) as db, db:
            db.execute("UPDATE bookings SET scope='google:broker@example.test' WHERE id=?",(bid,))
        class Provider:
            event=None
            calls=0
            def description(self,booking,text,op):
                self.calls+=1
                self.event={"id":booking["event"],"status":"confirmed","extendedProperties":{"private":{"lumi_booking":booking["id"],"lumi_description_op":op}}}
                raise TimeoutError()
            def get(self,event): return self.event
        provider=Provider()
        with patch.object(engine,"provider",return_value=provider):
            first=self.request("/description",args,role="corretor").json()
            second=self.request("/description",args,role="corretor").json()
            self.assertEqual(first["status"],"confirmed")
            self.assertEqual(second["status"],"confirmed")
            self.assertEqual(provider.calls,1)

    def test_concurrent_description_is_not_duplicated(self):
        bid=self.booking();args={"proposal_id":bid,"description":"Descrição única"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.request("/description",args,role="corretor").json(),range(2)))
        self.assertTrue(all(r["status"] in ("confirmed","pending_verification") for r in results))
        with closing(store.connect()) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM description_changes").fetchone()[0],1)
