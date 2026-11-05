"""Serialização compartilhada pelo painel e pelo relatório, sem notas internas."""
from sqlalchemy import select
from .business_models import Contract, ImportedRecord, Project, ProjectUpdate, WorkLog
from .models import User
from .conversations import timestamp


def project_view(row):
    return {k: getattr(row, k) for k in ("id", "tenant_id", "name", "status", "summary", "next_steps", "due_date")}


def contract_view(row, used=0):
    return {**{k: getattr(row, k) for k in ("id", "tenant_id", "project_id", "title", "kind", "status",
        "description", "included_minutes", "carried_minutes", "opening_used_minutes", "opening_as_of", "opening_note", "amount_cents", "start_date", "end_date")},
        "used_minutes": used + row.opening_used_minutes,
        "remaining_minutes": row.included_minutes + row.carried_minutes - row.opening_used_minutes - used}


def work_view(row, actor):
    return {**{k: getattr(row, k) for k in ("id", "contract_id", "work_date", "minutes", "description")}, "actor": actor}


def records(db, tid):
    projects = list(db.scalars(select(Project).where(Project.tenant_id == tid).order_by(Project.created_at.desc())))
    contracts = list(db.scalars(select(Contract).where(Contract.tenant_id == tid).order_by(Contract.title)))
    work = list(db.execute(select(WorkLog, User.name).join(User, User.id == WorkLog.actor_id)
        .where(WorkLog.tenant_id == tid).order_by(WorkLog.work_date.desc(), WorkLog.created_at.desc())))
    used = {c.id: 0 for c in contracts}
    for row, _ in work:
        used[row.contract_id] = used.get(row.contract_id, 0) + row.minutes
    updates = list(db.execute(select(ProjectUpdate, User.name).join(User, User.id == ProjectUpdate.actor_id)
        .where(ProjectUpdate.tenant_id == tid).order_by(ProjectUpdate.created_at.desc()).limit(200)))
    return {"sources": [{"kind": r.kind, "record_id": r.record_id, "url": r.source_url,
                         "imported_at": timestamp(r.imported_at)} for r in db.scalars(select(ImportedRecord).where(ImportedRecord.tenant_id == tid))],
        "projects": [project_view(p) for p in projects],
        "contracts": [contract_view(c, used[c.id]) for c in contracts],
        "work_logs": [work_view(w, actor) for w, actor in work],
        "updates": [{"id": u.id, "project_id": u.project_id, "content": u.content,
                     "actor": actor, "created_at": timestamp(u.created_at)} for u, actor in updates]}
