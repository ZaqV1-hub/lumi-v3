"""Permissões e contratos são provisionados pelo código, nunca por instruções livres."""
import argparse
import json
import os
import secrets
from pathlib import Path
from dotenv import dotenv_values, set_key
from sqlalchemy import select
from .db import Base, Session, engine
from .models import Feature, Tenant
from .business_models import ReportGrant
from .role_instructions import RoleInstruction, ensure_roles
from .tool_models import ToolContract
from .tenant_runtime import TenantChatPolicy, TenantRuntime
from services.brevia.contracts import CONTRACT


def provision(db, tenant, role, scope, endpoint, secret_key, enable_lumi=False):
    ensure_roles(db)
    row = db.get(RoleInstruction, (tenant.id, role))
    if not row:
        db.add(RoleInstruction(tenant_id=tenant.id, role=role, label=role.capitalize()))
    db.merge(ReportGrant(tenant_id=tenant.id, role=role, scope=scope, enabled=True))
    db.flush()
    roles = ",".join(db.scalars(select(ReportGrant.role).where(ReportGrant.tenant_id == tenant.id, ReportGrant.enabled == True)))
    feature = db.scalar(select(Feature).where(Feature.tenant_id == tenant.id, Feature.name == CONTRACT["name"]))
    if not feature:
        feature = Feature(tenant_id=tenant.id, name=CONTRACT["name"])
        db.add(feature)
    feature.description = CONTRACT["description"]
    feature.endpoint = endpoint.rstrip("/") + CONTRACT["path"]
    feature.roles = roles
    feature.enabled = True
    db.flush()
    db.merge(ToolContract(feature_id=feature.id, parameters_schema=json.dumps(CONTRACT["parameters"], ensure_ascii=False), secret_env=secret_key))
    if enable_lumi:
        state = db.get(TenantRuntime, tenant.id)
        if state:
            state.lumi_enabled = True
        if scope == "all":
            db.merge(TenantChatPolicy(tenant_id=tenant.id, allowed_roles=role))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--role", choices=["gestor", "administrador"], required=True)
    parser.add_argument("--scope", choices=["own", "all"], required=True)
    parser.add_argument("--service", default="http://127.0.0.1:8005")
    parser.add_argument("--enable-lumi", action="store_true")
    args = parser.parse_args()
    private = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi"
    private.mkdir(parents=True, exist_ok=True)
    tools = private / "tools.env"
    config = private / "brevia-tools.env"
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if not tenant:
            parser.error("Tenant não encontrado")
        key = "BREVIA_REPORT_" + tenant.id.replace("-", "_").upper()
        existing = dotenv_values(tools)
        secret = existing.get(key) or secrets.token_urlsafe(40)
        bindings = json.loads(dotenv_values(config).get("BREVIA_TOOLS_BINDINGS") or "{}")
        bindings[tenant.id] = key
        set_key(str(tools), key, secret)
        set_key(str(config), key, secret)
        set_key(str(config), "BREVIA_TOOLS_BINDINGS", json.dumps(bindings))
        provision(db, tenant, args.role, args.scope, args.service, key, args.enable_lumi)
    print("Permissão e contrato registrados. Credenciais preservadas fora do repositório.")


if __name__ == "__main__":
    main()
