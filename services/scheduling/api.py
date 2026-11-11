import logging
import secrets
import sqlite3
from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .config import settings
from .contracts import Availability, Proposal, Reference, Participants, Agenda, Description, contracts
from . import engine

app = FastAPI(title="Agendamentos da Lumi", docs_url=None, redoc_url=None)
log = logging.getLogger(__name__)


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1, max_length=80)
    conversation_id: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=40)
    context: dict = Field(default_factory=dict)


class AvailabilityCall(Call):
    arguments: Availability


class ProposalCall(Call):
    arguments: Proposal


class ReferenceCall(Call):
    arguments: Reference

class ParticipantsCall(Call):
    arguments: Participants


class AgendaCall(Call):
    arguments: Agenda

class DescriptionCall(Call):
    arguments: Description


def authorize(call, authorization):
    config = settings().get(call.tenant_id)
    if not config or not secrets.compare_digest(authorization, "Bearer " + config.secret) or call.role not in (config.editor_roles if isinstance(call, (AgendaCall, DescriptionCall)) else config.roles):
        raise HTTPException(403, "Acesso negado")
    return config


def run(call, authorization, operation):
    try:
        config = authorize(call, authorization)
        return operation(config, call)
    except HTTPException:
        raise
    except sqlite3.OperationalError:
        log.warning("scheduling-storage-unavailable")
        return {"ok": False, "error": "agendador_ocupado"}
    except Exception:
        log.warning("scheduling-operation-unavailable")
        return {"ok": False, "error": "agenda_indisponivel"}


@app.exception_handler(RequestValidationError)
async def invalid_request(_request, error):
    # Do not echo names, addresses, credentials, request body or Pydantic input values.
    fields = sorted({str(e["loc"][2]) for e in error.errors() if len(e["loc"]) >= 3 and e["loc"][:2] == ("body", "arguments")})
    return JSONResponse(status_code=422, content={"ok": False, "error": "dados_invalidos",
        "invalid_fields": [{"field": field, "reason": "invalid"} for field in fields if field.isidentifier()]})


@app.get("/contracts")
def discovery():
    roles = sorted({role for config in settings().values() for role in config.roles})
    editors = sorted({role for config in settings().values() for role in config.editor_roles})
    return contracts(roles, editors)


@app.post("/availability")
def availability(call: AvailabilityCall, authorization: str = Header(default="")):
    return run(call, authorization, engine.available)


@app.post("/prepare")
def prepare(call: ProposalCall, authorization: str = Header(default="")):
    return run(call, authorization, engine.prepare)


@app.post("/confirm")
def confirm(call: ReferenceCall, authorization: str = Header(default="")):
    return run(call, authorization, engine.confirm)


@app.post("/status")
def status(call: ReferenceCall, authorization: str = Header(default="")):
    return run(call, authorization, engine.status)


@app.post("/participants")
def participants(call: ParticipantsCall, authorization: str = Header(default="")):
    from .participants import update
    return run(call, authorization, update)


@app.post("/agenda")
def agenda(call: AgendaCall, authorization: str = Header(default="")):
    from .descriptions import agenda as operation
    return run(call, authorization, operation)


@app.post("/description")
def description(call: DescriptionCall, authorization: str = Header(default="")):
    from .descriptions import update
    return run(call, authorization, update)
