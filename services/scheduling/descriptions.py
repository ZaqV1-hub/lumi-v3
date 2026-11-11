"""Consulta de agenda do tenant e edição restrita à descrição, com recuperação."""
import hashlib
import json
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import httpx
from . import engine, store
from .google import public_event

log = logging.getLogger(__name__)


def agenda(config, call):
    args = call.arguments
    if not 0 <= (args.end_date-args.start_date).days <= 6:
        return {"ok":False,"error":"intervalo_maximo_sete_dias"}
    zone = ZoneInfo(config.timezone)
    start = datetime.combine(args.start_date,time.min,zone).astimezone(engine.timezone.utc).isoformat()
    end = datetime.combine(args.end_date+timedelta(days=1),time.min,zone).astimezone(engine.timezone.utc).isoformat()
    db = store.connect()
    try:
        rows = db.execute("SELECT * FROM bookings WHERE tenant=? AND scope=? AND state='confirmed' AND start>=? AND start<? ORDER BY start,id LIMIT 21",
                          (call.tenant_id,config.scope,start,end)).fetchall()
        meetings=[]
        for booking in rows[:20]:
            description=booking["topic"]
            public={"start":booking["start"],"end":booking["end"]}
            meetings.append({"proposal_id":booking["id"],"name":booking["name"],"description":description[:2000],"description_truncated":len(description)>2000,**public})
        reference=hashlib.sha256(json.dumps([call.tenant_id,call.conversation_id,str(args.start_date),str(args.end_date)]).encode()).hexdigest()
        return {"ok":True,"context_reference":reference,"meetings":meetings,"truncated":len(rows)>20,"simulated":config.mode=="demo","source":"registros_da_integracao"}
    finally:
        db.close()


def completed(db, operation, booking, text):
    with db:
        db.execute("UPDATE description_changes SET state='confirmed' WHERE id=?",(operation,))
        db.execute("UPDATE bookings SET topic=? WHERE id=?",(text,booking["id"]))
    return {"ok":True,"status":"confirmed","proposal_id":booking["id"],"description_updated":True}


def recover(db, config, booking, operation):
    row=db.execute("SELECT * FROM description_changes WHERE id=?",(operation,)).fetchone()
    try:
        event=engine.provider(config).get(booking["event"])
        if event and event.get("extendedProperties",{}).get("private",{}).get("lumi_description_op")==operation:
            public_event(event,booking)
            return completed(db,operation,booking,row["description"])
    except Exception:
        log.warning("scheduling-description-recovery-pending",extra={"booking_id":booking["id"]})
    return {"ok":True,"status":"pending_verification","proposal_id":booking["id"]}


def update(config, call):
    message=str(call.context.get("message_id", ""))
    if not message:
        return {"ok":False,"error":"mensagem_de_origem_necessaria"}
    text=call.arguments.description
    operation=hashlib.sha256(json.dumps([call.tenant_id,call.conversation_id,call.arguments.proposal_id,message,text]).encode()).hexdigest()
    db=store.connect()
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            booking=db.execute("SELECT * FROM bookings WHERE id=? AND tenant=? AND scope=? AND state='confirmed'",
                (call.arguments.proposal_id,call.tenant_id,config.scope)).fetchone()
            if booking is None:
                return {"ok":False,"error":"reuniao_confirmada_nao_encontrada"}
            previous=db.execute("SELECT * FROM description_changes WHERE id=?",(operation,)).fetchone()
            if previous and previous["state"]=="confirmed":
                return {"ok":True,"status":"confirmed","proposal_id":booking["id"],"description_updated":True}
            if previous and previous["state"]=="rejected":
                return {"ok":False,"error":"evento_alterado_consulte_novamente"}
            pending=db.execute("SELECT id FROM description_changes WHERE booking=? AND state IN ('creating','unknown') LIMIT 1",(booking["id"],)).fetchone()
            if not pending:
                db.execute("INSERT INTO description_changes VALUES(?,?,'creating',?,?)",(operation,booking["id"],text,engine.clock().timestamp()))
        if pending:
            result=recover(db,config,booking,pending["id"])
            return result if pending["id"]==operation else {"ok":False,"error":"nova_alteracao_ainda_nao_aplicada","previous_status":result["status"]}
        if config.mode=="demo":
            return {**completed(db,operation,booking,text),"simulated":True}
        try:
            event=engine.provider(config).description(booking,text,operation)
            public_event(event,booking)
            return {**completed(db,operation,booking,text),"simulated":False}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code==412:
                with db:
                    db.execute("UPDATE description_changes SET state='rejected' WHERE id=?",(operation,))
                return {"ok":False,"error":"evento_alterado_consulte_novamente"}
        except Exception:
            pass
        with db:
            db.execute("UPDATE description_changes SET state='unknown' WHERE id=?",(operation,))
        log.warning("scheduling-description-pending",extra={"booking_id":booking["id"]})
        return recover(db,config,booking,operation)
    finally:
        db.close()
