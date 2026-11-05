"""Provisionamento local da equipe. Senhas são solicitadas sem eco, nunca por argumento."""
import argparse
import getpass
import secrets
from sqlalchemy import select, delete
from .access import password_hash
from .db import Session
from .models import User, Tenant, LoginSession
from .console_models import ConsoleAccount, ConsoleAudit, RemovedAccess


def provision(email, name, tenant_slug, role, password):
    if role not in {"brevia","admin","leitura"} or len(password)<8:
        raise ValueError("Informe um perfil válido e uma senha de pelo menos oito caracteres")
    with Session.begin() as db:
        tenant=db.scalar(select(Tenant).where(Tenant.slug==tenant_slug))
        if not tenant: raise ValueError("Empresa não cadastrada")
        row=db.scalar(select(User).where(User.email==email.strip().lower()))
        if row and row.tenant_id!=tenant.id:
            raise ValueError("Este login já pertence a outra empresa")
        if not row:
            row=User(tenant_id=tenant.id,email=email.strip().lower(),name=name,salt="",password_hash="")
            db.add(row);db.flush()
        row.name=name;row.salt=secrets.token_hex(16);row.password_hash=password_hash(password,row.salt)
        account=db.get(ConsoleAccount,row.id)
        if not account:account=ConsoleAccount(user_id=row.id);db.add(account)
        account.role=role;account.enabled=True;account.must_change_password=False
        removed=db.get(RemovedAccess,row.id)
        if removed:db.delete(removed)
        db.execute(delete(LoginSession).where(LoginSession.user_id==row.id))
        db.add(ConsoleAudit(actor_id=row.id,tenant_id=tenant.id,action="account.provisioned.local",target=row.id))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email",required=True)
    parser.add_argument("--name",required=True)
    parser.add_argument("--tenant",required=True,help="Slug de uma empresa já cadastrada")
    parser.add_argument("--role",choices=["brevia","admin","leitura"],default="brevia")
    args=parser.parse_args()
    password=getpass.getpass("Senha: ")
    if password!=getpass.getpass("Confirme a senha: "):raise SystemExit("As senhas não conferem")
    try:provision(args.email,args.name,args.tenant,args.role,password)
    except ValueError as error:raise SystemExit(str(error))
    print("Acesso provisionado. Nenhuma senha foi gravada em arquivo ou log.")


if __name__=="__main__":main()
