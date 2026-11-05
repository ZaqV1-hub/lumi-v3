"""Comprovação curta para concluir cadastro incompleto pelo WhatsApp comprador."""
import base64
import json
import os
import secrets
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .config import required

AAD = b"lumi-rincao-guest-account-v1"


def issue(packet, order_id):
    if not packet.get("metadata", {}).get("whatsapp_verified"):
        return None
    payload = {"purpose": "guest-account", "cpf": packet["buyer"]["cpf"],
        "phone": packet["buyer"]["phone"], "order_id": str(order_id), "exp": int(time.time()) + 3600}
    key = base64.b64decode(required("RINCAO_GUEST_CLAIM_KEY"), validate=True)
    nonce = secrets.token_bytes(12)
    sealed = AESGCM(key).encrypt(nonce, json.dumps(payload).encode(), AAD)
    return "v1." + base64.urlsafe_b64encode(nonce + sealed).decode().rstrip("=")


def account_link(packet, order_id):
    if os.getenv("RINCAO_GUEST_CLAIM_ENABLED", "false") != "true":
        return None
    token = issue(packet, order_id)
    base = os.getenv("RINCAO_GUEST_ACCOUNT_URL", "")
    if token and base.startswith("https://") and "?" not in base:
        return base + "?claim=" + token
    return None
