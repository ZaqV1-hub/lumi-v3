"""Vínculo explícito de perfil ao tenant; tokens permanecem no arquivo privado."""
import argparse
import re
from sqlalchemy import select
from ..db import Base, Session
from ..models import Tenant
from .models import Channel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--token-env", required=True)
    parser.add_argument("--secret-env", default="INSTAGRAM_APP_SECRET")
    args = parser.parse_args()
    if not args.profile_id.isdigit() or not all(re.fullmatch(r"[A-Z][A-Z0-9_]{0,119}", name) for name in (args.token_env, args.secret_env)):
        parser.error("Perfil ou referência de configuração inválidos")
    Base.metadata.create_all(Session.kw["bind"])
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if not tenant:
            parser.error("Tenant não encontrado")
        channel = db.get(Channel, args.profile_id)
        if channel and channel.tenant_id != tenant.id:
            parser.error("Perfil já pertence a outro tenant; vínculo preservado")
        if not channel:
            channel = Channel(profile_id=args.profile_id, tenant_id=tenant.id)
            db.add(channel)
        channel.token_env, channel.secret_env = args.token_env, args.secret_env
    print("Vínculo salvo. A autorização e o webhook da Meta ainda precisam ser validados.")


if __name__ == "__main__":
    main()
