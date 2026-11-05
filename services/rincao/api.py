import secrets
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from threading import BoundedSemaphore
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal
from .config import load_config, required
from .contracts import CONTRACTS
from .agenda import query_agenda
from .buffet import query_revenue
from . import commerce_contracts
from .commerce_models import Cart, Buyer, PurchaseStatus
from .commerce import quote_cart, purchase
from .commerce_status import reconcile
from .commerce_worker import watch_payments
from .commerce_store import connect as commerce_db
from .commerce_validation import buyer_validation, invalid_data, BUSINESS_FIELDS
from .checkout_public import router as checkout_router

load_config()


@asynccontextmanager
async def lifespan(_):
    with commerce_db() as db:
        db.execute("UPDATE checkouts SET state='unknown' WHERE state='creating'")
    worker = asyncio.create_task(watch_payments())
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Consultas Rincão", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(checkout_router)
app.add_exception_handler(RequestValidationError, buyer_validation)
slots = BoundedSemaphore(8)


class Dates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date | None = None
    end_date: date | None = None


class RevenueDates(Dates):
    representative: str | None = Field(default=None, min_length=1, max_length=120)
    date_base: str = Field(pattern="^(evento|contrato)$")


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    conversation_id: str
    role: str
    arguments: dict
    context: dict = Field(default_factory=dict)


class AgendaCall(Call):
    arguments: Dates


class RevenueCall(Call):
    arguments: RevenueDates


class CartCall(Call):
    arguments: Cart


class BuyerCall(Call):
    arguments: Buyer


class PurchaseStatusCall(Call):
    arguments: PurchaseStatus


def authorize(call, authorization, roles):
    if not secrets.compare_digest(authorization, "Bearer " + required("RINCAO_TOOLS_SECRET")):
        raise HTTPException(401, "Credencial inválida")
    if call.tenant_id != required("RINCAO_TENANT_ID") or call.role not in roles:
        raise HTTPException(403, "Acesso negado")


def period(arguments, default_days):
    start = arguments.start_date or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    end = arguments.end_date or start + timedelta(days=default_days)
    if end < start or (end - start).days > 366:
        raise HTTPException(422, "Informe um período de até 367 dias, em ordem crescente")
    return start, end


def run(query):
    if not slots.acquire(blocking=False):
        raise HTTPException(503, "Consulta ocupada, tente novamente")
    try:
        return jsonable_encoder(query(), custom_encoder={Decimal: lambda value: format(value, "f")})
    except Exception as exc:
        raise HTTPException(503, "Fonte de dados indisponível") from exc
    finally:
        slots.release()


@app.get("/contracts")
def contracts():
    return CONTRACTS


@app.post("/agenda")
def agenda(call: AgendaCall, authorization: str = Header(default="")):
    authorize(call, authorization, ["cliente", "gestor", "atendente"])
    start, end = period(call.arguments, 90)
    return run(lambda: query_agenda(start, end))


@app.post("/faturamento")
def revenue(call: RevenueCall, authorization: str = Header(default="")):
    authorize(call, authorization, ["gestor"])
    args = call.arguments
    start, end = period(args, 0)
    return run(lambda: query_revenue(start, end, args.date_base, args.representative))


def commerce_result(operation):
    if not slots.acquire(blocking=False):
        return {"ok": False, "error": "sistema_de_compras_ocupado"}
    try:
        return operation()
    except ValueError as exc:
        if str(exc) in BUSINESS_FIELDS:
            return invalid_data([{"field": BUSINESS_FIELDS[str(exc)], "reason": "required"}])
        return {"ok": False, "error": str(exc)}
    except Exception:
        return {"ok": False, "error": "sistema_de_compras_indisponivel"}
    finally:
        slots.release()


@app.post("/commerce/quote")
def commerce_quote(call: CartCall, authorization: str = Header(default="")):
    authorize(call, authorization, ["cliente", "gestor", "atendente"])
    return commerce_result(lambda: quote_cart(call.tenant_id, call.conversation_id, call.arguments, call.context))


@app.post("/commerce/purchase")
def commerce_purchase(call: BuyerCall, authorization: str = Header(default="")):
    authorize(call, authorization, ["cliente", "gestor", "atendente"])
    return commerce_result(lambda: purchase(call.tenant_id, call.conversation_id, call.arguments, call.context))


@app.post("/commerce/status")
def commerce_status(call: PurchaseStatusCall, authorization: str = Header(default="")):
    authorize(call, authorization, ["cliente", "gestor", "atendente"])
    return commerce_result(lambda: reconcile(call.arguments.quote_id, call.tenant_id, call.conversation_id))
