"""Importação revisada do Notion: transacional, idempotente e com origem preservada."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from sqlalchemy import select
from .db import Base, Session, engine
from .models import Tenant, User, now
from .business_models import Contract, ImportedRecord, Project, ProjectUpdate, WorkLog
from .business_routes import work_date
from .business_schemas import ContractInput, ProjectInput, UpdateInput, WorkInput


def import_records(db, tid, actor_id, entries):
    counts = {"created": 0, "updated": 0, "unchanged": 0, "conflicts": []}
    models = {"project": (Project, ProjectInput), "contract": (Contract, ContractInput),
              "work": (WorkLog, WorkInput), "update": (ProjectUpdate, UpdateInput)}
    def reference(url, kind):
        row = db.get(ImportedRecord, (tid, url, kind))
        if not row:
            raise ValueError("Referência de importação não encontrada no mesmo cliente")
        return row.record_id
    for entry in entries:
        kind, url = entry["kind"], entry["source_url"]
        if kind not in models or urlsplit(url).scheme != "https" or urlsplit(url).hostname not in ("app.notion.com", "www.notion.so", "notion.so"):
            raise ValueError("Tipo ou origem de importação inválido")
        model, schema = models[kind]
        data = dict(entry["data"])
        if kind == "contract":
            data["project_id"] = reference(entry["project_source"], "project")
        if kind == "work":
            data["contract_id"] = reference(entry["contract_source"], "contract")
        validated = schema.model_validate(data)
        values = validated.model_dump()
        if kind == "update":
            values["project_id"] = reference(entry["project_source"], "project")
        if kind == "work":
            work_date(db.get(Contract, values["contract_id"]), validated)
        serial = json.loads(json.dumps(values, default=str, ensure_ascii=False))
        ref = db.get(ImportedRecord, (tid, url, kind))
        if ref:
            row = db.scalar(select(model).where(model.id == ref.record_id, model.tenant_id == tid))
            if not row:
                raise ValueError("Registro importado não encontrado no cliente")
            current = json.loads(json.dumps({k: getattr(row, k) for k in serial}, default=str, ensure_ascii=False))
            if current != json.loads(ref.snapshot_json):
                counts["conflicts"].append({"kind": kind, "url": url}); continue
            if current == serial:
                counts["unchanged"] += 1; continue
            for key, value in values.items():
                setattr(row, key, value)
            ref.snapshot_json = json.dumps(serial, ensure_ascii=False); ref.imported_at = now()
            counts["updated"] += 1
        else:
            row = model(tenant_id=tid, **values)
            if kind in ("work", "update"):
                row.actor_id = actor_id
            if kind == "update" and entry.get("recorded_at"):
                row.created_at = datetime.fromisoformat(entry["recorded_at"])
            db.add(row); db.flush()
            db.add(ImportedRecord(tenant_id=tid, source_url=url, kind=kind, record_id=row.id,
                snapshot_json=json.dumps(serial, ensure_ascii=False)))
            db.flush(); counts["created"] += 1
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--actor-email", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        actor = db.scalar(select(User).where(User.email == args.actor_email))
        if not tenant or not actor:
            parser.error("Cliente ou responsável não encontrado")
        print(json.dumps(import_records(db, tenant.id, actor.id, data), ensure_ascii=False))


if __name__ == "__main__":
    main()
