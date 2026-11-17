"""Atualização idempotente dos convidados do mesmo evento; não cria reuniões."""
import hashlib
import json
import logging
import re
import httpx
from . import engine, store
from .google import public_event

log = logging.getLogger(__name__)


def save(db, config, booking, operation, data):
    with db:
        db.execute("UPDATE participant_changes SET state='confirmed',result=? WHERE id=?", (json.dumps(data),operation))
        db.execute("UPDATE bookings SET result=? WHERE id=?", (json.dumps(data),booking["id"]))
    return engine.result(config,booking,data)


def recover(db, config, booking, operation):
    try:
        event = engine.provider(config).get(booking["event"])
        if event and event.get("extendedProperties",{}).get("private",{}).get("lumi_participants_op") == operation:
            return save(db,config,booking,operation,{**public_event(event,booking),"invitations_requested":config.send_invites})
    except Exception:
        log.warning("scheduling-participants-recovery-pending",extra={"booking_id":booking["id"]})
    return engine.result(config,booking,{"status":"pending_verification","invitations_requested":False})


def update(config, call):
    args = call.arguments
    emails = sorted({email.strip().lower() for email in args.emails})
    if any(len(email)>240 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email) for email in emails):
        return {"ok":False,"error":"email_invalido"}
    message = str(call.context.get("message_id", ""))
    if not message:
        return {"ok":False,"error":"mensagem_de_origem_necessaria"}
    if not emails and not args.resend_invitations:
        return {"ok":False,"error":"informe_participante_ou_reenvio"}
    operation = hashlib.sha256(json.dumps([call.tenant_id,call.conversation_id,args.proposal_id,message,emails,args.resend_invitations]).encode()).hexdigest()
    db = store.connect()
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            booking = store.scoped(db,args.proposal_id,call.tenant_id,call.conversation_id)
            if booking is None or booking["scope"] != config.scope or booking["state"] != "confirmed":
                return {"ok":False,"error":"reuniao_confirmada_nao_encontrada"}
            previous = db.execute("SELECT * FROM participant_changes WHERE id=?",(operation,)).fetchone()
            if previous and previous["state"] == "confirmed":
                return engine.result(config,booking,json.loads(previous["result"]))
            if previous and previous["state"] == "rejected":
                return {"ok":False,"error":"evento_alterado_consulte_novamente"}
            pending = db.execute("SELECT id FROM participant_changes WHERE booking=? AND state IN ('creating','unknown') LIMIT 1",(booking["id"],)).fetchone()
            if pending:
                retry = pending["id"]
            else:
                retry = None
                recent = db.execute("SELECT 1 FROM participant_changes WHERE booking=? AND state='confirmed' AND created>? LIMIT 1",
                    (booking["id"],engine.clock().timestamp()-60)).fetchone()
                if args.resend_invitations and recent:
                    return {"ok":False,"error":"convite_solicitado_recentemente"}
                db.execute("INSERT INTO participant_changes VALUES(?,?,'creating',NULL,?)",(operation,booking["id"],engine.clock().timestamp()))
        if retry:
            recovered = recover(db,config,booking,retry)
            if retry != operation:
                return {"ok":False,"error":"nova_alteracao_ainda_nao_aplicada","previous_status":recovered.get("status")}
            return recovered
        try:
            if config.mode == "demo":
                old = json.loads(booking["result"] or "{}")
                data = {**old,"status":"confirmed","invitations_requested":False,"participants_updated":True}
            else:
                event, sent = engine.provider(config).participants(booking,emails,operation,args.resend_invitations)
                data = {**public_event(event,booking),"invitations_requested":sent,"participants_updated":True}
            return save(db,config,booking,operation,data)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 412:
                with db:
                    db.execute("UPDATE participant_changes SET state='rejected' WHERE id=?",(operation,))
                return {"ok":False,"error":"evento_alterado_consulte_novamente"}
            with db:
                db.execute("UPDATE participant_changes SET state='unknown' WHERE id=?",(operation,))
            log.warning("scheduling-participants-pending",extra={"booking_id":booking["id"]})
            return recover(db,config,booking,operation)
        except Exception:
            with db:
                db.execute("UPDATE participant_changes SET state='unknown' WHERE id=?",(operation,))
            log.warning("scheduling-participants-pending",extra={"booking_id":booking["id"]})
            return recover(db,config,booking,operation)
    finally:
        db.close()
