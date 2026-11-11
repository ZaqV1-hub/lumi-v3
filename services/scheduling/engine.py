"""Disponibilidade, proposta e gravação idempotente; sem lógica de respostas ao cliente."""
import hashlib
import json
import logging
import secrets
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from . import store
from .google import GoogleCalendar, public_event

log = logging.getLogger(__name__)


def clock():
    return datetime.now(timezone.utc)


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class DemoCalendar:
    def busy(self, start, end):
        return []  # Local bookings are checked transactionally in the service database.

    def create(self, booking):
        return {"id": booking["event"], "status": "confirmed",
                "extendedProperties": {"private": {"lumi_booking": booking["id"]}}}

    def get(self, event_id):
        return None


def provider(config):
    return GoogleCalendar(config) if config.mode == "google" else DemoCalendar()


def result(config, booking, data=None):
    data = data if data is not None else json.loads(booking["result"] or "{}")
    return {"ok": True, "context_reference": booking["id"], "proposal_id": booking["id"],
            "timezone": config.timezone, "simulated": config.mode == "demo", **data}


def available(config, call):
    args, now, zone = call.arguments, clock(), ZoneInfo(config.timezone)
    start_date = args.start_date or now.astimezone(zone).date()
    end_date = args.end_date or min(start_date + timedelta(days=6), now.astimezone(zone).date() + timedelta(days=config.horizon_days))
    if start_date < now.astimezone(zone).date() or not 0 <= (end_date-start_date).days <= 6 or end_date > now.astimezone(zone).date() + timedelta(days=config.horizon_days):
        return {"ok": False, "error": "periodo_fora_da_janela", "max_days_per_query": 7, "horizon_days": config.horizon_days}
    start = datetime.combine(start_date, time(), zone).astimezone(timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time(), zone).astimezone(timezone.utc)
    busy = [(parse(item["start"]), parse(item["end"])) for item in provider(config).busy(start, end)]
    slots, truncated, day = [], False, start_date
    db = store.connect()
    try:
        with db:
            db.execute("DELETE FROM slots WHERE expires<?", (now.timestamp(),))
            while day <= end_date:
                for a, b in config.hours.get(str(day.weekday()), []):
                    local = datetime.combine(day, time.fromisoformat(a), zone)
                    finish = datetime.combine(day, time.fromisoformat(b), zone)
                    while local + timedelta(minutes=config.duration_minutes) <= finish:
                        meeting_start = local.astimezone(timezone.utc)
                        meeting_end = (local + timedelta(minutes=config.duration_minutes)).astimezone(timezone.utc)
                        period_ok = args.period is None or (args.period == "manha" and local.hour < 12) or (args.period == "tarde" and local.hour >= 12)
                        if (period_ok and meeting_start >= now + timedelta(minutes=config.lead_minutes)
                            and not any(a < meeting_end and b > meeting_start for a, b in busy)
                            and not store.overlap(db, config.scope, meeting_start.isoformat(), meeting_end.isoformat())):
                            if len(slots) >= 32:
                                truncated = True
                            else:
                                sid = secrets.token_urlsafe(24)
                                db.execute("INSERT INTO slots VALUES(?,?,?,?,?,?,?)", (sid, call.tenant_id, call.conversation_id,
                                    config.scope, meeting_start.isoformat(), meeting_end.isoformat(), now.timestamp()+900))
                                slots.append({"slot_id": sid, "start": local.isoformat(), "end": (local + timedelta(minutes=config.duration_minutes)).isoformat()})
                        local += timedelta(minutes=config.duration_minutes)
                day += timedelta(days=1)
    finally:
        db.close()
    return {"ok": True, "context_reference": "meeting-availability", "simulated": config.mode == "demo",
            "timezone": config.timezone, "duration_minutes": config.duration_minutes,
            "slots": slots, "truncated": truncated, "expires_in_minutes": 15, "reserved": False}


def prepare(config, call):
    args, now = call.arguments, clock()
    source = str(call.context.get("message_id", ""))
    if not source:
        return {"ok": False, "error": "mensagem_de_origem_necessaria"}
    db = store.connect()
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            slot = db.execute("SELECT * FROM slots WHERE id=? AND tenant=? AND conversation=? AND scope=? AND expires>?",
                (args.slot_id, call.tenant_id, call.conversation_id, config.scope, now.timestamp())).fetchone()
            if slot is None:
                return {"ok": False, "error": "horario_invalido_ou_expirado"}
            previous = db.execute("SELECT * FROM bookings WHERE slot=? AND tenant=? AND conversation=?",
                (args.slot_id, call.tenant_id, call.conversation_id)).fetchone()
            if previous:
                if previous["state"] == "prepared" and any(previous[key] != getattr(args, key) for key in ("name", "email", "topic")):
                    summary = {**json.loads(previous["result"]), "name": args.name, "email": args.email, "topic": args.topic}
                    db.execute("UPDATE bookings SET name=?,email=?,topic=?,source_message=?,result=?,created=? WHERE id=?",
                        (args.name,args.email,args.topic,source,json.dumps(summary),now.timestamp(),previous["id"]))
                    return result(config, previous, summary)
                return result(config, previous)
            bid = secrets.token_urlsafe(24)
            eid = "lumi" + hashlib.sha256((call.tenant_id + ":" + bid).encode()).hexdigest()
            summary = {"status": "awaiting_confirmation", "start": slot["start"], "end": slot["end"],
                "name": args.name, "email": args.email, "topic": args.topic, "requires_customer_confirmation": True}
            db.execute("INSERT INTO bookings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (bid, args.slot_id,
                call.tenant_id, call.conversation_id, config.scope, slot["start"], slot["end"], args.name,
                args.email, args.topic, source, "prepared", eid, json.dumps(summary), now.timestamp()))
            booking = store.scoped(db, bid, call.tenant_id, call.conversation_id)
            return result(config, booking, summary)
    finally:
        db.close()


def recover(config, db, booking):
    if booking["state"] == "confirmed":
        return result(config, booking)
    try:
        event = provider(config).get(booking["event"])
        if event:
            data = {**public_event(event, booking), "invitations_requested": config.mode == "google" and config.send_invites}
            with db:
                db.execute("UPDATE bookings SET state='confirmed',result=? WHERE id=?", (json.dumps(data), booking["id"]))
            return result(config, booking, data)
    except Exception:
        log.warning("scheduling-recovery-pending", extra={"booking_id": booking["id"]})
    return result(config, booking, {"status": "pending_verification", "confirmed": False})


def confirm(config, call):
    db = store.connect()
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            booking = store.scoped(db, call.arguments.proposal_id, call.tenant_id, call.conversation_id)
            if booking is None or booking["scope"] != config.scope:
                return {"ok": False, "error": "proposta_nao_encontrada"}
            if booking["state"] in ("creating", "unknown", "confirmed"):
                retry = True
            else:
                retry = False
                if not call.context.get("message_id") or call.context["message_id"] == booking["source_message"]:
                    return {"ok": False, "error": "aguardando_confirmacao_do_cliente"}
                now = clock()
                if now.timestamp() > booking["created"]+900 or parse(booking["start"]) < now + timedelta(minutes=config.lead_minutes):
                    return {"ok": False, "error": "proposta_expirada"}
                if store.overlap(db, config.scope, booking["start"], booking["end"], booking["id"]) or provider(config).busy(parse(booking["start"]), parse(booking["end"])):
                    return {"ok": False, "error": "horario_nao_disponivel"}
                db.execute("UPDATE bookings SET state='creating' WHERE id=?", (booking["id"],))
        if retry:
            return recover(config, db, booking)
        try:
            event = provider(config).create(booking)
            data = {**public_event(event, booking), "invitations_requested": config.mode == "google" and config.send_invites}
            with db:
                db.execute("UPDATE bookings SET state='confirmed',result=? WHERE id=?", (json.dumps(data), booking["id"]))
            return result(config, booking, data)
        except Exception:
            with db:
                db.execute("UPDATE bookings SET state='unknown' WHERE id=?", (booking["id"],))
            log.warning("scheduling-write-pending", extra={"booking_id": booking["id"]})
            return recover(config, db, booking)
    finally:
        db.close()


def status(config, call):
    db = store.connect()
    try:
        booking = store.scoped(db, call.arguments.proposal_id, call.tenant_id, call.conversation_id)
        if booking is None or booking["scope"] != config.scope:
            return {"ok": False, "error": "proposta_nao_encontrada"}
        return recover(config, db, booking) if booking["state"] in ("unknown", "creating") else result(config, booking)
    finally:
        db.close()
