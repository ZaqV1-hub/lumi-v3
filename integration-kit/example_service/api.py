"""Exemplo independente: recebe o contrato da Lumi sem importar seu núcleo."""
import os
import secrets
from datetime import date
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()
app = FastAPI(title="Exemplo de integração Lumi", docs_url="/docs")
CONTRACT = {"name": "consultar_disponibilidade_demo", "path": "/availability", "roles": ["cliente", "gestor"],
    "description": "Consultar disponibilidade fictícia de uma visita no ambiente de desenvolvimento. Não registra agendamento nem envia notificações.",
    "parameters": {"type": "object", "properties": {"date": {"type": "string", "format": "date"}},
        "required": ["date"], "additionalProperties": False}}


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1, max_length=80)
    conversation_id: str = Field(min_length=1, max_length=80)
    role: str
    arguments: Arguments
    context: dict = Field(default_factory=dict)


@app.exception_handler(RequestValidationError)
async def invalid_input(request, exc):
    errors = exc.errors()
    if errors and all(tuple(item.get("loc", ())) == ("body", "arguments", "date") for item in errors):
        return JSONResponse(status_code=422, content={"ok": False, "error": "dados_invalidos",
            "invalid_fields": [{"field": "date", "reason": "required" if errors[0]["type"] == "missing" else "invalid"}]})
    return JSONResponse(status_code=422, content={"error": "parametros_invalidos"})


@app.get("/contracts")
def contracts():
    return [CONTRACT]


@app.post("/availability")
def availability(call: Call, authorization: str = Header(default="")):
    expected = os.getenv("SERVICE_SECRET", "")
    if not expected or not secrets.compare_digest(authorization, "Bearer " + expected):
        raise HTTPException(403, "Acesso negado")
    if call.tenant_id != os.getenv("SERVICE_TENANT_ID") or call.role not in CONTRACT["roles"]:
        raise HTTPException(403, "Acesso negado")
    return {"ok": True, "demo": True, "date": call.arguments.date.isoformat(),
        "available_times": ["09:00", "14:00"], "booking_created": False}
