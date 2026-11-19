"""Exibição do telefone definida por tenant, sem inferir autorização pela conversa."""
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class PhoneVisibility(Base):
    __tablename__ = "tenant_phone_visibility"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="visible")


def phone_mode(db, tid):
    row = db.get(PhoneVisibility, tid)
    if row:
        return row.mode if row.mode in {"visible", "hidden", "consent"} else "hidden"
    # Instalações anteriores conservam a política até configuração explícita.
    from .attendance import AttendancePolicy
    legacy = db.get(AttendancePolicy, tid)
    return "consent" if legacy and legacy.phone_consent else "hidden"
