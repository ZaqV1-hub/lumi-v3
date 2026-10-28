"""Serviço falso independente. Não importa nenhum módulo da Lumi."""

import os
import secrets
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Handover de teste")


class Request(BaseModel):
    tenant_id: str
    conversation_id: str
    reason: str


@app.post("/execute")
def execute(data: Request, authorization: str = Header(default="")):
    if not secrets.compare_digest(
        authorization, "Bearer " + os.getenv("HANDOVER_SECRET", "local-demo-handover")
    ):
        raise HTTPException(401, "Credencial inválida")
    return {"accepted": True, "request_id": secrets.token_hex(8)}
