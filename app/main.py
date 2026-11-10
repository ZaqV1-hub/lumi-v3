from contextlib import asynccontextmanager
import asyncio
from hashlib import sha256
from pathlib import Path
import os

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .db import Base, Session
from .seed import seed
from .auth_routes import router as auth_router
from .onboarding_routes import router as onboarding_router
from .admin import router as admin_router
from .client import router as client_router, private_simulator_user
from .images import router as image_router
from .media_models import ContactGate
from .tool_models import ToolContract
from sqlalchemy import update
from .whatsapp import bridge
from .instagram import bridge as instagram_bridge
from .instagram.admin import router as instagram_admin_router
from .whatsapp.config import load_config
from .whatsapp.checkout_proxy import router as checkout_router
from .whatsapp.admin import router as whatsapp_admin_router
from .whatsapp.registration import router as whatsapp_registration_router
from .incoming import router as incoming_router
from .usage_models import ModelCall, ResponseRun
from .usage_routes import router as usage_router
from .console_access import router as console_access_router
from .console_issues import router as console_issues_router
from .console_metrics import router as console_metrics_router
from .console_models import ConsoleAudit
from .business_routes import router as business_router
from .business_chat import router as business_chat_router, guard_chat
from .simulation import router as simulation_router
from .instagram.comment_admin import router as comment_admin_router
from .role_instructions import router as role_instructions_router
from .access import console_user
from .tenant_ai_routes import router as tenant_ai_router
from .whatsapp.calling_admin import router as calling_router
from .whatsapp.calling_reconcile import run_reconciler
from .whatsapp.calling_models import CALLING_TABLES

ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(_):
    load_config()
    active_engine = Session.kw["bind"]
    Base.metadata.create_all(active_engine, tables=[table for table in Base.metadata.sorted_tables if table not in CALLING_TABLES])
    if os.getenv("LUMI_SEED_DEMO", "true").lower() in {"true", "1"}:
        seed()
    with active_engine.begin() as connection:
        connection.execute(update(ContactGate).values(pending=0))
    calling_worker = asyncio.create_task(run_reconciler())
    try:
        yield
    finally:
        calling_worker.cancel()
        try:
            await calling_worker
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Lumi", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(admin_router)
app.include_router(calling_router)
app.include_router(client_router)
app.include_router(image_router)
app.include_router(checkout_router)
app.include_router(whatsapp_admin_router)
app.include_router(whatsapp_registration_router)
app.include_router(instagram_admin_router)
app.include_router(incoming_router)
app.include_router(usage_router)
app.include_router(tenant_ai_router)
app.include_router(console_access_router)
app.include_router(console_issues_router)
app.include_router(console_metrics_router)
app.include_router(business_router)
app.include_router(business_chat_router)
app.include_router(simulation_router)
app.include_router(comment_admin_router)
app.include_router(role_instructions_router)
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.middleware("http")
async def console_audit(request, call_next):
    if os.getenv("LUMI_PRIVATE_SIMULATOR", "false").lower() in {"true", "1"} and request.url.path.startswith("/api/client/"):
        from .models import VisitorSession
        with Session() as db:
            visitor = db.get(VisitorSession, request.url.path.split("/")[3])
            try:
                private_simulator_user(request, visitor.tenant_id if visitor else None)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    denied = guard_chat(request)
    if denied is not None:
        return denied
    response=await call_next(request)
    actor=getattr(request.state,"console_actor",None)
    tid=getattr(request.state,"console_tenant",None)
    if request.url.path.startswith("/api/console/business/clients/"):
        tid=request.path_params.get("tid")
    if actor and response.status_code<400 and (request.method not in {"GET","HEAD","OPTIONS"} or (request.url.path=="/api/me" and tid)):
        with Session.begin() as db:
            db.add(ConsoleAudit(actor_id=actor,tenant_id=tid,
                action="tenant.view" if request.method=="GET" else request.method+" "+request.url.path,
                target=getattr(request.state,"console_target",request.url.path)))
    if request.url.path.startswith("/api/console/"):
        response.headers["Cache-Control"]="no-store"
    return response


@app.get("/")
@app.get("/admin")
def home(request: Request):
    from .access import authenticated_user, current_user
    try:user=authenticated_user(request)
    except HTTPException:return versioned_page("console.html")
    if user.must_change_password:return versioned_page("console.html",authenticated=True)
    if user.console_role=="brevia":
        if request.query_params.get("tenant"):
            current_user(request)
            return versioned_page("admin.html",back=True,authenticated=True)
        return versioned_page("console.html",authenticated=True)
    return versioned_page("admin.html",readonly=user.console_role=="leitura",authenticated=True)


@app.get("/chat/{slug}")
def client_page(slug: str,request: Request):
    from .access import current_user
    if os.getenv("LUMI_PRIVATE_SIMULATOR", "false").lower() in {"true", "1"}:
        from sqlalchemy import select
        from .models import Tenant
        with Session() as db:
            tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
            if not tenant:
                raise HTTPException(404, "Empresa não encontrada")
            try:
                private_simulator_user(request, tenant.id)
            except HTTPException as exc:
                if exc.status_code == 401:
                    return RedirectResponse("/admin", status_code=307)
                raise
    back=False
    if request.query_params.get("tenant"):
        user=current_user(request)
        if user.console_role=="brevia":
            from .models import Tenant
            with Session() as db:
                if db.get(Tenant,user.tenant_id).slug!=slug:raise HTTPException(403,"Empresa diferente da selecionada")
            back=True
    return versioned_page("client.html",back=back)


@app.get("/console")
def console_page():
    return RedirectResponse("/admin",status_code=307)


def versioned_page(filename,back=False,readonly=False,authenticated=False):
    import re
    html = (ROOT / "web" / filename).read_text(encoding="utf-8-sig")
    if authenticated:html=html.replace('<section id="login">','<section id="login" hidden>',1)
    if back:
        html=html.replace('<body>','<body class="operator-workspace"><header id="operatorBar"><a href="/admin#/tenants">Voltar ao console</a></header>',1)
    elif readonly:
        html=html.replace('<body>','<body><div class="readonly-notice">Seu acesso é somente de leitura.</div>',1)
    for asset in set(re.findall(r'"/static/([\w.-]+\.(?:js|css))"',html)):
        revision=sha256((ROOT / "web" / asset).read_bytes()).hexdigest()[:12]
        html=html.replace(f'"/static/{asset}"',f'"/static/{asset}?v={revision}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/whatsapp-setup")
def whatsapp_setup_page():
    return FileResponse(ROOT / "web/whatsapp-setup.html", headers={"Cache-Control": "no-store"})


@app.get("/instagram-setup")
def instagram_setup_page():
    return versioned_page("instagram-setup.html")


@app.get("/whatsapp-activate")
def whatsapp_activate_page():
    return versioned_page("whatsapp-activate.html")


@app.get("/privacy-preview")
def privacy_preview(user=Depends(console_user)):
    return FileResponse(ROOT / "docs" / "privacy-policy-draft.html", headers={"Cache-Control": "no-store"})
