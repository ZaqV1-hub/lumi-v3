"""Registra contratos HTTP revisados, sem carregar código dos serviços."""
import argparse
import json
import urllib.request
from urllib.parse import urljoin, urlsplit
from jsonschema import Draft202012Validator
from sqlalchemy import select
from .db import Session, Base, engine
from .models import Tenant, Feature
from .tool_models import ToolContract


def register(slug, service_url, secret_env):
    with urllib.request.urlopen(service_url.rstrip("/") + "/contracts", timeout=8) as response:
        contracts = json.load(response)
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
        if not tenant:
            raise ValueError("Tenant não encontrado")
        for item in contracts:
            Draft202012Validator.check_schema(item["parameters"])
            endpoint = urljoin(service_url, item["path"])
            origin, target = urlsplit(service_url), urlsplit(endpoint)
            if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
                raise ValueError("Endpoint fora do serviço informado")
            feature = db.scalar(select(Feature).where(Feature.tenant_id == tenant.id, Feature.name == item["name"]))
            if not feature:
                feature = Feature(tenant_id=tenant.id, name=item["name"])
                db.add(feature)
            feature.description = item["description"]
            feature.endpoint = endpoint
            feature.roles = ",".join(item["roles"])
            feature.enabled = True
            db.flush()
            contract = db.get(ToolContract, feature.id)
            if not contract:
                contract = ToolContract(feature_id=feature.id)
                db.add(contract)
            contract.parameters_schema = json.dumps(item["parameters"], ensure_ascii=False)
            contract.secret_env = secret_env


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--secret-env", required=True)
    args = parser.parse_args()
    register(args.tenant, args.service, args.secret_env)
    print("Contratos salvos no banco.")
