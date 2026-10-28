import json
import secrets
from pathlib import Path
from sqlalchemy import select
from .access import password_hash
from .db import Session
from .models import Tenant, User, KnowledgeItem, Feature


def seed():
    data = json.loads(
        (Path(__file__).resolve().parent.parent / "demo/tenants.json").read_text(
            encoding="utf-8"
        )
    )
    with Session.begin() as db:
        for item in data:
            tenant = db.scalar(select(Tenant).where(Tenant.slug == item["slug"]))
            if not tenant:
                tenant = Tenant(
                    name=item["name"],
                    slug=item["slug"],
                    identity=item["identity"],
                    personality=item["personality"],
                )
                db.add(tenant)
                db.flush()
                db.add(
                    KnowledgeItem(
                        tenant_id=tenant.id,
                        title="Ambiente de teste",
                        content=item["knowledge"],
                    )
                )
            if not db.scalar(select(User).where(User.email == item["email"])):
                salt = secrets.token_hex(16)
                db.add(
                    User(
                        tenant_id=tenant.id,
                        name=item["user"],
                        email=item["email"],
                        salt=salt,
                        password_hash=password_hash("demo1234", salt),
                    )
                )
            if not db.scalar(
                select(Feature).where(
                    Feature.tenant_id == tenant.id, Feature.name == "handover"
                )
            ):
                db.add(
                    Feature(
                        tenant_id=tenant.id,
                        name="handover",
                        description="Solicitar atendimento humano quando o cliente pedir explicitamente.",
                        endpoint="http://127.0.0.1:8001/execute",
                        roles="cliente,gerente,atendente",
                    )
                )
