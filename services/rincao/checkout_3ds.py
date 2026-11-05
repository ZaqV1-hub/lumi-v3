"""Sessão curta de autenticação bancária, vinculada ao pedido e ao cartão."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.request
from pydantic import BaseModel, ConfigDict, Field
from .config import required
from .cielo_checkout import settings


class Authentication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cavv: str = Field(min_length=8, max_length=256, repr=False)
    eci: str = Field(pattern="^(02|05)$")
    version: str = Field(pattern=r"^2\.[12]\.0$")
    reference_id: str = Field(pattern=r"^[a-fA-F0-9-]{36}$")
    xid: str | None = Field(default=None, max_length=128, repr=False)


def configured():
    settings()
    return all(os.getenv(key, "").strip() for key in (
        "INGRESSO_CIELO_3DS_CLIENT_ID", "INGRESSO_CIELO_3DS_CLIENT_SECRET",
        "INGRESSO_CIELO_3DS_ESTABLISHMENT_CODE", "INGRESSO_CIELO_3DS_MERCHANT_NAME",
        "INGRESSO_CIELO_3DS_MCC")) and environment_matches()


def environment_matches():
    sandbox = "sandbox" in os.getenv("INGRESSO_CIELO_API_ENDPOINT", "")
    return os.getenv("INGRESSO_CIELO_3DS_ENVIRONMENT", "PRD").upper() == ("SDB" if sandbox else "PRD")


def signature(payload):
    return hmac.new(required("RINCAO_TOOLS_SECRET").encode(), payload.encode(), hashlib.sha256).hexdigest()


def card_hash(data):
    value = "|".join([data.card_number or "", data.expiration or "", data.brand or ""])
    return hmac.new(required("RINCAO_TOOLS_SECRET").encode(), value.encode(), hashlib.sha256).hexdigest()


def start(token, data, amount):
    if not configured():
        raise ValueError("debito_temporariamente_indisponivel")
    sandbox = "sandbox" in os.getenv("INGRESSO_CIELO_API_ENDPOINT", "")
    host = "mpisandbox.braspag.com.br" if sandbox else "mpi.braspag.com.br"
    # MPI V2 é a integração por script usada pelo site atual. Token de uso específico 3DS.
    endpoint = os.getenv("INGRESSO_CIELO_3DS_TOKEN_ENDPOINT", "https://" + host + "/api/public/v1/access-token").rstrip("/")
    if endpoint not in {"https://" + host + "/api/public/v1/access-token", "https://" + host + "/v2/auth/token"}:
        raise ValueError("autenticacao_bancaria_indisponivel")
    credentials = required("INGRESSO_CIELO_3DS_CLIENT_ID") + ":" + required("INGRESSO_CIELO_3DS_CLIENT_SECRET")
    body = {"EstablishmentCode": required("INGRESSO_CIELO_3DS_ESTABLISHMENT_CODE"),
            "MerchantName": required("INGRESSO_CIELO_3DS_MERCHANT_NAME"), "MCC": required("INGRESSO_CIELO_3DS_MCC")}
    request = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode()})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        access_token = result["access_token"]
        if not isinstance(access_token, str) or not access_token:
            raise ValueError()
    except Exception:
        raise ValueError("autenticacao_bancaria_indisponivel") from None
    payload = base64.urlsafe_b64encode(json.dumps({"checkout": token, "card": card_hash(data),
        "amount": amount, "exp": time.time() + 300, "nonce": secrets.token_hex(16)}).encode()).decode()
    return {"access_token": access_token, "proof": payload + "." + signature(payload),
            "environment": "SDB" if sandbox else "PRD", "script_url": "https://" + host + "/Scripts/BP.Mpi.3ds20.min.js"}


def validate(token, data, amount):
    if not configured() or not data.authentication or not data.authentication_proof:
        raise ValueError("debito_exige_autenticacao_bancaria")
    if data.installments != 1 or data.brand not in {"Visa", "Master", "Elo"}:
        raise ValueError("debito_invalido")
    try:
        payload, mac = data.authentication_proof.split(".", 1)
        if not hmac.compare_digest(signature(payload), mac):
            raise ValueError()
        proof = json.loads(base64.urlsafe_b64decode(payload))
        if (proof["checkout"] != token or proof["amount"] != amount or proof["exp"] < time.time()
                or proof["exp"] > time.time() + 301 or not hmac.compare_digest(proof["card"], card_hash(data))):
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9+/=]+", data.authentication.cavv):
            raise ValueError()
    except Exception:
        raise ValueError("autenticacao_bancaria_invalida") from None
