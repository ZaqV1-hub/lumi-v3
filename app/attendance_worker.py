"""Agenda avisos sem pausar a assistente antes de um operador assumir."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select, update, func, or_

from .attendance import AttendancePolicy, AttendanceRequest, schedule, utc
from .db import Session
from .features import ASSISTED_HANDOVER_ENDPOINT
from .media_models import ContactGate
from .models import Conversation, Feature, Message, now
from .reply_delivery import save_reply
from .spam import admission_lock, control
from .tenant_runtime import enabled

log = logging.getLogger(__name__)


def register(db, tid, cid, mid):
    policy = db.get(AttendancePolicy, tid)
    if not policy:
        return
    row = db.get(AttendanceRequest, cid)
    if not row:
        row = AttendanceRequest(tenant_id=tid, conversation_id=cid, message_id=mid)
        db.add(row)
    row.message_id, row.requested_at = mid, now()
    row.claimed_at = row.unavailable_at = None
    row.available_since = now() if schedule(policy)[0] else None
    row.checked_at = now()


def process(cid, at=None):
    from .whatsapp.handover_alerts import HandoverAlert
    from .whatsapp.calling import has_active_call
    from .whatsapp.models import Chat
    from .instagram.models import Chat as InstagramChat
    at = utc(at or now())
    with admission_lock, Session.begin() as db:
        conversation = db.scalar(select(Conversation).where(Conversation.id == cid).with_for_update())
        row = db.get(AttendanceRequest, cid)
        if not conversation or not row or row.tenant_id != conversation.tenant_id or conversation.status not in {"aguardando", "humano"}:
            return
        tid = conversation.tenant_id
        policy = db.get(AttendancePolicy, tid)
        if not policy or not enabled(db, tid):
            return
        row.checked_at = at
        feature = db.scalar(select(Feature).where(Feature.tenant_id == tid, Feature.name == "handover", Feature.enabled.is_(True)))
        if not feature or feature.endpoint != ASSISTED_HANDOVER_ENDPOINT or not schedule(policy, at)[0]:
            return
        if row.available_since is None:
            row.available_since = at
        db.execute(update(HandoverAlert).where(HandoverAlert.message_id == row.message_id,
            HandoverAlert.status == "deferred").values(status="pending"))
        if not policy.timeout_enabled or row.unavailable_at or has_active_call(db, tenant_id=tid, conversation_id=cid):
            return
        claimed = conversation.status == "humano"
        if policy.timeout_mode == ("waiting" if claimed else "claimed"):
            return
        customer_at = db.scalar(select(func.max(Message.created_at)).where(Message.tenant_id == tid,
            Message.conversation_id == cid, Message.sender == "cliente"))
        anchor = max(utc(row.requested_at), utc(row.available_since))
        if claimed:
            if not row.claimed_at:
                return
            human_at = db.scalar(select(func.max(Message.created_at)).where(Message.tenant_id == tid,
                Message.conversation_id == cid, Message.sender == "humano"))
            if human_at and (not customer_at or utc(human_at) >= utc(customer_at)):
                return  # The customer is not waiting for an answer.
            anchor = max(anchor, utc(row.claimed_at), utc(customer_at) if customer_at else anchor)
        if at < anchor + timedelta(minutes=policy.timeout_minutes):
            return
        gate = db.get(ContactGate, conversation.contact_id)
        if gate and (gate.pending or gate.blocked):
            return
        row.unavailable_at = at
        if claimed:
            state = control(db, cid)
            state.operator_id = None
            state.revision += 1
            conversation.status = "aguardando"
        state = control(db, cid)
        # The operator alert has its own template/window policy. It can still be
        # queued when the customer's free-form window has expired.
        external_chat = db.get(Chat, cid) or db.get(InstagramChat, cid)
        can_notify_customer = not external_chat or (customer_at and utc(customer_at) >= at - timedelta(hours=23))
        if not can_notify_customer:
            notice = Message(tenant_id=tid, conversation_id=cid, sender="sistema",
                content="O prazo de espera por um atendente foi atingido.")
            db.add(notice)
            db.flush()
            from .whatsapp.models import Outbox
            from .instagram.models import Outbox as InstagramOutbox
            for model in (Outbox, InstagramOutbox):
                queued = db.get(model, notice.id)
                if queued:
                    queued.status, queued.error = "cancelled", "Aviso interno; janela de atendimento encerrada."
        else:
            notice = save_reply(db, tid, cid,
            "Ainda não tivemos uma resposta de um atendente. Sua solicitação continua registrada para a equipe. "
            "Enquanto isso, sigo por aqui para ajudar com suas dúvidas.", state.revision, track_revision=True)[0]
        original = db.get(HandoverAlert, row.message_id)
        if not original or original.status in {"accepted", "failed", "no_window", "cancelled"}:
            from .whatsapp.handover_alerts import enqueue
            enqueue(db, tid, cid, notice.id, original.topic if original else "outro")


def run_once():
    with Session() as db:
        ids = list(db.scalars(select(AttendanceRequest.conversation_id).join(Conversation,
            Conversation.id == AttendanceRequest.conversation_id).join(AttendancePolicy,
            AttendancePolicy.tenant_id == AttendanceRequest.tenant_id)
            .where(Conversation.status.in_(("aguardando", "humano")),
                   or_(AttendanceRequest.unavailable_at.is_(None), AttendanceRequest.available_since.is_(None)),
                   or_(AttendancePolicy.hours_enabled.is_(True), AttendancePolicy.timeout_enabled.is_(True),
                       AttendanceRequest.available_since.is_(None)))
            .order_by(AttendanceRequest.checked_at).limit(50)))
    for cid in ids:
        process(cid)


async def poll():
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            log.exception("Attendance scheduling failed")
        await asyncio.sleep(2)
