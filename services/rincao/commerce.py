import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone
from .config import required
from .commerce_store import connect, load, unpack
from .commerce_upstream import request
from . import cielo_checkout


def reference(quote_id):
    return "LV3" + hashlib.sha256(quote_id.encode()).hexdigest()[:17]


def public_quote(quote_id, quote):
    ready = cielo_checkout.is_enabled()
    return {"ok": True, "quote_id": quote_id, "currency": "BRL", **quote,
        "checkout_available": ready,
        "next_fields": ["nome do comprador", "CPF", "WhatsApp quando não fornecido pelo canal (Instagram e simulador)"] if ready else [],
        "instruction": ("Este cálculo ainda não é uma compra paga. Cotação é uma etapa interna: não ofereça fazer outra cotação nem repita pedidos de confirmação de escolhas já informadas. Apresente o total com naturalidade e avance somente com as escolhas autorizadas, coletando apenas os dados que faltam. Nunca peça cartão ou senha no chat." if ready else
            "Pode apresentar a cotação, mas o pagamento está temporariamente indisponível. Não peça CPF nem prometa link. Não exponha detalhes técnicos ou IDs internos.")}


def quote_cart(tenant_id, conversation_id, cart, context):
    if not 0 < cart.adults + cart.children + cart.exempt <= 100:
        raise ValueError("quantidade_invalida")
    items = [{"sku": category, "title": label, "quantity": count, "unitPrice": 0,
        "visitDate": cart.visit_date.isoformat(), "ticketType": cart.ticket_type, "ticketCategory": category}
        for category, label, count in [("adult", "Adulto", cart.adults), ("child", "Infantil", cart.children), ("exempt", "Isento", cart.exempt)] if count]
    result = request("quote", {"tenant_id": required("RINCAO_COMMERCE_TENANT_ID"),
        "product_type": "day_use", "currency": "BRL", "external_reference": "lumi-v3-quote", "items": items})
    if not result.get("ok"):
        return {"ok": False, "error": "ingressos_indisponiveis", "reason": result.get("reason")}
    quote_id = secrets.token_urlsafe(32)
    request_id = hashlib.sha256((tenant_id + conversation_id + str(context.get("message_id", quote_id)) + cart.model_dump_json()).encode()).hexdigest()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT id,quote FROM checkouts WHERE request_id=?", (request_id,)).fetchone()
        if old:
            return public_quote(old["id"], json.loads(old["quote"]))
        db.execute("INSERT INTO checkouts(id,tenant_id,conversation_id,expires_at,quote,request_id) VALUES(?,?,?,?,?,?)",
            (quote_id, tenant_id, conversation_id, time.time() + 900, json.dumps(result["quote"]), request_id))
    return public_quote(quote_id, result["quote"])


def purchase(tenant_id, conversation_id, buyer, context):
    # A criação do link não cria transação financeira: pagamento é feito na página.
    if not cielo_checkout.is_enabled():
        return {"ok": False, "error": "checkout_nao_habilitado", "instruction": "O pagamento está indisponível. Não peça CPF para contornar e não prometa link ou compra concluída."}
    evidence = [re.sub(r"[.\-\s]", "", str(text)) for text in context.get("customer_messages", [])]
    if not any(re.search(r"(?<!\d)" + re.escape(buyer.cpf) + r"(?!\d)", text) for text in evidence):
        raise ValueError("cpf_precisa_ser_informado_pelo_comprador")
    phone = re.sub(r"\D", "", context.get("whatsapp") or buyer.phone or "")
    if not 10 <= len(phone) <= 15:
        raise ValueError("whatsapp_necessario")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = load(db, buyer.quote_id, tenant_id, conversation_id)
        if row["packet"] and json.loads(row["packet"])["buyer"]["cpf"] != buyer.cpf:
            raise ValueError("comprador_diferente_da_cotacao")
        if row["state"] == "paid":
            return {"ok": True, "order_id": row["order_id"], "status": "paid"}
        if row["state"] in ("expired", "denied", "cancelled"):
            return {"ok": False, "error": "novo_pedido_necessario", "status": row["state"]}
        if row["payment_url"]:
            packet = json.loads(row["packet"])
            packet.setdefault("metadata", {})["channel"] = context.get("channel")
            url = cielo_checkout.create_page(reference(buyer.quote_id), packet, buyer.quote_id)
            db.execute("UPDATE checkouts SET payment_url=?,packet=? WHERE id=?", (url, json.dumps(packet), buyer.quote_id))
            return {"ok": True, "order_id": row["order_id"], "payment_url": url, "status": row["state"]}
        if row["state"] in ("creating", "unknown"):
            return {"ok": False, "error": "pedido_em_verificacao", "status": row["state"]}
        if row["expires_at"] < time.time():
            raise ValueError("cotacao_expirada")
        quote = unpack(row)
        if cielo_checkout.cents(quote["totalAmount"]) <= 0:
            raise ValueError("pedido_sem_valor_requer_atendimento")
        items = [{"sku": i["sku"], "title": i["title"], "quantity": i["quantity"],
            "unitPrice": i["unit_price"], "visitDate": i["visit_date"],
            "ticketType": i["ticket_type"], "ticketCategory": i["sku"]} for i in quote["items"]]
        fresh = request("quote", {"tenant_id": required("RINCAO_COMMERCE_TENANT_ID"), "product_type": "day_use",
            "currency": "BRL", "external_reference": reference(buyer.quote_id), "items": items})
        if not fresh.get("ok") or fresh["quote"] != quote:
            raise ValueError("cotacao_mudou_consulte_novamente")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        packet = {"event_id": reference(buyer.quote_id) + "pending", "event_type": "checkout.session_created",
            "tenant_id": required("RINCAO_COMMERCE_TENANT_ID"), "checkout_session_id": reference(buyer.quote_id),
            "occurred_at": now, "checkout_expires_at": datetime.fromtimestamp(time.time() + 86400, timezone.utc).isoformat().replace("+00:00", "Z"),
            "buyer": {"name": buyer.name.strip(), "cpf": buyer.cpf, "phone": phone},
            "metadata": {"whatsapp_verified": bool(context.get("whatsapp")), "channel": context.get("channel")},
            "items": items, "snapshot": {"quote": quote}, "external_reference": reference(buyer.quote_id)}
        if buyer.email:
            packet["buyer"]["email"] = buyer.email
        db.execute("UPDATE checkouts SET state='creating',packet=? WHERE id=?", (json.dumps(packet), buyer.quote_id))
    try:
        order = request("pending", packet)
        order_id = str(order["externalOrderId"])
        packet["external_reference"] = order_id
        with connect() as db:
            db.execute("UPDATE checkouts SET order_id=?,packet=? WHERE id=?", (order_id, json.dumps(packet), buyer.quote_id))
        url = cielo_checkout.create_page(reference(buyer.quote_id), packet, buyer.quote_id)
        with connect() as db:
            db.execute("UPDATE checkouts SET state='waiting_payment',payment_url=?,expires_at=? WHERE id=?", (url, time.time() + 1800, buyer.quote_id))
        return {"ok": True, "order_id": order_id, "payment_url": url, "status": "waiting_payment",
            "instruction": "Pedido pendente vinculado ao CPF. Ingressos só serão liberados após pagamento confirmado."}
    except ValueError:
        with connect() as db:
            db.execute("UPDATE checkouts SET state='checkout_unavailable' WHERE id=?", (buyer.quote_id,))
        raise
    except Exception:
        with connect() as db:
            db.execute("UPDATE checkouts SET state='unknown' WHERE id=?", (buyer.quote_id,))
        raise
