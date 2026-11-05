"""Ferramenta externa de consulta à gestão Brevia. A Lumi só conhece o contrato HTTP."""
import json
import os
import secrets
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.db import Session
from .contracts import CONTRACT
from .reports import run

load_dotenv(Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "brevia-tools.env")
load_dotenv(Path(os.getenv("LUMI_TOOLS_ENV", str(Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "tools.env"))))
app = FastAPI(title="Gestão Brevia", docs_url=None, redoc_url=None, openapi_url=None)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client: str | None = Field(default=None, max_length=160)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.start_date and self.end_date and (self.end_date < self.start_date or (self.end_date-self.start_date).days > 366):
            raise ValueError("Período inválido; limite de 366 dias")
        return self


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1, max_length=36)
    conversation_id: str = Field(min_length=1, max_length=36)
    role: str = Field(max_length=40)
    arguments: Arguments
    context: dict = Field(default_factory=dict)


@app.get("/contracts")
def contracts():
    return [CONTRACT]


@app.post("/reports/projects")
def projects(call: Call, authorization: str = Header(default="")):
    bindings = json.loads(os.getenv("BREVIA_TOOLS_BINDINGS", "{}"))
    key = bindings.get(call.tenant_id)
    secret = os.getenv(key, "") if isinstance(key, str) else ""
    if not secret or not secrets.compare_digest(authorization, "Bearer " + secret):
        raise HTTPException(403, "Consulta não autorizada")
    with Session() as db:
        return run(db, call)
