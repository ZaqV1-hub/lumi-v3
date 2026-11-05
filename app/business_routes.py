"""Gestão de clientes exclusiva da equipe Brevia. O cliente consulta via ferramenta."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from .access import console_user
from .db import Session
from .models import Tenant
from .tenant_runtime import listed
from .business_models import ClientProfile, Contract, Project, ProjectUpdate, WorkLog
from .business_schemas import ClientInput, ContractInput, ProjectInput, UpdateInput, WorkInput
from .business_views import records

router = APIRouter(prefix="/api/console/business")


def client(db, tid):
    row = db.get(Tenant, tid)
    if not row or not listed(db, tid):
        raise HTTPException(404, "Cliente não encontrado")
    return row


def owned(db, model, tid, key):
    row = db.scalar(select(model).where(model.id == key, model.tenant_id == tid))
    if not row:
        raise HTTPException(404, "Registro não encontrado neste cliente")
    return row


def assign(row, data):
    for key, value in data.model_dump().items():
        setattr(row, key, value)


def work_date(contract, data):
    if contract.opening_used_minutes and contract.opening_as_of and data.work_date <= contract.opening_as_of:
        raise HTTPException(409, "Esta data já está coberta pelo saldo inicial. Reconcilie o saldo antes de detalhar atividades anteriores.")
    if (contract.start_date and data.work_date < contract.start_date) or (contract.end_date and data.work_date > contract.end_date):
        raise HTTPException(422, "A atividade precisa estar na vigência do contrato")


@router.get("/clients")
def clients(actor=Depends(console_user)):
    with Session() as db:
        return [{"id": t.id, "name": t.name, "slug": t.slug} for t in db.scalars(select(Tenant).order_by(Tenant.name)) if listed(db, t.id)]


@router.get("/clients/{tid}")
def detail(tid: str, actor=Depends(console_user)):
    with Session() as db:
        tenant = client(db, tid)
        profile = db.get(ClientProfile, tid)
        return {"id": tid, "name": tenant.name, "slug": tenant.slug,
            "profile": {k: getattr(profile, k) if profile else "" for k in ("contact_name", "contact_email", "notes")}, **records(db, tid)}


@router.put("/clients/{tid}")
def update_client(tid: str, data: ClientInput, actor=Depends(console_user)):
    with Session.begin() as db:
        client(db, tid)
        row = db.get(ClientProfile, tid)
        if not row:
            row = ClientProfile(tenant_id=tid)
            db.add(row)
        assign(row, data)
    return {"ok": True}


@router.post("/clients/{tid}/projects")
def add_project(tid: str, data: ProjectInput, actor=Depends(console_user)):
    with Session.begin() as db:
        client(db, tid)
        row = Project(tenant_id=tid, **data.model_dump())
        db.add(row); db.flush()
        key = row.id
    return {"id": key}


@router.put("/clients/{tid}/projects/{pid}")
def update_project(tid: str, pid: str, data: ProjectInput, actor=Depends(console_user)):
    with Session.begin() as db:
        client(db, tid)
        assign(owned(db, Project, tid, pid), data)
    return {"ok": True}


@router.post("/clients/{tid}/projects/{pid}/updates")
def add_update(tid: str, pid: str, data: UpdateInput, actor=Depends(console_user)):
    with Session.begin() as db:
        client(db, tid); owned(db, Project, tid, pid)
        row = ProjectUpdate(tenant_id=tid, project_id=pid, actor_id=actor.id, content=data.content)
        db.add(row); db.flush()
        key = row.id
    return {"id": key}


@router.post("/clients/{tid}/contracts")
def add_contract(tid: str, data: ContractInput, actor=Depends(console_user)):
    with Session.begin() as db:
        client(db, tid); owned(db, Project, tid, data.project_id)
        row = Contract(tenant_id=tid, **data.model_dump())
        db.add(row); db.flush()
        key = row.id
    return {"id": key}


@router.put("/clients/{tid}/contracts/{key}")
def update_contract(tid: str, key: str, data: ContractInput, actor=Depends(console_user)):
    with Session.begin() as db:
        client(db, tid); owned(db, Project, tid, data.project_id)
        row = owned(db, Contract, tid, key)
        if row.project_id != data.project_id:
            raise HTTPException(409, "O projeto de um contrato não pode ser transferido; encerre-o e cadastre outro")
        if data.opening_used_minutes and db.scalar(select(WorkLog.id).where(WorkLog.tenant_id == tid,
                WorkLog.contract_id == key, WorkLog.work_date <= data.opening_as_of).limit(1)):
            raise HTTPException(409, "O saldo inicial sobrepõe atividades já detalhadas; reconcilie os registros primeiro")
        assign(row, data)
    return {"ok": True}


@router.post("/clients/{tid}/work-logs")
def add_work(tid: str, data: WorkInput, actor=Depends(console_user)):
    with Session.begin() as db:
        client(db, tid); work_date(owned(db, Contract, tid, data.contract_id), data)
        row = WorkLog(tenant_id=tid, actor_id=actor.id, **data.model_dump())
        db.add(row); db.flush()
        key = row.id
    return {"id": key}


@router.put("/clients/{tid}/work-logs/{key}")
def update_work(tid: str, key: str, data: WorkInput, actor=Depends(console_user)):
    with Session.begin() as db:
        client(db, tid); work_date(owned(db, Contract, tid, data.contract_id), data)
        assign(owned(db, WorkLog, tid, key), data)
    return {"ok": True}
