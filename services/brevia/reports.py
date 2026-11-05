"""Consultas prontas. Nenhuma consulta ou permissão vem do modelo."""
import json
import re
import unicodedata
from datetime import datetime, timezone
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from app.models import Contact, Conversation, Feature, Tenant
from app.business_models import Contract, ImportedRecord, Project, ProjectUpdate, ReportGrant, WorkLog
from app.business_views import contract_view, project_view, work_view
from app.tenant_runtime import enabled, listed
from app.conversations import timestamp


def normalized_name(value):
    text = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(re.findall(r"[^\W_]+", "".join(c for c in text if not unicodedata.combining(c))))


def authorized_clients(db, call):
    chat = db.scalar(select(Conversation).where(Conversation.id == call.conversation_id, Conversation.tenant_id == call.tenant_id))
    contact = db.get(Contact, chat.contact_id) if chat else None
    grant = db.get(ReportGrant, (call.tenant_id, call.role))
    if not contact or contact.role != call.role or call.context.get("contact_id") != contact.id or not grant or not grant.enabled:
        raise HTTPException(403, "Consulta não autorizada")
    if grant.scope not in ("all", "own") or not listed(db, call.tenant_id):
        raise HTTPException(403, "Consulta não autorizada")
    query = select(Tenant).order_by(Tenant.name)
    if grant.scope == "own":
        query = query.where(Tenant.id == call.tenant_id)
    allowed = [t for t in db.scalars(query) if listed(db, t.id)]
    name = normalized_name(call.arguments.client or "")
    if name:
        exact = [t for t in allowed if name in (normalized_name(t.name), normalized_name(t.slug), normalized_name(t.id))]
        allowed = exact or [t for t in allowed if name in normalized_name(t.name)
            or (" " + normalized_name(t.name) + " ") in (" " + name + " ")]
        if not allowed:
            raise HTTPException(404, "Cliente não encontrado no escopo autorizado")
    return allowed


def opening_in_period(contract, args):
    if not contract.opening_used_minutes or not contract.opening_as_of:
        return 0, True
    if args.start_date and args.start_date > contract.opening_as_of:
        return 0, True
    if args.end_date and contract.start_date and args.end_date < contract.start_date:
        return 0, True
    if (args.end_date and args.end_date < contract.opening_as_of) or (args.start_date and
            (not contract.start_date or args.start_date > contract.start_date)):
        return 0, False
    return contract.opening_used_minutes, True


def report(db, tenant, args, role):
    projects = list(db.scalars(select(Project).where(Project.tenant_id == tenant.id).order_by(Project.name)))
    contracts = list(db.scalars(select(Contract).where(Contract.tenant_id == tenant.id).order_by(Contract.title)))
    work = list(db.scalars(select(WorkLog).where(WorkLog.tenant_id == tenant.id).order_by(WorkLog.work_date.desc(), WorkLog.created_at.desc())))
    selected = [w for w in work if (not args.start_date or w.work_date >= args.start_date) and (not args.end_date or w.work_date <= args.end_date)]
    usage = {c.id: sum(w.minutes for w in work if w.contract_id == c.id) for c in contracts}
    openings = {c.id: opening_in_period(c, args) for c in contracts}
    updates = list(db.scalars(select(ProjectUpdate).where(ProjectUpdate.tenant_id == tenant.id).order_by(ProjectUpdate.created_at.desc()).limit(20)))
    # Limites explícitos evitam reenviar toda a base a cada pergunta.
    project_rows = [{**project_view(p), "summary": p.summary[:1800], "next_steps": p.next_steps[:1000]} for p in projects[:15]]
    contract_rows = [{**contract_view(c, usage[c.id]), "description": c.description[:1200],
        "period_used_minutes": sum(w.minutes for w in selected if w.contract_id == c.id)+openings[c.id][0],
        "period_complete": openings[c.id][1]} for c in contracts[:20]]
    active = [c for c in contracts if c.status == "ativo"]
    return {"client": {"id": tenant.id, "name": tenant.name}, "projects": project_rows, "contracts": contract_rows,
        "hours": {"active_contracted_minutes": sum(c.included_minutes+c.carried_minutes for c in active),
            "active_used_minutes": sum(usage[c.id]+c.opening_used_minutes for c in active),
            "period_used_minutes": sum(w.minutes for w in selected)+sum(v[0] for v in openings.values()),
            "period_complete": all(v[1] for v in openings.values())},
        "work_logs": [{"contract_id": w.contract_id, "date": w.work_date, "minutes": w.minutes, "description": w.description[:600]} for w in selected[:30]],
        "updates": [{"project_id": u.project_id, "content": u.content[:1000], "created_at": timestamp(u.created_at)} for u in updates[:10]],
        "lumi": {"enabled": enabled(db, tenant.id), "features": list(db.scalars(select(Feature.name).where(
            Feature.tenant_id == tenant.id, Feature.enabled == True)))},
        "truncated": len(projects)>15 or len(contracts)>20 or len(selected)>30 or len(updates)>10,
        "sources": [{"url": r.source_url, "imported_at": timestamp(r.imported_at)} for r in db.scalars(
            select(ImportedRecord).where(ImportedRecord.tenant_id == tenant.id, ImportedRecord.kind.in_(["project", "contract"])).limit(20))],
        "note": "Horas por contrato incluem saldo inicial documentado e lançamentos. Períodos que cortam um saldo inicial consolidado são parciais (period_complete=false): não invente a divisão diária. Fontes do Notion são cópias importadas, não uma consulta ao Notion em tempo real. Não há renovação automática da franquia. Nenhum custo de IA ou conteúdo de conversa é incluído."}


def run(db, call):
    clients = authorized_clients(db, call)
    if len(clients) > 1 and call.arguments.client:
        return {"ok": True, "select_client": [{"id": t.id, "name": t.name} for t in clients],
                "instruction": "Peça para escolher um cliente antes de detalhar o relatório."}
    result = {"ok": True, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "period": {"start_date": call.arguments.start_date, "end_date": call.arguments.end_date},
        "reports": [report(db, t, call.arguments, call.role) for t in clients[:20]], "more_clients": len(clients)>20}
    if len(clients)>1:
        for row in result["reports"]:
            row["work_logs"] = []; row["updates"] = []; row["truncated"] = True
    # O relatório tem orçamento próprio de contexto; totais continuam completos.
    while len(json.dumps(jsonable_encoder(result), ensure_ascii=False).encode()) > 18000:
        rows = [r for r in result["reports"] if any(r[k] for k in ("work_logs", "updates", "projects", "contracts"))]
        if not rows:
            break
        row = max(rows, key=lambda r: len(json.dumps(jsonable_encoder(r), ensure_ascii=False)))
        for key in ("work_logs", "updates", "projects", "contracts"):
            if row[key]:
                row[key].pop(); row["truncated"] = True; break
    return result
