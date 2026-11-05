import io
import json
import os
import time
import unittest
from unittest.mock import patch
from services.rincao import checkout_3ds, cielo_api
from services.rincao.checkout_payment import PaymentInput, validate_card


class DebitTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"RINCAO_TOOLS_SECRET": "fake-secret",
            "INGRESSO_CIELO_API_ENDPOINT": "https://api.cieloecommerce.cielo.com.br/",
            "INGRESSO_CIELO_3DS_CLIENT_ID": "fake-client", "INGRESSO_CIELO_3DS_CLIENT_SECRET": "fake-secret",
            "INGRESSO_CIELO_3DS_ESTABLISHMENT_CODE": "fake-establishment",
            "INGRESSO_CIELO_3DS_MERCHANT_NAME": "fake-store", "INGRESSO_CIELO_3DS_MCC": "5811",
            "INGRESSO_CIELO_3DS_ENVIRONMENT": "PRD"})
        self.env.start()
        self.data = PaymentInput(method="debit", card_number="4111 1111 1111 1111", holder="Teste",
            expiration="12/2030", security_code="123", brand="Visa")
        validate_card(self.data, 200)

    def tearDown(self):
        self.env.stop()

    def authenticated(self):
        with patch.object(checkout_3ds.urllib.request, "urlopen", return_value=io.BytesIO(b'{"access_token":"fake-token"}')):
            session = checkout_3ds.start("checkout-a", self.data, 200)
        self.assertNotIn("4111111111111111", session["proof"])
        self.data.authentication_proof = session["proof"]
        self.data.authentication = checkout_3ds.Authentication(cavv="Y2FyZGluYWw=", eci="05", version="2.2.0",
            reference_id="11111111-1111-4111-8111-111111111111")
        return session

    def test_requires_authentication_bound_to_checkout_card_amount_and_time(self):
        with self.assertRaises(ValueError): checkout_3ds.validate("checkout-a", self.data, 200)
        self.authenticated()
        checkout_3ds.validate("checkout-a", self.data, 200)
        for token, amount in [("checkout-b", 200), ("checkout-a", 300)]:
            with self.assertRaises(ValueError): checkout_3ds.validate(token, self.data, amount)
        with patch.object(checkout_3ds.time, "time", return_value=time.time()+310):
            with self.assertRaises(ValueError): checkout_3ds.validate("checkout-a", self.data, 200)
        self.data.card_number="5555555555554444"
        with self.assertRaises(ValueError): checkout_3ds.validate("checkout-a", self.data, 200)

    def test_debit_payload_never_becomes_credit_or_installments(self):
        self.authenticated()
        with patch.object(cielo_api, "call", return_value={}) as call:
            cielo_api.create_payment("reference", 200, {"name":"Teste", "cpf":"52998224725"}, self.data, 60)
            payment=call.call_args.args[1]["Payment"]
            self.assertEqual(payment["Type"], "DebitCard")
            self.assertTrue(payment["Authenticate"])
            self.assertIn("DebitCard", payment)
            self.assertIn("ExternalAuthentication", payment)
            self.assertNotIn("CreditCard", payment)
            self.assertNotIn("Installments", payment)
        self.data.installments=2
        with self.assertRaises(ValueError): checkout_3ds.validate("checkout-a", self.data, 200)

    def test_environment_mismatch_disables_debit(self):
        with patch.dict(os.environ, {"INGRESSO_CIELO_3DS_ENVIRONMENT":"SDB"}):
            self.assertFalse(checkout_3ds.configured())

    def test_failed_authentication_cannot_supply_success_proof(self):
        with self.assertRaises(ValueError):
            checkout_3ds.Authentication(cavv="Y2FyZGluYWw=", eci="07", version="2.2.0",
                reference_id="11111111-1111-4111-8111-111111111111")
