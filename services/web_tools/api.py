"""Serviço HTTP externo. Não importa código nem consulta bancos da Lumi."""
import copy
import json
import os
import secrets
import threading
import time
from collections import OrderedDict, defaultdict, deque
from datetime import date, datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .contracts import CONTRACTS
from .search import search
from .weather import forecast

ROOT = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi"
load_dotenv(ROOT / "web-tools.env")
load_dotenv(Path(os.getenv("LUMI_TOOLS_ENV", str(ROOT / "tools.env"))))
app = FastAPI(title="Ferramentas públicas da Lumi", docs_url=None, redoc_url=None)
lock = threading.Lock()
slots = threading.BoundedSemaphore(4)
cache = OrderedDict()
requests = defaultdict(deque)


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=3, max_length=240)


class Weather(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place: str = Field(min_length=2, max_length=120)
    country_code: str | None = Field(default=None, pattern="^[A-Z]{2}$")
    start_date: date
    end_date: date | None = None


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1, max_length=80)
    conversation_id: str = Field(min_length=1, max_length=80)
    role: str
    context: dict = Field(default_factory=dict)


class SearchCall(Call):
    arguments: Search


class WeatherCall(Call):
    arguments: Weather


def authorize(call, authorization):
    bindings = json.loads(os.getenv("WEB_TOOLS_BINDINGS", "{}"))
    key = bindings.get(call.tenant_id)
    secret = os.getenv(key, "") if isinstance(key, str) else ""
    if not secret or not secrets.compare_digest(authorization, "Bearer " + secret):
        raise HTTPException(403, "Acesso negado")
    if call.role not in ("cliente", "gestor", "atendente"):
        raise HTTPException(403, "Papel não autorizado")


def run(call, action, operation):
    key = (call.tenant_id, action, call.arguments.model_dump_json())
    now = time.monotonic()
    with lock:
        recent = requests[call.tenant_id]
        while recent and recent[0] < now - 60: recent.popleft()
        if len(recent) >= 20:
            raise HTTPException(429, "Aguarde para consultar novamente")
        recent.append(now)
        saved = cache.get(key)
        if saved and saved[0] > now:
            result = copy.deepcopy(saved[1]); result["cached"] = True
            return result
    if not slots.acquire(blocking=False):
        raise HTTPException(503, "Consulta ocupada")
    try:
        try:
            result = operation()
        except ValueError as exc:
            error = str(exc)
            result = {"ok": False, "error": error if error in (
                "consulta_contem_dados_pessoais_ou_secretos", "busca_publica_temporariamente_indisponivel",
                "busca_nao_configurada") else "fonte_indisponivel",
                "instruction": "A consulta não pôde ser feita. Informe isso sem inventar resultados e sem enviar dados internos para outro buscador."}
        except Exception:
            result = {"ok": False, "error": "fonte_indisponivel",
                      "instruction": "A fonte não respondeu. Informe indisponibilidade temporária; não invente informação atual."}
        result["fetched_at"] = datetime.now(timezone.utc).isoformat()
        result["cached"] = False
        with lock:
            cache[key] = (now + (600 if result.get("ok") else 30), copy.deepcopy(result))
            cache.move_to_end(key)
            while len(cache) > 128: cache.popitem(last=False)
        return result
    finally:
        slots.release()


@app.get("/contracts")
def contracts():
    return CONTRACTS


@app.post("/search")
def query(call: SearchCall, authorization: str = Header(default="")):
    authorize(call, authorization)
    return run(call, "search", lambda: search(call.arguments.query))


@app.post("/weather")
def weather(call: WeatherCall, authorization: str = Header(default="")):
    authorize(call, authorization)
    return run(call, "weather", lambda: forecast(call.arguments))
