import hashlib
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from .access import authenticated_user, current_user, password_hash
from .console_models import ConsoleAccount
from .models import now
from pydantic import BaseModel, Field
from .tenant_runtime import enabled
from .db import Session
from .models import User, LoginSession, Tenant
from .schemas import Login

router = APIRouter()

@router.post("/api/login")
def login(data: Login, response: Response):
    with Session.begin() as db:
        user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
        if not user or not secrets.compare_digest(
            user.password_hash, password_hash(data.password, user.salt)
        ):
            raise HTTPException(401, "E-mail ou senha inválidos")
        account = db.get(ConsoleAccount, user.id)
        if account and not account.enabled:
            raise HTTPException(401, "E-mail ou senha inválidos")
        if account:
            account.last_login = now()
        token = str(int(time.time())) + "." + secrets.token_urlsafe(32)
        db.add(
            LoginSession(
                token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id
            )
        )
        response.set_cookie(
            "lumi_session", token, httponly=True, samesite="strict", max_age=86400 if data.remember else None
        )
        return {"ok": True}


@router.post("/api/logout")
def logout(request: Request, response: Response):
    with Session.begin() as db:
        row = db.get(
            LoginSession,
            hashlib.sha256(
                request.cookies.get("lumi_session", "").encode()
            ).hexdigest(),
        )
        if row:
            db.delete(row)
    response.delete_cookie("lumi_session")
    return {"ok": True}


@router.get("/api/me")
def me(request: Request, user=Depends(authenticated_user)):
    if request.query_params.get("tenant") and not user.must_change_password:
        user = current_user(request)
    with Session() as db:
        tenant = db.get(Tenant, user.tenant_id)
        return {"name": user.name, "tenant": tenant.name, "tenant_id":tenant.id,
                "slug": tenant.slug, "role": user.console_role,
                "lumi_enabled":enabled(db,tenant.id),
                "must_change_password":user.must_change_password}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


@router.post("/api/password")
def change_password(data: PasswordChange, request: Request, user=Depends(authenticated_user)):
    with Session.begin() as db:
        row = db.get(User, user.id)
        if not secrets.compare_digest(row.password_hash, password_hash(data.current_password, row.salt)):
            raise HTTPException(400, "A senha atual não confere")
        if secrets.compare_digest(data.current_password, data.password):
            raise HTTPException(400, "Escolha uma senha diferente da provisória")
        row.salt = secrets.token_hex(16)
        row.password_hash = password_hash(data.password, row.salt)
        account = db.get(ConsoleAccount, user.id)
        if account: account.must_change_password = False
        current = hashlib.sha256(request.cookies.get("lumi_session", "").encode()).hexdigest()
        for session in db.scalars(select(LoginSession).where(LoginSession.user_id==user.id, LoginSession.token_hash!=current)):
            db.delete(session)
    return {"ok":True}
