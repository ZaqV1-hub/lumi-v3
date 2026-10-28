import hashlib
import secrets
import time

from fastapi import HTTPException, Request
from sqlalchemy import select

from .db import Session
from .models import LoginSession, User


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200000).hex()


def current_user(request: Request):
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
        db.expunge(user)
        return user
