import hashlib
import secrets
import time

from fastapi import HTTPException, Request
from sqlalchemy import select

from .db import Session
from .models import LoginSession, User
from .console_models import ConsoleAccount
from .tenant_runtime import listed


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200000).hex()


def authenticated_user(request: Request):
    token = request.cookies.get("lumi_session", "")
    try:
        issued = int(token.split(".")[0])
        if not 0 <= time.time() - issued < 86400:
            raise ValueError()
    except ValueError:
        raise HTTPException(401, "Entre com seu login")
    with Session() as db:
        session = db.get(LoginSession, hashlib.sha256(token.encode()).hexdigest())
        if not session:
            raise HTTPException(401, "Entre com seu login")
        user = db.get(User, session.user_id)
        if not user:
            raise HTTPException(401, "Entre com seu login")
        account = db.get(ConsoleAccount, user.id)
        if account and not account.enabled:
            raise HTTPException(401, "Este acesso está desativado")
        user.console_role = account.role if account else "admin"
        user.must_change_password = bool(account and account.must_change_password)
        db.expunge(user)
        return user


def console_user(request: Request):
    user = authenticated_user(request)
    if user.must_change_password:
        raise HTTPException(403, "Crie sua senha definitiva antes de continuar")
    if user.console_role != "brevia":
        raise HTTPException(403, "Acesso exclusivo da equipe Brevia")
    request.state.console_actor = user.id
    return user


def current_user(request: Request):
    user = authenticated_user(request)
    if user.must_change_password:
        raise HTTPException(403, "Crie sua senha definitiva antes de continuar")
    selected = request.query_params.get("tenant")
    if user.console_role == "brevia":
        from .models import Tenant
        if not selected:
            raise HTTPException(403, "Escolha uma empresa no console")
        with Session() as db:
            if not db.get(Tenant, selected) or not listed(db,selected):
                raise HTTPException(404, "Empresa não encontrada")
        user.tenant_id = selected  # Objeto separado da sessão: não altera o cadastro do operador.
        request.state.console_actor = user.id
        request.state.console_tenant = selected
    elif selected and selected != user.tenant_id:
        raise HTTPException(403, "Este acesso pertence a outra empresa")
    with Session() as db:
        if not listed(db,user.tenant_id):raise HTTPException(403,"Empresa arquivada")
    if user.console_role == "leitura" and request.method not in {"GET", "HEAD", "OPTIONS"}:
        raise HTTPException(403, "Seu acesso é somente de leitura")
    return user
