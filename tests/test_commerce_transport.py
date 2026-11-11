import os
import unittest
from unittest.mock import patch, Mock
from services.rincao.commerce_upstream import request


class CommerceTransportTest(unittest.TestCase):
    def test_local_transport_needs_no_ssh_key_and_preserves_test_guard(self):
        env = {"RINCAO_COMMERCE_TRANSPORT":"local", "RINCAO_COMMERCE_REMOTE_ROOT":"C:/fake/hml",
               "RINCAO_COMMERCE_REMOTE_DEPENDENCIES":"C:/fake/dependencies",
               "RINCAO_COMMERCE_REMOTE_BUILD":"C:/fake/build"}
        with patch.dict(os.environ, env, clear=True), patch("services.rincao.commerce_upstream.subprocess.run", return_value=Mock(returncode=0,stdout=b'{"ok":true}')) as run:
            self.assertEqual(request("quote", {"tenant_id":"fake"}), {"ok":True})
            command=run.call_args.args[0]
            self.assertEqual(command[:2],["node","-e"])
            self.assertIn("test_database_required",command[2])
            self.assertIn("default_transaction_read_only",command[2])

    def test_invalid_transport_does_not_start_process(self):
        env={"RINCAO_COMMERCE_TRANSPORT":"invalid", "RINCAO_COMMERCE_REMOTE_ROOT":"fake",
             "RINCAO_COMMERCE_REMOTE_DEPENDENCIES":"fake", "RINCAO_COMMERCE_REMOTE_BUILD":"fake"}
        with patch.dict(os.environ,env,clear=True), patch("services.rincao.commerce_upstream.subprocess.run") as run:
            with self.assertRaises(RuntimeError):request("quote", {})
            run.assert_not_called()

    def test_hml_handover_preserves_legacy_auth_and_tenant_scope(self):
        from fastapi.testclient import TestClient
        from services.rincao.hml import app
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"RINCAO_TENANT_ID":"a","HANDOVER_SECRET":"fake-handover","RINCAO_COMMERCE_DATA_DIR":folder}):
            http=TestClient(app)
            payload={"tenant_id":"a","conversation_id":"v","reason":"Atendente solicitado"}
            self.assertEqual(http.post("/handover/execute",json=payload).status_code,401)
            payload["tenant_id"]="b"
            self.assertEqual(http.post("/handover/execute",json=payload,headers={"Authorization":"Bearer fake-handover"}).status_code,403)
            payload["tenant_id"]="a"
            self.assertEqual(http.post("/handover/execute",json=payload,headers={"Authorization":"Bearer fake-handover"}).json(),{"accepted":True})

    def test_mounted_search_still_requires_tenant_credential(self):
        from fastapi.testclient import TestClient
        from services.rincao.hml import app
        call={"tenant_id":"other","conversation_id":"fake","role":"cliente","arguments":{"query":"Parque Ibirapuera"}}
        with patch.dict(os.environ,{"WEB_TOOLS_BINDINGS":"{}"}):
            self.assertEqual(TestClient(app).post("/public-tools/search",json=call).status_code,403)
