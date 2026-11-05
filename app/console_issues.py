from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .access import console_user, current_user
from .db import Session
from .models import Tenant, User, Message, now
from .usage_models import ModelCall
from .whatsapp.models import Outbox
from .console_models import ConsoleIssue, ConsoleIssueNote
from .conversations import timestamp

router = APIRouter()


def detected(db, **values):
    try:
        with db.begin_nested():
            db.add(ConsoleIssue(**values));db.flush()
    except IntegrityError:
        if not db.scalar(select(ConsoleIssue.id).where(ConsoleIssue.source_key==values["source_key"])):
            raise


def sync_issues(db):
    """Falhas observadas, nunca conteúdo, credenciais ou texto bruto de erro."""
    existing = set(db.scalars(select(ConsoleIssue.source_key).where(ConsoleIssue.source_key!=None)))
    failed = db.scalars(select(ModelCall).where(ModelCall.status!="completed", ModelCall.created_at>=now()-timedelta(days=30)))
    for row in failed:
        key = "model:"+row.id
        if key not in existing:
            detected(db,tenant_id=row.tenant_id,title="Falha na resposta da IA",
                description="Uma geração de resposta não foi concluída. Confira o atendimento e a disponibilidade do provider.",
                source="sistema",source_key=key,created_at=row.created_at)
    db.flush()


def issue_data(db, row):
    notes = db.execute(select(ConsoleIssueNote,User.name).join(User,User.id==ConsoleIssueNote.actor_id)
        .where(ConsoleIssueNote.issue_id==row.id).order_by(ConsoleIssueNote.created_at))
    return {"id":row.id,"tenant_id":row.tenant_id,"title":row.title,"description":row.description,
            "priority":row.priority,"status":row.status,"source":row.source,"created_at":timestamp(row.created_at),
            "notes":[{"author":name,"content":note.content,"created_at":timestamp(note.created_at)} for note,name in notes]}


@router.get("/api/console/issues")
def issues(actor=Depends(console_user)):
    with Session.begin() as db:
        sync_issues(db)
        return [issue_data(db,row) for row in db.scalars(select(ConsoleIssue).order_by(ConsoleIssue.created_at.desc()))]


class IssueInput(BaseModel):
    title: str = Field(min_length=1,max_length=160)
    description: str = Field(min_length=1,max_length=4000)
    priority: Literal["alta","media","baixa"] = "media"


class OperatorIssueInput(IssueInput):
    tenant_id: str


def add_issue(db, tid, data, source):
    if not db.get(Tenant,tid): raise HTTPException(404,"Empresa não encontrada")
    row = ConsoleIssue(tenant_id=tid,title=data.title,description=data.description,priority=data.priority,source=source)
    db.add(row);db.flush()
    return issue_data(db,row)


@router.post("/api/console/issues")
def create_issue(data: OperatorIssueInput, request: Request, actor=Depends(console_user)):
    with Session.begin() as db:
        request.state.console_tenant = data.tenant_id
        result=add_issue(db,data.tenant_id,data,"operador")
        request.state.console_target=result["id"]
        return result


@router.post("/api/admin/problems")
def report_issue(data: IssueInput, actor=Depends(current_user)):
    with Session.begin() as db: return add_issue(db,actor.tenant_id,data,"cliente")


class IssueChange(BaseModel):
    status: Literal["aberto","analise","resolvido"]
    note: str = Field(default="",max_length=4000)


@router.put("/api/console/issues/{issue_id}")
def update_issue(issue_id: str, data: IssueChange, request: Request, actor=Depends(console_user)):
    with Session.begin() as db:
        row = db.get(ConsoleIssue,issue_id)
        if not row: raise HTTPException(404,"Problema não encontrado")
        row.status=data.status
        if data.note.strip(): db.add(ConsoleIssueNote(issue_id=issue_id,actor_id=actor.id,content=data.note.strip()))
        request.state.console_tenant=row.tenant_id
    return {"ok":True}
