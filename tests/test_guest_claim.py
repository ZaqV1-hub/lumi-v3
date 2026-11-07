import base64
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from services.rincao.guest_claim import issue


class GuestClaimTest(unittest.TestCase):
    def test_checkout_offers_site_account_only_after_tickets_are_confirmed(self):
        from services.rincao.checkout_public import view
        packet = {"metadata": {"whatsapp_verified": True},
                  "buyer": {"name": "Teste", "cpf": "52998224725", "phone": "5511999999999"}}
        row = {"quote": json.dumps({"totalAmount": 140}), "packet": json.dumps(packet),
               "order_id": "123", "state": "waiting_payment", "expires_at": 9999999999}
        with patch.dict(os.environ, {"RINCAO_GUEST_CLAIM_ENABLED": "true",
                "RINCAO_GUEST_ACCOUNT_URL": "https://cluberincao.questione.ai/cadastro",
                "RINCAO_GUEST_CLAIM_KEY": base64.b64encode(bytes(range(32))).decode()}), \
                patch("services.rincao.checkout_public.latest_attempt", return_value=None), \
                patch("services.rincao.checkout_public.csrf", return_value="test"):
            self.assertNotIn("account_url", view("test", row))
            row["state"] = "paid"
            self.assertTrue(view("test", row)["account_url"].startswith(
                "https://cluberincao.questione.ai/cadastro?claim=v1."))
            packet["metadata"] = {}
            row["packet"] = json.dumps(packet)
            self.assertIsNone(view("test", row)["account_url"])

    def test_python_token_works_in_node_but_not_tampered_expired_or_wrong_cpf(self):
        key = base64.b64encode(bytes(range(32))).decode()
        packet = {"metadata": {"whatsapp_verified": True},
                  "buyer": {"cpf": "52998224725", "phone": "5511999999999"}}
        with patch.dict(os.environ, {"RINCAO_GUEST_CLAIM_KEY": key}):
            token = issue(packet, "123")
            self.assertIsNone(issue({**packet, "metadata": {}}, "123"))
        self.assertNotIn("52998224725", token)
        module = (Path(__file__).resolve().parent.parent / "integrations/rincao-site/lumi-guest-token.mjs").as_uri()
        script = """import {decodeGuestClaim} from MODULE;
let text=''; for await (const chunk of process.stdin) text+=chunk;
const {token,key}=JSON.parse(text), cpf='52998224725';
console.log(JSON.stringify([
  !!decodeGuestClaim(token,cpf,key),
  !!decodeGuestClaim(token,'12345678909',key),
  !!decodeGuestClaim(token.slice(0,20)+(token[20]==='X'?'Y':'X')+token.slice(21),cpf,key),
  !!decodeGuestClaim(token,cpf,key,Date.now()+3601000),
  !!decodeGuestClaim(token,cpf,Buffer.alloc(32).toString('base64'))
]));""".replace("MODULE", json.dumps(module))
        result = subprocess.run(["node", "--input-type=module", "-e", script],
            input=json.dumps({"token": token, "key": key}), text=True, capture_output=True, timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout), [True, False, False, False, False])
