"""Vocabulário de cada objetivo, configurado no banco por tenant."""
import json
import re
import unicodedata
from sqlalchemy import Boolean, ForeignKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class ObjectiveOptions(Base):
    __tablename__ = "onboarding_objective_options"
    objective_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36))
    choices_json: Mapped[str] = mapped_column(Text, default='[]')
    allow_other: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (ForeignKeyConstraint(['tenant_id','objective_id'],['onboarding_objectives.tenant_id','onboarding_objectives.id']),)


def options(db, tid, oid):
    row=db.get(ObjectiveOptions,oid)
    return {'choices':json.loads(row.choices_json),'allow_other':row.allow_other} if row and row.tenant_id==tid else {'choices':[],'allow_other':False}


def normalized(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c)).split())


def canonical_value(field, value, evidence):
    choices=field.get('choices',[])
    if not choices:
        return value if value.casefold() in evidence.casefold() else ''
    for choice in choices:
        names=[choice['value']]+choice.get('aliases',[])
        if normalized(value) in {normalized(n) for n in names} and any(
            re.search(r'(?<!\w)'+re.escape(normalized(n))+r'(?!\w)',normalized(evidence)) for n in names):
            return choice['value']
    return value if field.get('allow_other') and value.casefold() in evidence.casefold() else ''
