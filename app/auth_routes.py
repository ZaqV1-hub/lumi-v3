import hashlib
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from .access import current_user, password_hash
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
        token = str(int(time.time())) + "." + secrets.token_urlsafe(32)
        db.add(
            LoginSession(
                token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id
            )
        )
        response.set_cookie(
            "lumi_session", token, httponly=True, samesite="strict", max_age=86400
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
def me(user=Depends(current_user)):
    with Session() as db:
        tenant = db.get(Tenant, user.tenant_id)
        return {"name": user.name, "tenant": tenant.name, "slug": tenant.slug}
