"""Vincula o número da Meta ao tenant sem colocar credenciais no repositório."""

import argparse
from sqlalchemy import select
from ..db import Base, Session, engine
from ..models import Tenant
from .models import Channel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--phone-number-id", required=True)
    parser.add_argument("--token-env", default="WHATSAPP_ACCESS_TOKEN")
    args = parser.parse_args()
    if not args.phone_number_id.isdigit():
        parser.error("Use o Phone Number ID numérico exibido pela Meta.")
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if not tenant:
            parser.error("Tenant não encontrado")
        channel = db.get(Channel, args.phone_number_id)
        if channel and channel.tenant_id != tenant.id:
            parser.error("Esse número já pertence a outro tenant; não foi alterado.")
        if not channel:
            db.add(
                Channel(
                    phone_number_id=args.phone_number_id,
                    tenant_id=tenant.id,
                    token_env=args.token_env,
                )
            )
        else:
            channel.token_env = args.token_env
    print("Número vinculado ao tenant informado. Nenhuma credencial foi impressa.")


if __name__ == "__main__":
    main()
