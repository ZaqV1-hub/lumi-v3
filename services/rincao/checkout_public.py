import hmac
import html
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from .checkout_payment import csrf, public_row, PaymentInput, submit
from .payment_lookup import latest_attempt
from .commerce_status import reconcile
from .cielo_checkout import cents
from .guest_claim import account_link
from . import checkout_3ds

router = APIRouter()
WEB = Path(__file__).with_name("checkout_web")
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' https://mpi.braspag.com.br https://mpisandbox.braspag.com.br https://*.cardinalcommerce.com https://*.cardinaltrusted.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://*.cardinalcommerce.com https://*.cardinaltrusted.com; connect-src 'self' https://mpi.braspag.com.br https://mpisandbox.braspag.com.br https://*.cardinalcommerce.com https://*.cardinaltrusted.com; frame-src https:; frame-ancestors 'none'; base-uri 'none'; form-action 'self' https:"}


@router.get("/checkout/assets/{name}")
def assets(name: str):
    if name not in ("app.js", "app.css", "screen.js", "card-fields.js", "authentication.js", "lg-l.png", "lg-d.png"):
        raise HTTPException(404)
    return FileResponse(WEB / name, headers=HEADERS)


def row_or_error(token, allow_expired=False):
    try:
        return public_row(token, allow_expired=allow_expired)
    except ValueError:
        raise HTTPException(404, "Este link de pagamento não está disponível ou expirou.") from None


def view(token, row):
    quote = json.loads(row["quote"])
    buyer = json.loads(row["packet"])["buyer"]
    last = latest_attempt(token)
    state = "paid" if row["state"] == "paid" else last["state"] if last else "ready"
    data = {"order_id": row["order_id"], "buyer_name": buyer["name"], "cpf_masked": "***.***.***-" + buyer["cpf"][-2:],
        "quote": quote, "state": state, "security_token": csrf(token),
        "max_installments": min(3, max(1, cents(quote["totalAmount"]) // int(os.getenv("INGRESSO_CIELO_MIN_INSTALLMENT_VALUE_CENTS", "10000")))),
        "sandbox": "sandbox" in os.getenv("INGRESSO_CIELO_API_ENDPOINT", "")}
    if last and last["public_data"]:
        data.update(json.loads(last["public_data"]))
    if state == "paid" and row["state"] != "paid":
        data["state"] = "issuing_tickets"
    if row["expires_at"] < time.time() and data["state"] not in ("paid", "issuing_tickets"):
        data["state"] = "expired"
    if row["state"] == "paid":
        data["account_url"] = account_link(json.loads(row["packet"]), row["order_id"])
    data["expires_at"] = row["expires_at"]
    data["debit_available"] = bool(checkout_3ds.configured())
    data["payment_id"] = last["payment_id"] if last else None
    return data


@router.get("/checkout/{token}")
def page(token: str):
    row_or_error(token, allow_expired=True)
    source = (WEB / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(source.replace("__TOKEN__", html.escape(token, quote=True)), headers=HEADERS)


@router.get("/checkout/{token}/state")
def state(token: str):
    row = row_or_error(token, allow_expired=True)
    return JSONResponse(view(token, row), headers=HEADERS)


async def payment_input(token: str, request: Request):
    row_or_error(token)
    origin = request.headers.get("origin")
    bases = [urlsplit(os.getenv(key, "")) for key in
             ("RINCAO_CHECKOUT_PUBLIC_URL", "RINCAO_CHECKOUT_SIMULATOR_URL")]
    origins = {base.scheme + "://" + base.netloc for base in bases if base.scheme and base.netloc}
    if origin and origin not in origins:
        raise HTTPException(403, "Origem inválida")
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise HTTPException(413)
    try:
        body = json.loads(raw)
        if not hmac.compare_digest(str(body.pop("security_token", "")), csrf(token)):
            raise HTTPException(403, "Reabra o link de pagamento")
        return PaymentInput.model_validate(body)
    except HTTPException:
        raise
    except Exception:
        # A validação padrão poderia ecoar PAN/CVV no campo input.
        raise HTTPException(400, "Confira os dados de pagamento.") from None


@router.post("/checkout/{token}/authenticate")
async def authenticate(token: str, request: Request):
    from .checkout_payment import validate_card
    from .commerce import reference
    import asyncio
    data = await payment_input(token, request)
    row = row_or_error(token)
    if row["state"] == "paid" or data.method != "debit" or data.installments != 1 or data.brand not in {"Visa", "Master", "Elo"}:
        raise HTTPException(400, "Confira a opção de pagamento.")
    last = latest_attempt(token)
    if last and last["state"] not in ("denied", "voided", "aborted", "rejected"):
        raise HTTPException(409, "Já existe um pagamento em verificação. Aguarde a confirmação.")
    if last and last["number"] >= 5:
        raise HTTPException(409, "O limite de tentativas foi atingido. Fale com o atendimento.")
    try:
        amount = cents(json.loads(row["quote"])["totalAmount"])
        validate_card(data, amount)
        session = await asyncio.to_thread(checkout_3ds.start, token, data, amount)
        session["order_reference"] = reference(token) + "A" + str(last["number"] + 1 if last else 1)
        return JSONResponse(session, headers=HEADERS)
    except ValueError:
        return JSONResponse({"error": "Não foi possível iniciar a autenticação bancária. Tente novamente ou use Pix."}, status_code=400, headers=HEADERS)


@router.post("/checkout/{token}/pay")
async def pay(token: str, request: Request):
    data = await payment_input(token, request)
    import asyncio
    try:
        await asyncio.to_thread(submit, token, data)
        row = row_or_error(token)
        return JSONResponse(view(token, row), headers=HEADERS)
    except ValueError as exc:
        messages = {"dados_cartao_invalidos": "Confira os dados do cartão.", "parcela_abaixo_do_minimo": "Escolha menos parcelas.",
            "cotacao_mudou_consulte_novamente": "A disponibilidade ou o preço mudou. Peça uma nova cotação à Lumi.",
            "pagamento_nao_autorizado": "Não foi possível autorizar o pagamento. Confira os dados ou escolha outra forma.",
            "debito_exige_autenticacao_bancaria": "Confirme a autenticação do banco para pagar com débito.",
            "autenticacao_bancaria_invalida": "A autenticação do banco expirou ou não corresponde ao cartão. Tente novamente.",
            "debito_invalido": "No débito, use Visa, Mastercard ou Elo, à vista.",
            "pagamento_em_verificacao_nao_repita": "Estamos verificando o pagamento. Aguarde antes de tentar novamente."}
        return JSONResponse({"error": messages.get(str(exc), "Não foi possível concluir. Fale com o atendimento.")}, status_code=409, headers=HEADERS)
