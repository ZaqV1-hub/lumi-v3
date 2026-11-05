import io
import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.tool_errors import validation_error
from services.rincao import api


class BuyerValidationTest(unittest.TestCase):
    def test_invalid_buyer_fields_are_public_and_never_create_purchase(self):
        http = TestClient(api.app)
        for field, value in [("cpf", "00000000000"), ("name", " "), ("email", "bad-email")]:
            buyer = {"quote_id": "q" * 32, "name": "Teste", "cpf": "52998224725", "phone": None, "email": None}
            buyer[field] = value
            body = {"tenant_id": "test", "conversation_id": "test", "role": "cliente", "arguments": buyer}
            with self.subTest(field=field), patch.object(api, "purchase") as purchase:
                response = http.post("/commerce/purchase", json=body)
                self.assertEqual(response.status_code, 422)
                public = validation_error(io.BytesIO(response.content))
                self.assertEqual(public["data"]["invalid_fields"], [{"field": field, "reason": "invalid"}])
                self.assertNotIn(value, response.text)
                purchase.assert_not_called()
        http.close()

    def test_missing_phone_is_a_field_error(self):
        def operation():
            raise ValueError("whatsapp_necessario")
        self.assertEqual(api.commerce_result(operation)["invalid_fields"], [{"field": "phone", "reason": "required"}])

    def test_untrusted_errors_are_not_forwarded(self):
        for body in [{"detail": "driver password"}, {"error": "dados_invalidos", "invalid_fields": [{"field": "secret=value", "reason": "invalid"}]}]:
            self.assertIsNone(validation_error(io.BytesIO(json.dumps(body).encode())))
