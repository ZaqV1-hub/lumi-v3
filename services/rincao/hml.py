"""Entrada do serviço externo de demonstração; mantém o contrato legado do handover."""
import secrets
from fastapi import Header, HTTPException
from pydantic import BaseModel
from .api import app
from .config import required


class Handover(BaseModel):
    tenant_id: str
    conversation_id: str
    reason: str


@app.post("/handover/execute")
def handover(data: Handover, authorization: str = Header(default="")):
    if not secrets.compare_digest(authorization, "Bearer " + required("HANDOVER_SECRET")):
        raise HTTPException(401, "Credencial inválida")
    if data.tenant_id != required("RINCAO_TENANT_ID"):
        raise HTTPException(403, "Acesso negado")
    # A pausa e a fila humana pertencem ao núcleo; este adaptador confirma o recebimento.
    return {"accepted": True}
