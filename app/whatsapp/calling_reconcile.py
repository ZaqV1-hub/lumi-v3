"""One cancellable admin worker; durable leases coordinate with the webhook process."""
import asyncio
from datetime import timedelta
import logging

from sqlalchemy import select

from ..console_models import ConsoleAccount
from ..db import Session
from ..media_models import ConversationControl
from ..models import Conversation, LoginSession, now
from . import calling, calling_graph as graph
from .calling_models import CallOperation
from .models import Channel

log = logging.getLogger(__name__)


def terminate_one(operation_id):
    with Session.begin() as db:
        op = db.get(CallOperation, operation_id)
        if not op or not op.active:
            return
        calling.lock_conversation(db, op.tenant_id, op.conversation_id)
        db.refresh(op)
        if not op.active or (op.reconcile_after and calling.utc(op.reconcile_after) > now()):
            return
        if not op.external_id:
            calling.update_operation(db, op, state='terminating', public_error='reconciliation_required')
            return
        if op.terminate_attempts >= 3:
            calling.update_operation(db, op, state='uncertain', public_error='termination_unconfirmed')
            return
        op.terminate_attempts += 1
        # Reserve the attempt before HTTP; a crash cannot cause an immediate duplicate.
        op.reconcile_after = now() + timedelta(seconds=40)
        calling.update_operation(db, op, state='terminating')
        phone, external_id = op.phone_number_id, op.external_id
        token_env = db.get(Channel, phone).token_env
    error_code = None
    try:
        graph.terminate(phone, token_env, external_id)
    except graph.GraphError as error:
        error_code = error.code
    except Exception as error:
        error_code = 'termination_unconfirmed'
        log.error('Calling termination result uncertain: %s', type(error).__name__)
    with Session.begin() as db:
        op = db.get(CallOperation, operation_id)
        calling.lock_conversation(db, op.tenant_id, op.conversation_id)
        db.refresh(op)
        if op.active:
            op.reconcile_after = now() + timedelta(seconds=10)
            # Only the signed terminal event frees the reservation.
            calling.update_operation(db, op, state='uncertain' if error_code else 'terminating', public_error=error_code)


def reconcile_once():
    with Session() as db:
        if not calling.schema_ready(db):
            return
        ids = list(db.scalars(select(CallOperation.id).where(CallOperation.kind == 'call', CallOperation.active.is_(True))))
    with Session.begin() as db:
        calling.purge_expired_event_sdp(db)
    for operation_id in ids:
        with Session.begin() as db:
            op = db.get(CallOperation, operation_id)
            calling.lock_conversation(db, op.tenant_id, op.conversation_id)
            db.refresh(op)
            if not op.active:
                continue
            c = db.get(Conversation, op.conversation_id)
            control = db.get(ConversationControl, op.conversation_id)
            login = db.get(LoginSession, op.session_hash) if op.session_hash else None
            account = db.get(ConsoleAccount, op.operator_id)
            abandoned = (not op.lease_expires_at or calling.utc(op.lease_expires_at) <= now()
                or not op.session_expires_at or calling.utc(op.session_expires_at) <= now()
                or not login or login.user_id != op.operator_id or not c or c.status != 'humano'
                or not control or control.operator_id != op.operator_id
                or bool(account and (not account.enabled or account.role == 'leitura' or account.must_change_password))
                or op.browser_state in {'failed', 'closed'})
            stopping = op.reconcile_after is not None or op.state == 'terminating' or op.terminate_attempts > 0
            if not abandoned and not stopping:
                continue
        terminate_one(operation_id)


async def run_reconciler():
    while True:
        work = asyncio.create_task(asyncio.to_thread(reconcile_once))
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            # Finish the already dispatched HTTP attempt before the service exits.
            await work
            raise
        except Exception as error:
            log.error('Calling reconciliation failed: %s', type(error).__name__)
        await asyncio.sleep(10)
