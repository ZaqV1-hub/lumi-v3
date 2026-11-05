import copy
import json
import time
from datetime import datetime, timezone
from .commerce import reference
from .commerce_store import connect, load, unpack
from .commerce_upstream import request
from .guest_claim import account_link
from .payment_lookup import lookup, latest_attempt
from . import cielo_checkout


def reconcile(quote_id, tenant_id, conversation_id):
    with connect() as db:
        row = load(db, quote_id, tenant_id, conversation_id)
    packet = json.loads(row["packet"]) if row["packet"] else None
    if row["state"] == "paid":
        return {"ok": True, "status": "paid", "order_id": row["order_id"],
                "account_url": account_link(packet, row["order_id"])}
    payment = lookup(quote_id)
    if not payment:
        if row["expires_at"] < time.time():
            return {"ok": True, "status": "expired", "order_id": row["order_id"],
                    "instruction": "O prazo deste pedido expirou. Uma nova compra exige nova cotação e escolha da pessoa; não apresente o link antigo como válido."}
        result = {"ok": True, "status": "waiting_payment", "order_id": row["order_id"]}
        if packet and row["payment_url"] and cielo_checkout.is_enabled():
            result["payment_url"] = cielo_checkout.create_page(reference(quote_id), packet, quote_id)
        return result
    if payment["status"] != 2:
        return {"ok": True, "status": "not_paid", "gateway_status": payment["status"], "order_id": row["order_id"]}
    approved = copy.deepcopy(packet)
    approved.pop("checkout_expires_at", None)
    approved["event_type"] = "checkout.payment_approved"
    approved["event_id"] = reference(quote_id) + "paid"
    approved["occurred_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    method = {"Pix": "pix", "CreditCard": "credit_card", "DebitCard": "debit_card"}.get(payment.get("method"))
    if method:
        approved.setdefault("metadata", {})["payment_method"] = method
    approved["payment"] = {"provider": "cielo-ecommerce", "payment_id": payment["id"],
        "status": "approved", "amount": unpack(row)["totalAmount"], "currency": "BRL", "paid_at": approved["occurred_at"]}
    result = request("approved", approved)
    if result.get("status") not in ("created", "already_confirmed"):
        return {"ok": False, "status": "paid_awaiting_review", "order_id": row["order_id"]}
    with connect() as db:
        db.execute("UPDATE checkouts SET state='paid',gateway_id=? WHERE id=?", (payment["id"], quote_id))
    return {"ok": True, "status": "paid", "order_id": row["order_id"],
            "account_url": account_link(packet, row["order_id"]),
            "instruction": "Pagamento verificado na Cielo e ingressos registrados no sistema pelo CPF."}
