from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import Base, engine
from .seed import seed
from .auth_routes import router as auth_router
from .onboarding_routes import router as onboarding_router
from .admin import router as admin_router
from .client import router as client_router
from .images import router as image_router
from .media_models import ContactGate
from sqlalchemy import update
from .whatsapp import bridge
from .whatsapp.config import load_config

ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(_):
    load_config()
    Base.metadata.create_all(engine)
    seed()
    with engine.begin() as connection:
        connection.execute(update(ContactGate).values(pending=0))
    yield


app = FastAPI(title="Lumi", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(admin_router)
app.include_router(client_router)
app.include_router(image_router)
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.get("/")
@app.get("/admin")
def home():
    return FileResponse(ROOT / "web/admin.html")


@app.get("/chat/{slug}")
def client_page(slug: str):
    return FileResponse(ROOT / "web/client.html")
