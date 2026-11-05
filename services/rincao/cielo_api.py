"""API E-commerce. Só a página de pagamento envia cartão, nunca a Lumi."""
import json
import os
import urllib.request
import urllib.error
from uuid import UUID
from .cielo_checkout import settings
from .config import required


def call(path, payload=None, query=False):
    settings()
    key = "INGRESSO_CIELO_QUERY_ENDPOINT" if query else "INGRESSO_CIELO_API_ENDPOINT"
    base = required(key).rstrip("/")
    allowed = {"https://api.cieloecommerce.cielo.com.br", "https://apisandbox.cieloecommerce.cielo.com.br"} if not query else {
        "https://apiquery.cieloecommerce.cielo.com.br", "https://apiquerysandbox.cieloecommerce.cielo.com.br"}
    if base not in allowed:
        raise RuntimeError("gateway_endpoint_invalido")
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json",
        "MerchantId": required("INGRESSO_CIELO_MERCHANT_ID"), "MerchantKey": required("INGRESSO_CIELO_MERCHANT_KEY")})
    try:
        with urllib.request.urlopen(req, timeout=min(30, int(os.getenv("INGRESSO_CIELO_TIMEOUT_MS", "30000")) / 1000)) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Não persistir/ecoar resposta do gateway: ela pode conter dados do cartão.
        raise GatewayRejected(exc.code) from None


class GatewayRejected(RuntimeError):
    pass


def get_payment(payment_id):
    UUID(payment_id)
    return call("/1/sales/" + payment_id, query=True)


def find_payments(reference):
    if not reference.isalnum() or len(reference) > 50:
        raise ValueError("referencia_invalida")
    return call("/1/sales?merchantOrderId=" + reference, query=True)


def create_payment(reference, amount, buyer, data, expiration):
    payment = {"Amount": amount, "Type": {"pix": "Pix", "card": "CreditCard", "debit": "DebitCard"}[data.method]}
    if data.method == "pix":
        payment.update({"Provider": os.getenv("INGRESSO_CIELO_PIX_PROVIDER", "Cielo2"),
                        "QrCode": {"Expiration": expiration}})
    elif data.method == "debit":
        if not data.authentication:
            raise ValueError("debito_exige_autenticacao_bancaria")
        auth = data.authentication
        payment.update({"Authenticate": True,
            "DebitCard": {"CardNumber": data.card_number, "Holder": data.holder,
                "ExpirationDate": data.expiration, "SecurityCode": data.security_code, "Brand": data.brand},
            "ExternalAuthentication": {"Cavv": auth.cavv, "Eci": auth.eci, "Version": auth.version,
                "ReferenceId": auth.reference_id, **({"Xid": auth.xid} if auth.xid else {})}})
    else:
        payment.update({"Installments": data.installments, "Capture": True,
            "SoftDescriptor": os.getenv("INGRESSO_CIELO_SOFT_DESCRIPTOR", "RINCAO"),
            "CreditCard": {"CardNumber": data.card_number, "Holder": data.holder,
                "ExpirationDate": data.expiration, "SecurityCode": data.security_code,
                "Brand": data.brand}})
    return call("/1/sales/", {"MerchantOrderId": reference,
        "Customer": {"Name": buyer["name"], "Identity": buyer["cpf"], "IdentityType": "CPF"},
        "Payment": payment})
