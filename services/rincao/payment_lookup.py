import json
from uuid import UUID
from .commerce_store import connect
from . import cielo_api


def latest_attempt(quote_id):
    with connect() as db:
        row = db.execute("SELECT * FROM payment_attempts WHERE checkout_id=? ORDER BY number DESC LIMIT 1", (quote_id,)).fetchone()
        return dict(row) if row else None


def safe_payment(result):
    payment = result.get("Payment", {})
    payment_id = str(UUID(payment["PaymentId"]))
    data = {"id": payment_id, "reference": result.get("MerchantOrderId"),
        "amount": payment.get("Amount"), "status": payment.get("Status"),
        "cpf": result.get("Customer", {}).get("Identity"), "method": payment.get("Type")}
    # Whitelist: nunca persistir CreditCard, SecurityCode ou resposta bruta.
    if payment.get("Type") == "Pix":
        data["qr_code"] = str(payment.get("QrCodeString") or "")[:4096]
        data["qr_image"] = str(payment.get("QrCodeBase64Image") or payment.get("QrcodeBase64Image") or "")[:300000]
    return data


def save_result(quote_id, number, result):
    data = safe_payment(result)
    state = {2: "paid", 3: "denied", 10: "voided", 11: "refunded", 13: "aborted"}.get(data["status"], "pending")
    public = {k: data[k] for k in ("method", "qr_code", "qr_image") if k in data}
    with connect() as db:
        attempt = db.execute("SELECT reference,public_data FROM payment_attempts WHERE checkout_id=? AND number=?", (quote_id, number)).fetchone()
        row = db.execute("SELECT quote,packet FROM checkouts WHERE id=?", (quote_id,)).fetchone()
        from .cielo_checkout import cents
        packet = json.loads(row["packet"])
        if data["reference"] != attempt["reference"] or data["amount"] != cents(json.loads(row["quote"])["totalAmount"]) or data["cpf"] != packet["buyer"]["cpf"]:
            raise ValueError("pagamento_divergente_do_pedido")
        previous = json.loads(attempt["public_data"] or "{}")
        for field in ("qr_code", "qr_image"):
            if not public.get(field) and previous.get(field):
                public[field] = previous[field]
        db.execute("UPDATE payment_attempts SET state=?,payment_id=?,public_data=? WHERE checkout_id=? AND number=?",
            (state, data["id"], json.dumps(public), quote_id, number))
        db.execute("UPDATE checkouts SET gateway_id=? WHERE id=?", (data["id"], quote_id))
    return data


def lookup(quote_id):
    attempt = latest_attempt(quote_id)
    if not attempt:
        return None
    payment_id = attempt["payment_id"]
    if not payment_id:
        if attempt["state"] not in ("unknown", "creating"):
            return None
        result = cielo_api.find_payments(attempt["reference"])
        ids = result.get("Payments", [])
        if len(ids) != 1:
            return None
        payment_id = ids[0]["PaymentId"]
    return save_result(quote_id, attempt["number"], cielo_api.get_payment(payment_id))
