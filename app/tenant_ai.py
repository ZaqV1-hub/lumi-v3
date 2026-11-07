"""Configuração e credencial de IA vinculadas ao tenant, sem fallback global."""
import json
import os
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, Session

PROVIDERS = {"codex", "codex_gateway", "openai", "demo"}


class TenantAI(Base):
    __tablename__ = "tenant_ai_settings"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100), default="")
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")


@dataclass(frozen=True)
class AIConfig:
    provider: str
    model: str
    api_key: str = field(default="", repr=False)


def cipher():
    try:
        return Fernet(os.environ.get("LUMI_AI_SECRET_KEY", "").encode("ascii"))
    except (ValueError, UnicodeError):
        raise RuntimeError("Configure a chave de criptografia de IA no servidor.") from None


def encrypt_key(tenant_id, key):
    return cipher().encrypt(json.dumps({"tenant_id": tenant_id, "key": key}).encode()).decode()


def decrypt_key(tenant_id, encrypted):
    try:
        value = json.loads(cipher().decrypt(encrypted.encode()))
        if value["tenant_id"] != tenant_id or not isinstance(value["key"], str):
            raise ValueError()
        return value["key"]
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError):
        raise RuntimeError("Não foi possível ler a credencial de IA deste tenant.") from None


def configuration(tenant_id):
    if not tenant_id:
        raise RuntimeError("Tenant obrigatório para selecionar a IA.")
    with Session() as db:
        row = db.get(TenantAI, tenant_id)
        if not row or row.provider not in PROVIDERS or (row.provider != "demo" and not row.model):
            raise RuntimeError("Configure a IA deste tenant no painel.")
        key = decrypt_key(tenant_id, row.encrypted_api_key) if row.provider == "openai" and row.encrypted_api_key else ""
        if row.provider == "openai" and not key:
            raise RuntimeError("Configure a chave OpenAI deste tenant no painel.")
        return AIConfig(row.provider, row.model, key)


def public_configuration(row):
    if not row:
        return {"provider": None, "model": "", "api_key_configured": False, "ready": False}
    ready = row.provider in PROVIDERS and (row.provider == "demo" or bool(row.model))
    if row.provider == "openai":
        try:
            ready = ready and bool(row.encrypted_api_key) and bool(decrypt_key(row.tenant_id, row.encrypted_api_key))
        except RuntimeError:
            ready = False
    if row.provider == "codex_gateway":
        ready = ready and bool(os.getenv("LUMI_CODEX_GATEWAY_URL")) and bool(os.getenv("LUMI_CODEX_GATEWAY_TOKEN"))
    return {"provider": row.provider, "model": row.model,
            "api_key_configured": bool(row.encrypted_api_key), "ready": bool(ready)}
