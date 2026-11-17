"""Explicit, bounded export of new WhatsApp messages and audit events."""
import argparse
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from sqlalchemy import exists, inspect, or_, select

from .analytics_models import AnalyticsActivation, AnalyticsReceipt
from .db import Session, engine as default_engine
from .media_models import ContactGate
from .models import Conversation, FeatureCall, Message, Tenant
from .usage_models import ModelCall
from .whatsapp.models import ArchivedChat, Channel, Chat

MAX_BYTES = 256 * 1024
PART_SIZE = 20000  # Fits Sheets' cell limit even for supplementary Unicode characters.
PUBLIC_ERRORS = {"acesso_negado", "atendimento_alterado", "consulta_indisponivel", "parametros_invalidos",
    "dados_invalidos", "configuracao_invalida", "indisponivel", "ocupado", "horario_indisponivel",
    "nao_encontrado", "resultado_incerto", "catalog_request_not_confirmed", "unavailable"}


@dataclass(frozen=True)
class Config:
    tenant_id: str
    endpoint: str
    secret_env: str
    destination: str

    def validate(self):
        url = urlsplit(self.endpoint)
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.tenant_id)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.destination)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,119}", self.secret_env)
                or len(self.endpoint) > 500 or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path != "/analytics"
                or not (url.scheme == "https" or url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"})):
            raise ValueError("Invalid analytics configuration")
        _ = url.port


def load_config(path):
    with Path(path).open("rb") as source:
        raw = source.read(16385)
    if len(raw) > 16384:
        raise ValueError("Invalid analytics configuration")
    config = Config(**json.loads(raw))
    config.validate()
    return config


def migrate(config, *, engine=default_engine):
    """Add schema before deployment, without enabling any export."""
    config.validate()
    with engine.begin() as connection:
        if engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("Unsupported migration database")
        if connection.scalar(select(Tenant.id).where(Tenant.id == config.tenant_id)) is None:
            raise ValueError("Tenant not found")
        columns = {column["name"] for column in inspect(connection).get_columns("feature_calls")}
        if "created_at" not in columns:
            timestamp = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "TIMESTAMP"
            connection.exec_driver_sql("ALTER TABLE feature_calls ADD COLUMN created_at " + timestamp)
        if "message_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE feature_calls ADD COLUMN message_id VARCHAR(36)")
        for table in (AnalyticsActivation.__table__, AnalyticsReceipt.__table__):
            table.create(connection, checkfirst=True)


def prepare(config, *, engine=default_engine, activated_at=None):
    """Activate new-data export only after the timestamp-aware producers deploy."""
    activated_at = activated_at or datetime.now(timezone.utc)
    if activated_at.tzinfo is None:
        raise ValueError("Activation must include timezone")
    migrate(config, engine=engine)
    with engine.begin() as connection:
        existing = connection.execute(select(AnalyticsActivation.endpoint).where(
            AnalyticsActivation.tenant_id == config.tenant_id,
            AnalyticsActivation.destination == config.destination)).scalar_one_or_none()
        if existing is not None and existing != config.endpoint:
            raise ValueError("Destination is already bound to another endpoint")
        if existing is None:
            connection.execute(AnalyticsActivation.__table__.insert().values(
                tenant_id=config.tenant_id, destination=config.destination,
                endpoint=config.endpoint, activated_at=activated_at.astimezone(timezone.utc)))


def _activation(db, config):
    config.validate()
    row = db.get(AnalyticsActivation, (config.tenant_id, config.destination))
    if row is None or row.endpoint != config.endpoint:
        raise ValueError("Analytics destination is not activated")
    return row.activated_at


def _received(config, kind, source_id):
    return exists(select(AnalyticsReceipt.source_id).where(
        AnalyticsReceipt.tenant_id == config.tenant_id, AnalyticsReceipt.destination == config.destination,
        AnalyticsReceipt.kind == kind, AnalyticsReceipt.source_id == source_id))


def _whatsapp(config):
    current = exists(select(Chat.id).join(Channel, Channel.phone_number_id == Chat.phone_number_id).where(
        Chat.id == Message.conversation_id, Channel.tenant_id == config.tenant_id))
    archived = exists(select(ArchivedChat.id).where(ArchivedChat.id == Message.conversation_id,
                                                  ArchivedChat.tenant_id == config.tenant_id))
    return or_(current, archived)


def _utc(value):
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(timezone.utc).isoformat()


def _base(source, kind, identifier, message_id):
    return {"id": identifier, "kind": kind, "conversation_id": source.conversation_id,
        "message_id": message_id, "occurred_at": _utc(source.created_at), "channel": "whatsapp",
        "sender": "", "content": "", "event_type": "", "operation": "", "status": "",
        "error_code": "", "duration_ms": None, "reference": ""}


def _message_records(source):
    content = source.content
    parts = [content[i:i + PART_SIZE] for i in range(0, len(content), PART_SIZE)] or [""]
    for index, part in enumerate(parts, 1):
        identifier = "message-" + source.id + (f"-part-{index}" if len(parts) > 1 else "")
        yield _base(source, "message", identifier, source.id) | {"sender": source.sender, "content": part}


def _event(source, kind):
    record = _base(source, "event", kind + "-" + source.id, source.message_id)
    try:
        duration = int(source.duration_ms)
        record["duration_ms"] = duration if 0 <= duration <= 86400000 else None
    except (TypeError, ValueError):
        pass
    if kind == "model":
        record.update(event_type="model", operation="inference",
                      status=source.status if source.status in {"completed", "failed"} else "unknown")
        return record
    operation = source.feature if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,80}", source.feature) else "unknown"
    record.update(event_type="tool", operation=operation, status="unknown")
    try:
        result = json.loads(source.result)
        data = result.get("data", result)
        if not isinstance(data, dict):
            return record
        success = data.get("ok", data.get("accepted"))
        code = data.get("error") or (data.get("reason") if success is False else None)
        record["status"] = "completed" if success is True else "failed" if success is False or code else "unknown"
        record["error_code"] = code if code in PUBLIC_ERRORS else "unclassified_error" if code else ""
        booking = data.get("booking", {})
        reference = booking.get("booking_id") if isinstance(booking, dict) else None
        if isinstance(reference, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", reference):
            record["reference"] = reference
    except (ValueError, AttributeError, TypeError):
        pass
    return record


def _key(config, record_id):
    kind, identifier = record_id.split("-", 1)
    return config.tenant_id, config.destination, kind, identifier


def collect(db, config):
    activated_at = _activation(db, config)
    message_filters = (Message.tenant_id == config.tenant_id, Message.created_at >= activated_at, _whatsapp(config))
    busy = exists(select(ContactGate.contact_id).join(Conversation, Conversation.contact_id == ContactGate.contact_id).where(
        Conversation.tenant_id == config.tenant_id, Conversation.id == Message.conversation_id, ContactGate.pending > 0))
    # Admission and pending commit together; received audio in human service is already final.
    sources = [("message", select(Message).where(*message_filters, ~_received(config, "message", Message.id),
                 or_(Message.sender != "cliente", ~busy)).order_by(Message.created_at, Message.id).limit(20))]
    for kind, model in (("tool", FeatureCall), ("model", ModelCall)):
        sources.append((kind, select(model).join(Message, (Message.id == model.message_id)
            & (Message.tenant_id == model.tenant_id) & (Message.conversation_id == model.conversation_id))
            .where(*message_filters, model.tenant_id == config.tenant_id, model.created_at >= activated_at,
                   ~_received(config, kind, model.id)).order_by(model.created_at, model.id).limit(20)))
    candidates = []
    for kind, statement in sources:
        for source in db.scalars(statement):
            for record in _message_records(source) if kind == "message" else [_event(source, kind)]:
                if db.get(AnalyticsReceipt, _key(config, record["id"])) is not None:
                    continue
                candidates.append(record)
    # Merge the oldest records from each source so steady message traffic cannot starve audit events.
    candidates.sort(key=lambda record: (record["occurred_at"], re.sub(r"-part-\d+$", "", record["id"]),
                                        int(record["id"].rsplit("-part-", 1)[1]) if "-part-" in record["id"] else 0))
    records = []
    for record in candidates:
        body = json.dumps({"tenant_id": config.tenant_id, "records": records + [record]}, ensure_ascii=False).encode()
        if len(body) > MAX_BYTES or len(records) == 20:
            break
        records.append(record)
    return records


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def send_batch(config, records):
    config.validate()
    private = Path(os.getenv("LUMI_TOOLS_ENV", str(Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "tools.env")))
    secret = dotenv_values(private).get(config.secret_env) or os.getenv(config.secret_env, "")
    if not isinstance(secret, str) or not 32 <= len(secret) <= 256 or not re.fullmatch(r"[\x21-\x7e]+", secret):
        raise ValueError("Analytics credential is unavailable")
    body = json.dumps({"tenant_id": config.tenant_id, "records": records}, ensure_ascii=False).encode()
    if not records or len(records) > 20 or len(body) > MAX_BYTES:
        raise ValueError("Analytics batch is invalid")
    request = urllib.request.Request(config.endpoint, data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + secret})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=15) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("Analytics acknowledgment is invalid")
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise ValueError("Analytics acknowledgment is invalid")
    return result.get("accepted")


def run(config, *, max_batches=5, send=send_batch):
    if type(max_batches) is not int or not 1 <= max_batches <= 100:
        raise ValueError("Invalid batch limit")
    delivered = 0
    for _ in range(max_batches):
        with Session() as db:
            records = collect(db, config)
        if not records:
            break
        accepted = send(config, records)
        requested = {record["id"] for record in records}
        if (not isinstance(accepted, list) or any(not isinstance(identifier, str) for identifier in accepted)
                or len(accepted) != len(set(accepted)) or not set(accepted) <= requested):
            raise ValueError("Analytics acknowledgment is invalid")
        with Session.begin() as db:
            for identifier in accepted:
                key = _key(config, identifier)
                db.merge(AnalyticsReceipt(tenant_id=key[0], destination=key[1], kind=key[2], source_id=key[3]))
            db.flush()
            for message_id in {record["message_id"] for record in records if record["kind"] == "message"}:
                message = db.scalar(select(Message).where(Message.id == message_id, Message.tenant_id == config.tenant_id))
                if message and all(db.get(AnalyticsReceipt, _key(config, part["id"])) for part in _message_records(message)):
                    db.merge(AnalyticsReceipt(tenant_id=config.tenant_id, destination=config.destination,
                                              kind="message", source_id=message_id))
        delivered += len(accepted)
        if not accepted:
            break
    return {"ok": True, "accepted": delivered}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("migrate", "prepare", "run"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--max-batches", type=int, default=5)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.action == "migrate":
            migrate(config)
            result = {"ok": True, "migrated": True}
        elif args.action == "prepare":
            prepare(config)
            result = {"ok": True, "activated": True}
        else:
            result = run(config, max_batches=args.max_batches)
    except Exception:
        print(json.dumps({"ok": False, "error": "analytics_export_failed"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
