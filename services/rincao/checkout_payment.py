import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field
from .config import required
from .commerce_store import connect, unpack
from .commerce_upstream import request
from .commerce import reference
from .cielo_checkout import cents
from . import cielo_api
from .payment_lookup import save_result, latest_attempt
from .checkout_3ds import Authentication, validate as validate_authentication


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: str = Field(pattern="^(pix|card|debit)$")
    installments: int = Field(default=1, ge=1, le=3)
    card_number: str | None = Field(default=None, max_length=23, repr=False)
    holder: str | None = Field(default=None, max_length=120)
    expiration: str | None = Field(default=None, max_length=7)
    security_code: str | None = Field(default=None, max_length=4, repr=False)
    brand: str | None = Field(default=None, max_length=12)
    retry: bool = False
    authentication: Authentication | None = Field(default=None, repr=False)
    authentication_proof: str | None = Field(default=None, max_length=2048, repr=False)


def csrf(token):
    return hmac.new(required("RINCAO_TOOLS_SECRET").encode(), ("checkout:" + token).encode(), hashlib.sha256).hexdigest()


def public_row(token, allow_expired=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,80}", token):
        raise ValueError("link_invalido")
    with connect() as db:
        row = db.execute("SELECT * FROM checkouts WHERE id=?", (token,)).fetchone()
    if not row or not row["order_id"] or not row["packet"]:
        raise ValueError("link_nao_encontrado")
    if not allow_expired and row["state"] != "paid" and row["expires_at"] < time.time():
        raise ValueError("link_expirado")
    return dict(row)


def validate_card(data, total):
    if data.installments > 1 and total // data.installments < int(os.getenv("INGRESSO_CIELO_MIN_INSTALLMENT_VALUE_CENTS", "10000")):
        raise ValueError("parcela_abaixo_do_minimo")
    if data.method not in ("card", "debit"):
        return
    number = re.sub(r"[\s-]", "", data.card_number or "")
    if not number.isdigit() or not 13 <= len(number) <= 19:
        raise ValueError("dados_cartao_invalidos")
    digits = [int(d) for d in number[::-1]]
    if sum(d if i % 2 == 0 else (d * 2 - 9 if d > 4 else d * 2) for i, d in enumerate(digits)) % 10:
        raise ValueError("dados_cartao_invalidos")
    if not re.fullmatch(r"(0[1-9]|1[0-2])/20[0-9]{2}", data.expiration or "") or not re.fullmatch(r"[0-9]{3,4}", data.security_code or ""):
        raise ValueError("dados_cartao_invalidos")
    month, year = map(int, data.expiration.split("/"))
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    if (year, month) < (now.year, now.month) or not data.holder or len(data.holder.strip()) < 2 or data.brand not in {"Visa", "Master", "Amex", "Elo", "Hipercard", "Diners", "Discover", "JCB"}:
        raise ValueError("dados_cartao_invalidos")
    data.card_number = number


def submit(token, data):
    row = public_row(token)
    if row["state"] == "paid":
        return
    total = cents(unpack(row)["totalAmount"])
    validate_card(data, total)
    if data.method == "debit":
        validate_authentication(token, data, total)
    packet = json.loads(row["packet"])
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        last = db.execute("SELECT * FROM payment_attempts WHERE checkout_id=? ORDER BY number DESC LIMIT 1", (token,)).fetchone()
        if last and (last["state"] not in ("denied", "voided", "aborted", "rejected") or not data.retry):
            return
        number = last["number"] + 1 if last else 1
        if number > 5:
            raise ValueError("limite_de_tentativas")
        current = request("quote", {"tenant_id": packet["tenant_id"], "product_type": "day_use", "currency": "BRL",
            "items": packet["items"], "external_reference": packet["external_reference"]})
        if not current.get("ok") or current["quote"] != unpack(row):
            raise ValueError("cotacao_mudou_consulte_novamente")
        provider_reference = reference(token) + "A" + str(number)
        db.execute("INSERT INTO payment_attempts(checkout_id,number,reference,state,created_at) VALUES(?,?,?,'creating',?)",
            (token, number, provider_reference, time.time()))
    try:
        result = cielo_api.create_payment(provider_reference, total, packet["buyer"], data,
            max(60, min(int(os.getenv("INGRESSO_CIELO_PIX_EXPIRATION_SECONDS", "86400")), int(row["expires_at"] - time.time()))))
        save_result(token, number, result)
    except cielo_api.GatewayRejected:
        with connect() as db:
            db.execute("UPDATE payment_attempts SET state='rejected' WHERE checkout_id=? AND number=?", (token, number))
        raise ValueError("pagamento_nao_autorizado") from None
    except Exception:
        with connect() as db:
            db.execute("UPDATE payment_attempts SET state='unknown' WHERE checkout_id=? AND number=?", (token, number))
        raise ValueError("pagamento_em_verificacao_nao_repita") from None
