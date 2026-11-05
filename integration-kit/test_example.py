import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from example_service.api import app
from check_service import read_contracts


class IntegrationExampleTest(unittest.TestCase):
    def test_contract_and_authorized_call_without_core_or_ai(self):
        with patch.dict(os.environ, {"SERVICE_SECRET": "test-secret", "SERVICE_TENANT_ID": "tenant-demo"}):
            with TestClient(app) as client:
                contracts = read_contracts(client, "http://testserver")
                self.assertEqual(contracts[0]["name"], "consultar_disponibilidade_demo")
                body = {"tenant_id": "tenant-demo", "conversation_id": "c", "role": "cliente", "arguments": {"date": "2027-01-15"}, "context": {}}
                result = client.post('/availability', json=body, headers={"Authorization": "Bearer test-secret"})
                self.assertEqual(result.status_code, 200)
                self.assertTrue(result.json()["demo"])
                self.assertFalse(result.json()["booking_created"])

    def test_wrong_credential_tenant_role_and_invalid_fields(self):
        with patch.dict(os.environ, {"SERVICE_SECRET": "test-secret", "SERVICE_TENANT_ID": "tenant-demo"}):
            with TestClient(app) as client:
                base = {"tenant_id": "tenant-demo", "conversation_id": "c", "role": "cliente", "arguments": {"date": "2027-01-15"}, "context": {}}
                for changes, key in [({}, "wrong"), ({"tenant_id": "another"}, "test-secret"), ({"role": "administrador"}, "test-secret")]:
                    result = client.post('/availability', json={**base, **changes}, headers={"Authorization": "Bearer " + key})
                    self.assertEqual(result.status_code, 403)
                result = client.post('/availability', json={**base, "arguments": {"date": "invalid-private-value"}}, headers={"Authorization": "Bearer test-secret"})
                self.assertEqual(result.status_code, 422)
                self.assertEqual(result.json()["invalid_fields"], [{"field": "date", "reason": "invalid"}])
                self.assertNotIn("invalid-private-value", result.text)

    def test_contract_cannot_move_call_to_another_origin(self):
        contract = {"name": "tool", "description": "demo", "roles": ["cliente"], "path": "https://other.example/run", "parameters": {"type": "object"}}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[contract]))
        with httpx.Client(transport=transport) as client:
            with self.assertRaises(ValueError):
                read_contracts(client, "http://service.example")
