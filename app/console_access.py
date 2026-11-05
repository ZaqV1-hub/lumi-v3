import re
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .access import console_user, password_hash
from .db import Session
from .models import User, Tenant, LoginSession
from .console_models import ConsoleAccount, RemovedAccess
from .conversations import timestamp
from .tenant_runtime import listed

router = APIRouter(prefix="/api/console")


def account_data(db, row):
    account = db.get(ConsoleAccount, row.id)
    return {"id":row.id, "name":row.name, "email":row.email, "tenant_id":row.tenant_id,
            "role":account.role if account else "admin", "enabled":account.enabled if account else True,
            "removed":bool(db.get(RemovedAccess,row.id)),
            "must_change_password":bool(account and account.must_change_password),
            "last_login":timestamp(account.last_login) if account and account.last_login else None}


@router.get("/users")
def users(tenant: str | None = None, include_removed: bool=False, actor=Depends(console_user)):
    with Session() as db:
        query = select(User).order_by(User.name)
        if tenant: query = query.where(User.tenant_id==tenant)
        if not include_removed: query=query.where(~User.id.in_(select(RemovedAccess.user_id)))
        return [account_data(db, row) for row in db.scalars(query) if listed(db,row.tenant_id)]


class NewAccess(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=5, max_length=180)
    tenant_id: str
    role: Literal["admin", "leitura"] = "admin"


def temporary_password(db, row, account):
    password = secrets.token_urlsafe(12)
    row.salt = secrets.token_hex(16)
    row.password_hash = password_hash(password, row.salt)
    account.must_change_password = True
    for session in db.scalars(select(LoginSession).where(LoginSession.user_id==row.id)):
        db.delete(session)
    return password


@router.post("/users")
def create_user(data: NewAccess, request: Request, response: Response, actor=Depends(console_user)):
    email = data.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or not data.name.strip():
        raise HTTPException(422, "Informe um nome e um e-mail válidos")
    try:
        with Session.begin() as db:
            if not db.get(Tenant, data.tenant_id) or not listed(db,data.tenant_id): raise HTTPException(404, "Empresa não encontrada")
            if db.scalar(select(User).where(User.email==email)): raise HTTPException(409, "Este e-mail já tem acesso")
            row = User(tenant_id=data.tenant_id, name=data.name.strip(), email=email, salt="", password_hash="")
            db.add(row); db.flush()
            account = ConsoleAccount(user_id=row.id, role=data.role)
            db.add(account); db.flush()
            password = temporary_password(db, row, account)
            result = {**account_data(db,row), "temporary_password":password}
            request.state.console_tenant = row.tenant_id
            request.state.console_target = row.id
        response.headers["Cache-Control"] = "no-store"
        return result
    except IntegrityError:
        raise HTTPException(409, "Este e-mail já tem acesso")


class AccessChange(BaseModel):
    role: Literal["admin", "leitura"]
    enabled: bool


def editable(db, user_id):
    row = db.get(User, user_id)
    if not row: raise HTTPException(404, "Acesso não encontrado")
    account = db.get(ConsoleAccount, user_id)
    if account and account.role=="brevia":
        raise HTTPException(403, "A conta da equipe é administrada separadamente")
    if not account:
        account = ConsoleAccount(user_id=user_id)
        db.add(account); db.flush()
    return row, account


@router.put("/users/{user_id}")
def update_user(user_id: str, data: AccessChange, request: Request, actor=Depends(console_user)):
    with Session.begin() as db:
        row, account = editable(db,user_id)
        account.role, account.enabled = data.role, data.enabled
        removed=db.get(RemovedAccess,user_id)
        if removed and data.enabled: db.delete(removed)
        for session in db.scalars(select(LoginSession).where(LoginSession.user_id==user_id)): db.delete(session)
        request.state.console_tenant = row.tenant_id
    return {"ok":True}


@router.delete("/users/{user_id}")
def remove_user(user_id: str, request: Request, actor=Depends(console_user)):
    with Session.begin() as db:
        row,account=editable(db,user_id)
        account.enabled=False
        if not db.get(RemovedAccess,user_id): db.add(RemovedAccess(user_id=user_id))
        for session in db.scalars(select(LoginSession).where(LoginSession.user_id==user_id)): db.delete(session)
        request.state.console_tenant=row.tenant_id
    return {"ok":True}


@router.post("/users/{user_id}/password")
def reset_password(user_id: str, request: Request, response: Response, actor=Depends(console_user)):
    with Session.begin() as db:
        row, account = editable(db,user_id)
        password = temporary_password(db,row,account)
        result = {**account_data(db,row), "temporary_password":password}
        request.state.console_tenant = row.tenant_id
    response.headers["Cache-Control"] = "no-store"
    return result
