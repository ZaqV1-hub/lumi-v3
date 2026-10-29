"""Carga opcional de objetivos; dados ficam em JSON e no banco, nunca na lógica."""
import argparse
import json
from pathlib import Path
from sqlalchemy import select
from .db import Base, Session, engine
from .models import Tenant
from .onboarding_models import OnboardingObjective
from .onboarding_routes import ObjectiveInput


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    items = [ObjectiveInput(**item) for item in json.loads(Path(args.file).read_text(encoding="utf-8"))]
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if not tenant:
            parser.error("Tenant não encontrado")
        if db.scalar(select(OnboardingObjective).where(OnboardingObjective.tenant_id == tenant.id)):
            parser.error("Já existem objetivos. Edite-os pelo admin; nada foi sobrescrito.")
        for item in items:
            db.add(OnboardingObjective(tenant_id=tenant.id, **item.model_dump()))
    print("Objetivos salvos no banco do tenant.")


if __name__ == "__main__":
    main()
