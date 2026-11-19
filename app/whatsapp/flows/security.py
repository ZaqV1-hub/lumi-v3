"""Meta Flows encryption; no plaintext endpoint or unsigned fallback."""
import base64
import hashlib
import hmac
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def signed(raw, signature, secret):
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return bool(secret and signature and hmac.compare_digest(expected, signature))


def decrypt(raw, pem):
    envelope = json.loads(raw)
    decode = lambda name: base64.b64decode(envelope[name], validate=True)
    private = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(private, rsa.RSAPrivateKey):
        raise ValueError("Expected RSA key")
    key = private.decrypt(decode("encrypted_aes_key"), padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    iv = decode("initial_vector")
    if len(key) not in (16, 24, 32) or len(iv) not in (12, 16):
        raise ValueError("Invalid encrypted request")
    data = json.loads(AESGCM(key).decrypt(iv, decode("encrypted_flow_data"), None))
    if not isinstance(data, dict):
        raise ValueError("Invalid Flow request")
    return data, key, iv


def encrypt(data, key, iv):
    flipped = bytes(value ^ 255 for value in iv)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    return base64.b64encode(AESGCM(key).encrypt(flipped, payload, None)).decode()
