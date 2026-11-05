import os
import unittest
from datetime import date
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from services.estancia import api


class EstanciaToolsTest(unittest.TestCase):
    def test_other_tenant_and_client_roles_cannot_bypass_service_scope(self):
        with patch.dict(os.environ, {"ESTANCIA_TOOLS_SECRET": "test-secret", "ESTANCIA_TENANT_ID": "estancia"}), patch.object(api, "query_agenda") as query:
            http = TestClient(api.app)
            for tenant, role, auth, status in [("rincao", "cliente", "test-secret", 403), ("estancia", "administrador", "test-secret", 403), ("estancia", "cliente", "wrong", 403)]:
                r = http.post('/agenda', json={"tenant_id": tenant, "role": role, "conversation_id": "c", "arguments": {}}, headers={"Authorization": "Bearer " + auth})
                self.assertEqual(r.status_code, status)
            query.assert_not_called()
            query.return_value = {"items": []}
            r = http.post('/agenda', json={"tenant_id": "estancia", "role": "cliente", "conversation_id": "c", "arguments": {}}, headers={"Authorization": "Bearer test-secret"})
            self.assertEqual(r.status_code, 200)
            query.assert_called_once()
            http.close()

    def test_database_is_read_only_and_prices_are_not_taken_from_legacy_table(self):
        env = {"ESTANCIA_DB_HOST": "localhost", "ESTANCIA_DB_NAME": "estancia", "ESTANCIA_DB_USER": "test", "ESTANCIA_DB_PASSWORD": "test"}
        with patch.dict(os.environ, env), patch.object(api.psycopg, "connect") as connect:
            db = connect.return_value.__enter__.return_value
            db.execute.return_value.fetchall.return_value = [{"date": date(2027, 1, 1), "status": "fec", "type": "padra"}]
            result = api.query_agenda(date(2027, 1, 1), date(2027, 1, 2))
            self.assertIn("default_transaction_read_only=on", connect.call_args.kwargs['options'])
            self.assertFalse(result['prices_available'])
            self.assertEqual(result['items'][0]['status'], 'fechada')
            sql, params = db.execute.call_args.args
            self.assertNotIn('tabpreco', sql)
            self.assertEqual(params, (date(2027, 1, 1), date(2027, 1, 2)))
