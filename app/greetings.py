import re
import unicodedata
from sqlalchemy import String, Text, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class Greeting(Base):
    __tablename__ = "tenant_greetings"
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    __table_args__ = (ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),)


def quick_greeting(db, tenant, contact, text):
    normalized = "".join(
        c
        for c in unicodedata.normalize("NFD", text.casefold())
        if unicodedata.category(c) != "Mn"
    )
    if not re.fullmatch(
        r"\s*(oi|oie|ola|bom dia|boa tarde|boa noite)[!.?\s]*", normalized
    ):
        return None
    configured = db.get(Greeting, tenant.id)
    if not configured or not configured.text.strip():
        return None
    return configured.text.replace("{nome}", contact.name).replace(
        "{empresa}", tenant.name
    )
