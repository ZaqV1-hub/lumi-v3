"""Migração aditiva explícita: configura tenants sem sobrescrever escolhas/chaves."""
import argparse
import re
from sqlalchemy import select
from .db import Session
from .models import Tenant
from .tenant_ai import TenantAI, PROVIDERS


def migrate(provider, model, slug=None):
    if provider not in PROVIDERS or (provider != "demo" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", model)):
        raise ValueError("Informe provider e modelo válidos.")
    with Session.begin() as db:
        # Uma nova tabela; não altera nem recria colunas ou dados existentes.
        TenantAI.__table__.create(db.connection(), checkfirst=True)
        tenants = list(db.scalars(select(Tenant).where(Tenant.slug == slug) if slug else select(Tenant)))
        if slug and not tenants:
            raise ValueError("Tenant não encontrado.")
        added = 0
        for tenant in tenants:
            if not db.get(TenantAI, tenant.id):
                db.add(TenantAI(tenant_id=tenant.id, provider=provider,
                                model="" if provider == "demo" else model, encrypted_api_key=""))
                added += 1
    return added


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    parser.add_argument("--model", default="")
    parser.add_argument("--tenant", help="Slug; omitido configura todos os tenants ainda sem configuração")
    args = parser.parse_args()
    print(f"Configurações criadas: {migrate(args.provider, args.model, args.tenant)}. Credenciais não foram copiadas.")
