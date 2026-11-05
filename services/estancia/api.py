"""Consulta externa da Estância. Banco somente leitura; sem faturamento ou cobrança."""
import os
import secrets
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field

load_dotenv(Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "estancia-tools.env")
app = FastAPI(title="Integração Estância", docs_url=None, redoc_url=None)
CONTRACT = {"name": "consultar_agenda", "path": "/agenda", "roles": ["cliente", "gestor", "atendente"],
    "description": "Consultar datas públicas e disponibilidade da Estância no sistema do próprio tenant. Não inclui passeios escolares privados. Esta consulta não fornece preços de passaportes ou adicionais; não use valores antigos da base como se fossem confirmados. Uma data ausente não significa que o parque está aberto. Não cria reserva ou compra.",
    "parameters": {"type": "object", "properties": {
        "start_date": {"type": ["string", "null"], "format": "date"},
        "end_date": {"type": ["string", "null"], "format": "date"}},
        "required": ["start_date", "end_date"], "additionalProperties": False}}


class Dates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date | None = None
    end_date: date | None = None


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    conversation_id: str
    role: str
    arguments: Dates
    context: dict = Field(default_factory=dict)


def connection():
    return psycopg.connect(host=os.environ["ESTANCIA_DB_HOST"], port=int(os.getenv("ESTANCIA_DB_PORT", "5432")),
            dbname=os.environ["ESTANCIA_DB_NAME"], user=os.environ["ESTANCIA_DB_USER"],
            password=os.environ["ESTANCIA_DB_PASSWORD"], connect_timeout=5,
            sslmode="require" if os.getenv("ESTANCIA_DB_SSL") == "true" else "disable",
            options="-c default_transaction_read_only=on -c statement_timeout=5000", row_factory=dict_row)


def query_agenda(start, end):
    with connection() as db:
        rows = db.execute("SELECT dtagenda AS date, stagenda AS status, tpagenda AS type FROM agenda WHERE dtagenda BETWEEN %s AND %s AND tpagenda IN ('padra','promo') ORDER BY dtagenda,idagenda LIMIT 101", (start, end)).fetchall()
    for row in rows:
        row["status"] = {"abe": "aberta", "fec": "fechada", "lot": "lotada"}.get(row["status"], "desconhecida")
    return {"source": "agenda do site", "items": rows[:100], "truncated": len(rows) > 100,
        "prices_available": False, "scope": "Somente datas públicas; não inclui preços, reservas nem passeios escolares privados."}


@app.get("/contracts")
def contracts():
    return [CONTRACT]


def authorize(call, authorization):
    secret = os.getenv("ESTANCIA_TOOLS_SECRET", "")
    if not secret or not secrets.compare_digest(authorization, "Bearer " + secret):
        raise HTTPException(403, "Acesso negado")
    if call.tenant_id != os.getenv("ESTANCIA_TENANT_ID") or call.role not in CONTRACT["roles"]:
        raise HTTPException(403, "Acesso negado")


@app.post("/agenda")
def agenda(call: Call, authorization: str = Header(default="")):
    authorize(call, authorization)
    start = call.arguments.start_date or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    end = call.arguments.end_date or start + timedelta(days=60)
    if not 0 <= (end-start).days <= 366:
        raise HTTPException(422, "Período inválido")
    try:
        return jsonable_encoder(query_agenda(start, end), custom_encoder={Decimal: str})
    except Exception:
        raise HTTPException(503, "Agenda temporariamente indisponível") from None
