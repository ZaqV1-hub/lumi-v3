import os
import unittest
from unittest.mock import patch, AsyncMock
from fastapi.responses import Response
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.whatsapp import checkout_proxy as checkout


class CheckoutBindingsTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(checkout.router)
        self.client = TestClient(app)

    def test_unconfigured_binding_and_invalid_tokens_do_not_request_upstream(self):
        with patch.dict(os.environ, {"LUMI_CHECKOUT_BINDINGS": "{}"}), patch.object(checkout, "forward") as forward:
            self.assertEqual(self.client.get("/checkout/example/" + "x"*43).status_code, 404)
            self.assertEqual(self.client.get("/checkout/example/short/state").status_code, 404)
            forward.assert_not_called()

    def test_binding_does_not_accept_redirect_query_or_embedded_credentials(self):
        import json
        for url in ["http://example.com", "https://user:pass@example.com", "https://example.com?url=other", "https://example.com#fragment"]:
            with patch.dict(os.environ, {"LUMI_CHECKOUT_BINDINGS": json.dumps({"example": url})}):
                with self.assertRaises(Exception): checkout.binding_url("example")

    def test_allowed_binding_has_fixed_destination_and_read_only_assets(self):
        with patch.dict(os.environ, {"LUMI_CHECKOUT_BINDINGS": '{"example":"https://example.com/api/checkout"}'}):
            self.assertEqual(checkout.binding_url("example"), "https://example.com/api/checkout")
            self.assertEqual(self.client.get("/checkout/assets/app.js").status_code, 200)
            self.assertEqual(self.client.get("/checkout/assets/private.env").status_code, 404)

    def test_routes_forward_only_supported_operations_to_fixed_origin(self):
        result = Response(b'{"state":"ready"}', media_type="application/json")
        destination = "https://example.com/api/checkout"
        token = "x" * 43
        with patch.dict(os.environ, {"LUMI_CHECKOUT_BINDINGS": '{"example":"https://example.com/api/checkout"}'}), patch.object(checkout, "forward", new_callable=AsyncMock, return_value=result) as forward:
            self.assertEqual(self.client.get("/checkout/example/" + token).status_code, 200)
            self.assertEqual(forward.call_args.kwargs["base"], destination)
            self.assertEqual(forward.call_args.args[0], "/" + token)
            self.assertEqual(self.client.post("/checkout/example/" + token + "/pay", json={"method":"pix"}).status_code, 200)
            self.assertEqual(forward.call_args.args[0], "/" + token + "/pay")
            forward.reset_mock()
            self.assertEqual(self.client.post("/checkout/example/" + token + "/contracts").status_code, 404)
            forward.assert_not_called()
