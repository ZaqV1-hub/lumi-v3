"""Migração aditiva e ativação por tenant; faça backup antes de executar."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.db import Session
from app.models import Tenant
from app.reply_delivery import ReplyDelivery, ReplyPart

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--tenant", required=True)
parser.add_argument("--max-chars", type=int, default=450)
parser.add_argument("--no-typing", action="store_true")
parser.add_argument("--disable", action="store_true")
args = parser.parse_args()
if not 200 <= args.max_chars <= 1500:
    parser.error("max-chars deve estar entre 200 e 1500")
with Session() as db:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
    if not tenant:
        raise SystemExit("Tenant não encontrado; nenhum cadastro criado")
    tid = tenant.id
# Somente duas tabelas novas. Nenhuma coluna existente é alterada.
for table in (ReplyDelivery.__table__, ReplyPart.__table__):
    table.create(Session.kw["bind"], checkfirst=True)
with Session.begin() as db:
    row = db.get(ReplyDelivery, tid)
    if args.disable:
        if row:
            db.delete(row)
    else:
        db.merge(ReplyDelivery(tenant_id=tid, max_chars=args.max_chars, typing=not args.no_typing))
print("Configuração de entrega atualizada para o tenant informado.")
