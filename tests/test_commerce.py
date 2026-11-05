import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from services.rincao import commerce, commerce_status, cielo_checkout
from services.rincao.commerce_models import Cart, Buyer
from services.rincao.commerce_store import connect, load


QUOTE = {"totalAmount": 140, "visitDate": "2027-01-01", "availabilityStatus": "open", "items": [
    {"sku": "adult", "title": "Adulto", "quantity": 2, "unit_price": 70,
     "visit_date": "2027-01-01", "ticket_type": "padrao", "agenda_id": 10, "voucher_type": "norma"}]}


class CommerceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RINCAO_COMMERCE_DATA_DIR": self.folder.name,
            "RINCAO_COMMERCE_TENANT_ID": "test-tenant"})
        self.env.start()
        self.ready = patch.object(cielo_checkout, "is_enabled", return_value=True)
        self.ready.start()
        self.cart = Cart(visit_date="2027-01-01", ticket_type="padrao", adults=2, children=0, exempt=0)
        self.context = {"message_id": "message-1", "whatsapp": "5511964120664", "customer_messages": ["CPF de teste: 529.982.247-25"]}

    def tearDown(self):
        self.ready.stop(); self.env.stop(); self.folder.cleanup()

    def quote(self):
        with patch.object(commerce, "request", return_value={"ok": True, "quote": copy.deepcopy(QUOTE)}):
            return commerce.quote_cart("tenant", "conversation", self.cart, self.context)

    def buyer(self, quote_id):
        return Buyer(quote_id=quote_id, name="Cliente de teste", cpf="52998224725", phone="11999999999")

    def upstream(self, operation, payload):
        if operation == "quote":
            return {"ok": True, "quote": copy.deepcopy(QUOTE)}
        self.assertEqual(operation, "pending")
        self.assertEqual(payload["buyer"]["phone"], self.context["whatsapp"])
        self.assertEqual(payload["buyer"]["cpf"], "52998224725")
        self.assertEqual(payload["items"][0]["unitPrice"], 70)
        return {"externalOrderId": "123", "status": "pending"}

    def purchase(self, quote_id):
        with patch.object(commerce, "request", side_effect=self.upstream) as upstream, patch.object(cielo_checkout, "create_page", return_value="https://cieloecommerce.cielo.com.br/test") as gateway:
            result = commerce.purchase("tenant", "conversation", self.buyer(quote_id), self.context)
        return result, upstream, gateway

    def test_quote_without_cpf_and_owner_scope(self):
        first = self.quote(); second = self.quote()
        self.assertEqual(first["quote_id"], second["quote_id"])
        with self.assertRaises(ValueError):
            commerce.purchase("another", "conversation", self.buyer(first["quote_id"]), self.context)
        with self.assertRaises(ValueError):
            Buyer(quote_id=first["quote_id"], name="Nome", cpf="11111111111")

    def test_checkout_config_wins_over_obsolete_tools_url(self):
        from pathlib import Path
        from services.rincao.config import load_config
        root = Path(self.folder.name)
        (root / 'Lumi').mkdir()
        (root / 'Lumi' / 'cielo.env').write_text('RINCAO_CHECKOUT_PUBLIC_URL=https://current.test\n')
        tools = root / 'tools.env'
        tools.write_text('RINCAO_CHECKOUT_PUBLIC_URL=https://obsolete.test\n')
        with patch.dict(os.environ, {'LOCALAPPDATA': str(root), 'USERPROFILE': str(root),
                                     'RINCAO_TOOLS_ENV': str(tools)}, clear=True):
            load_config()
            self.assertEqual(os.environ['RINCAO_CHECKOUT_PUBLIC_URL'], 'https://current.test')

    def test_pending_link_idempotent_and_no_price_from_model(self):
        q = self.quote()
        first, upstream, gateway = self.purchase(q["quote_id"])
        self.assertEqual(first["status"], "waiting_payment")
        second, again, create_again = self.purchase(q["quote_id"])
        self.assertEqual(first["payment_url"], second["payment_url"])
        again.assert_not_called(); create_again.assert_called_once()
        self.assertEqual(upstream.call_count, 2)
        gateway.assert_called_once()

    def test_changed_price_never_creates_pending_order(self):
        q = self.quote(); changed = copy.deepcopy(QUOTE); changed["totalAmount"] = 160
        with patch.object(commerce, "request", return_value={"ok": True, "quote": changed}) as upstream:
            with self.assertRaisesRegex(ValueError, "cotacao_mudou"):
                commerce.purchase("tenant", "conversation", self.buyer(q["quote_id"]), self.context)
            upstream.assert_called_once()

    def test_status_returns_current_link_or_expiration_without_creating_order(self):
        import time
        q=self.quote();self.purchase(q['quote_id'])
        with patch.object(commerce_status,'lookup',return_value=None),patch.object(commerce_status,'request') as upstream,patch.object(cielo_checkout,'create_page',return_value='https://current.test/checkout/owned'):
            result=commerce_status.reconcile(q['quote_id'],'tenant','conversation')
            self.assertEqual(result['payment_url'],'https://current.test/checkout/owned')
            with connect() as db:db.execute('UPDATE checkouts SET expires_at=? WHERE id=?',(time.time()-1,q['quote_id']))
            expired=commerce_status.reconcile(q['quote_id'],'tenant','conversation')
            self.assertEqual(expired['status'],'expired');self.assertNotIn('payment_url',expired)
            upstream.assert_not_called()

    def test_existing_order_link_can_change_without_new_order_or_payment(self):
        q = self.quote()
        first, _, _ = self.purchase(q["quote_id"])
        with connect() as db:
            before = load(db, q["quote_id"], "tenant", "conversation")
        context = {**self.context, "channel": "instagram", "whatsapp": None}
        with patch.object(commerce, "request") as upstream, patch.object(cielo_checkout, "create_page",
                return_value="https://new-public.test/checkout/" + q["quote_id"]) as page:
            result = commerce.purchase("tenant", "conversation", self.buyer(q["quote_id"]), context)
        upstream.assert_not_called()
        self.assertEqual(result["order_id"], first["order_id"])
        self.assertTrue(result["payment_url"].startswith("https://new-public.test/"))
        self.assertEqual(page.call_args.args[1]["metadata"]["channel"], "instagram")
        with connect() as db:
            after = load(db, q["quote_id"], "tenant", "conversation")
            self.assertEqual(after["expires_at"], before["expires_at"])
            self.assertEqual(db.execute("SELECT count(*) FROM payment_attempts").fetchone()[0], 0)

    def test_payment_not_available_never_writes_remote(self):
        q = self.quote()
        with patch.object(cielo_checkout, "is_enabled", return_value=False), patch.object(commerce, "request") as upstream:
            result = commerce.purchase("tenant", "conversation", self.buyer(q["quote_id"]), self.context)
            self.assertEqual(result["error"], "checkout_nao_habilitado")
            upstream.assert_not_called()

    def test_model_cannot_invent_buyer_cpf(self):
        q = self.quote()
        with patch.object(commerce, "request") as upstream:
            with self.assertRaisesRegex(ValueError, "cpf_precisa"):
                commerce.purchase("tenant", "conversation", self.buyer(q["quote_id"]), {"whatsapp": "5511964120664"})
            upstream.assert_not_called()

    def test_unknown_gateway_result_cannot_duplicate_checkout(self):
        q = self.quote()
        with patch.object(commerce, "request", side_effect=self.upstream), patch.object(cielo_checkout, "create_page", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                commerce.purchase("tenant", "conversation", self.buyer(q["quote_id"]), self.context)
        result, upstream, gateway = self.purchase(q["quote_id"])
        self.assertEqual(result["status"], "unknown")
        upstream.assert_not_called(); gateway.assert_not_called()

    def raw_payment(self, quote_id, status=2):
        return {"MerchantOrderId": commerce.reference(quote_id)+"A1", "Customer": {"Identity": "52998224725"},
            "Payment": {"Amount": 14000, "PaymentId": "11111111-1111-4111-8111-111111111111", "Status": status,
                "Type": "CreditCard", "CreditCard": {"CardNumber": "4111111111111111", "SecurityCode": "123"}}}

    def attempt(self, quote_id):
        import time
        with connect() as db:
            db.execute("INSERT INTO payment_attempts(checkout_id,number,reference,state,payment_id,created_at) VALUES(?,1,?,'pending',?,?)",(quote_id,commerce.reference(quote_id)+"A1","11111111-1111-4111-8111-111111111111",time.time()))

    def test_only_verified_paid_payment_can_issue_tickets(self):
        from services.rincao import cielo_api
        q = self.quote(); self.purchase(q["quote_id"]); self.attempt(q["quote_id"])
        correct=self.raw_payment(q["quote_id"])
        wrongs=[{**correct,"MerchantOrderId":"other"},{**correct,"Customer":{"Identity":"123"}},
                {**correct,"Payment":{**correct["Payment"],"Amount":100}}]
        for wrong in wrongs:
            with patch.object(cielo_api,"get_payment",return_value=wrong),patch.object(commerce_status,"request") as upstream:
                with self.assertRaises(ValueError):commerce_status.reconcile(q["quote_id"],"tenant","conversation")
                upstream.assert_not_called()
        with patch.object(cielo_api,"get_payment",return_value=self.raw_payment(q["quote_id"],1)),patch.object(commerce_status,"request") as upstream:
            self.assertEqual(commerce_status.reconcile(q["quote_id"],"tenant","conversation")["status"],"not_paid")
            upstream.assert_not_called()
        with patch.object(cielo_api,"get_payment",return_value=correct),patch.object(commerce_status,"request",return_value={"status":"created"}) as upstream:
            self.assertEqual(commerce_status.reconcile(q["quote_id"],"tenant","conversation")["status"],"paid")
            self.assertEqual(upstream.call_args.args[1]["external_reference"],"123")
            self.assertEqual(upstream.call_args.args[1]["metadata"]["payment_method"], "credit_card")
            commerce_status.reconcile(q["quote_id"],"tenant","conversation");upstream.assert_called_once()

    def test_verified_pix_method_is_forwarded_to_external_system(self):
        from services.rincao import cielo_api
        q = self.quote(); self.purchase(q["quote_id"]); self.attempt(q["quote_id"])
        payment = self.raw_payment(q["quote_id"])
        payment["Payment"] = {k: v for k, v in payment["Payment"].items() if k != "CreditCard"}
        payment["Payment"]["Type"] = "Pix"
        with patch.object(cielo_api, "get_payment", return_value=payment), patch.object(
                commerce_status, "request", return_value={"status": "created"}) as upstream:
            commerce_status.reconcile(q["quote_id"], "tenant", "conversation")
            self.assertEqual(upstream.call_args.args[1]["metadata"]["payment_method"], "pix")

    def test_debit_without_bank_authentication_cannot_create_a_charge(self):
        from services.rincao import checkout_payment, cielo_api
        q = self.quote(); self.purchase(q["quote_id"])
        data = checkout_payment.PaymentInput(method="debit", card_number="4111111111111111",
            holder="Teste", expiration="12/2030", security_code="123", brand="Visa")
        with patch.object(cielo_api, "create_payment") as gateway:
            with self.assertRaisesRegex(ValueError, "autenticacao"):
                checkout_payment.submit(q["quote_id"], data)
            gateway.assert_not_called()
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM payment_attempts").fetchone()[0], 0)

    def test_polling_keeps_the_original_pix_code(self):
        from services.rincao.payment_lookup import save_result, latest_attempt
        q = self.quote(); self.purchase(q["quote_id"]); self.attempt(q["quote_id"])
        payment = self.raw_payment(q["quote_id"], 1)
        payment["Payment"]["Type"] = "Pix"
        payment["Payment"]["QrCodeString"] = "PIX-TESTE"
        save_result(q["quote_id"], 1, payment)
        del payment["Payment"]["QrCodeString"]
        save_result(q["quote_id"], 1, payment)
        self.assertEqual(json.loads(latest_attempt(q["quote_id"])["public_data"])["qr_code"], "PIX-TESTE")

    def test_payment_double_click_no_duplicate_no_card_persistence(self):
        from services.rincao import checkout_payment,cielo_api
        q=self.quote();self.purchase(q["quote_id"])
        data=checkout_payment.PaymentInput(method="card",card_number="4111111111111111",holder="Teste",expiration="12/2030",security_code="123",brand="Visa")
        with patch.object(checkout_payment,"request",return_value={"ok":True,"quote":copy.deepcopy(QUOTE)}),patch.object(cielo_api,"create_payment",return_value=self.raw_payment(q["quote_id"],1)) as gateway:
            checkout_payment.submit(q["quote_id"],data);checkout_payment.submit(q["quote_id"],data)
            gateway.assert_called_once();self.assertEqual(gateway.call_args.args[1],14000)
        with connect() as db:
            raw=json.dumps([dict(r) for r in db.execute("SELECT * FROM payment_attempts")])
            self.assertNotIn("4111111111111111",raw);self.assertNotIn("SecurityCode",raw)

    def test_public_page_rejects_csrf_cross_origin_and_never_echoes_card(self):
        from fastapi.testclient import TestClient
        from services.rincao import api,checkout_payment,cielo_api
        q=self.quote();self.purchase(q["quote_id"])
        http=TestClient(api.app);url="/checkout/"+q["quote_id"]
        with patch.dict(os.environ,{"RINCAO_TOOLS_SECRET":"fake","RINCAO_CHECKOUT_PUBLIC_URL":"https://checkout.test"}),patch.object(cielo_api,"create_payment") as gateway:
            page=http.get(url);self.assertEqual(page.status_code,200)
            view=http.get(url+"/state").json();self.assertNotIn("52998224725",json.dumps(view))
            self.assertEqual(http.post(url+"/pay",json={"method":"pix"}).status_code,403)
            body={"method":"card","security_token":view["security_token"],"card_number":"4111111111111111","security_code":"12345"}
            bad=http.post(url+"/pay",json=body);self.assertEqual(bad.status_code,400);self.assertNotIn("4111111111111111",bad.text)
            self.assertEqual(http.post(url+"/pay",json={"method":"pix","security_token":view["security_token"]},headers={"Origin":"https://evil.test"}).status_code,403)
            gateway.assert_not_called()
        http.close()

    def test_simulator_link_stays_local_and_accepts_its_exact_origin(self):
        from fastapi.testclient import TestClient
        from services.rincao import api, checkout_public
        q = self.quote(); self.purchase(q["quote_id"])
        with patch.dict(os.environ, {"RINCAO_CHECKOUT_PUBLIC_URL": "https://public.test",
                "RINCAO_TOOLS_SECRET": "fake",
                "RINCAO_CHECKOUT_SIMULATOR_URL": "http://127.0.0.1:8000"}):
            packet = {"metadata": {"whatsapp_verified": False, "channel": "simulator"}}
            self.assertEqual(cielo_checkout.create_page("ref", packet, q["quote_id"]),
                             "http://127.0.0.1:8000/checkout/" + q["quote_id"])
            packet["metadata"]["whatsapp_verified"] = True
            packet["metadata"]["channel"] = "whatsapp"
            self.assertEqual(cielo_checkout.create_page("ref", packet, q["quote_id"]),
                             "https://public.test/checkout/" + q["quote_id"])
            packet["metadata"] = {"whatsapp_verified": False, "channel": "instagram"}
            self.assertEqual(cielo_checkout.create_page("ref", packet, q["quote_id"]),
                             "https://public.test/checkout/" + q["quote_id"])
            packet["metadata"] = {"whatsapp_verified": False}
            self.assertEqual(cielo_checkout.create_page("ref", packet, q["quote_id"]),
                             "https://public.test/checkout/" + q["quote_id"])
            with TestClient(api.app) as http, patch.object(checkout_public, "submit") as payment:
                url = "/checkout/" + q["quote_id"]
                state = http.get(url + "/state").json()
                body = {"method": "pix", "security_token": state["security_token"]}
                self.assertEqual(http.post(url + "/pay", json=body,
                    headers={"Origin": "http://127.0.0.1:8000"}).status_code, 200)
                payment.assert_called_once()
                self.assertEqual(http.post(url + "/pay", json=body,
                    headers={"Origin": "http://127.0.0.1:8000.evil.test"}).status_code, 403)

    def test_bank_authentication_endpoint_is_scoped_and_does_not_charge(self):
        from fastapi.testclient import TestClient
        from services.rincao import api, checkout_3ds, cielo_api
        q=self.quote();self.purchase(q["quote_id"])
        http=TestClient(api.app);url="/checkout/"+q["quote_id"]
        body={"method":"debit","card_number":"4111111111111111","holder":"Teste",
              "expiration":"12/2030","security_code":"123","brand":"Visa"}
        with patch.dict(os.environ,{"RINCAO_TOOLS_SECRET":"fake"}), patch.object(
                checkout_3ds,"start",return_value={"access_token":"fake-token","proof":"fake-proof"}) as bank, \
                patch.object(cielo_api,"create_payment") as charge:
            self.assertEqual(http.post(url+"/authenticate",json=body).status_code,403)
            bank.assert_not_called()
            body["security_token"]=http.get(url+"/state").json()["security_token"]
            response=http.post(url+"/authenticate",json=body)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["order_reference"],commerce.reference(q["quote_id"])+"A1")
            self.assertNotIn("4111111111111111",response.text)
            charge.assert_not_called()
        http.close()
