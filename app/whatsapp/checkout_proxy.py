"""Expõe somente a página de pagamento; contratos e admin continuam privados."""
import re
import os
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response

router = APIRouter()
SAFE_HEADERS = {"content-type", "cache-control", "referrer-policy", "x-content-type-options", "content-security-policy"}


async def forward(path, request=None):
    body = bytearray()
    if request:
        async for part in request.stream():
            body.extend(part)
            if len(body) > 8192:
                raise HTTPException(413)
    headers = {key: request.headers[key] for key in ("origin", "content-type") if request and key in request.headers}
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            base = os.getenv("LUMI_CHECKOUT_SERVICE_URL", "http://127.0.0.1:8003").rstrip("/")
            result = await client.request("POST" if request else "GET", base + path,
                content=bytes(body) if request else None, headers=headers)
        return Response(result.content, status_code=result.status_code,
            headers={k: v for k, v in result.headers.items() if k.lower() in SAFE_HEADERS})
    except httpx.HTTPError:
        raise HTTPException(503, "Pagamento temporariamente indisponível") from None


def token_path(token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,80}", token):
        raise HTTPException(404)
    return "/checkout/" + token


@router.get("/checkout/assets/{name}")
async def asset(name: str):
    if name not in ("app.css", "app.js", "screen.js", "card-fields.js", "authentication.js", "lg-l.png", "lg-d.png"):
        raise HTTPException(404)
    return await forward("/checkout/assets/" + name)


@router.get("/checkout/{token}")
async def page(token: str):
    return await forward(token_path(token))


@router.get("/checkout/{token}/state")
async def state(token: str):
    return await forward(token_path(token) + "/state")


@router.post("/checkout/{token}/pay")
async def pay(token: str, request: Request):
    return await forward(token_path(token) + "/pay", request)


@router.post("/checkout/{token}/authenticate")
async def authenticate(token: str, request: Request):
    return await forward(token_path(token) + "/authenticate", request)
