"""Transactional calling state. Caller commits reservations before any HTTP.

Normalized events are supplied by the verified channel adapter, never raw Graph
payloads. Terminal states require confirmed external outcomes (or proof no send
occurred); a local timeout only transitions to uncertain.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json

from fastapi import HTTPException
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError

from ..console_models import ConsoleAccount
from ..media_models import ConversationControl
from ..models import Conversation, LoginSession, User, now
from ..tenant_runtime import enabled
from .models import Channel, Chat
from .calling_models import CallEvent, CallOperation, CallPermission, CallingChannel


TERMINAL_STATES = frozenset({'ended', 'rejected', 'failed', 'canceled', 'sent'})
CALL_STATES = frozenset({'reserved', 'initiating', 'ringing', 'accepted', 'terminating', 'uncertain',
                         'ended', 'rejected', 'failed', 'canceled'})
PERMISSION_STATES = frozenset({'unknown', 'absent', 'pending', 'granted', 'denied', 'expired', 'revoked'})
LEASE_SECONDS = 45


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def schema_ready(db):
    return inspect(db.get_bind()).has_table(CallingChannel.__tablename__)


def channel_enabled(db, *, tenant_id, phone_number_id):
    if not schema_ready(db):
        return False
    row = db.get(CallingChannel, phone_number_id, populate_existing=True)
    channel = db.get(Channel, phone_number_id, populate_existing=True)
    return bool(row and row.enabled and row.tenant_id == tenant_id and channel and channel.tenant_id == tenant_id)


def lock_conversation(db, tenant_id, conversation_id):
    # A consistent channel-first order also serializes early webhook/HTTP binding.
    phone_number_id = db.scalar(select(Chat.phone_number_id).join(Conversation, Conversation.id == Chat.id)
        .where(Chat.id == conversation_id, Conversation.tenant_id == tenant_id))
    if phone_number_id:
        _lock_channel(db, tenant_id, phone_number_id)
    # UPDATE acquires an actual write lock in SQLite as well as PostgreSQL.
    result = db.execute(update(Conversation).where(Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id).values(status=Conversation.status).execution_options(synchronize_session=False))
    if not result.rowcount:
        raise HTTPException(404, 'Conversa não encontrada')
    conversation = db.get(Conversation, conversation_id, populate_existing=True)
    db.execute(update(ConversationControl).where(ConversationControl.conversation_id == conversation_id)
        .values(revision=ConversationControl.revision).execution_options(synchronize_session=False))
    return conversation


def _lock_channel(db, tenant_id, phone_number_id):
    db.execute(update(Channel).where(Channel.phone_number_id == phone_number_id, Channel.tenant_id == tenant_id)
        .values(tenant_id=Channel.tenant_id).execution_options(synchronize_session=False))


def _context(db, tenant_id, conversation_id, operator_id, *, require_enabled=True):
    conversation = lock_conversation(db, tenant_id, conversation_id)
    user = db.get(User, operator_id, populate_existing=True)
    account = db.get(ConsoleAccount, operator_id, populate_existing=True)
    if not user or (user.tenant_id != tenant_id and not (account and account.role == 'brevia')):
        raise HTTPException(403, 'Operador não autorizado')
    if account and (not account.enabled or account.must_change_password or account.role == 'leitura'):
        raise HTTPException(403, 'Operador não autorizado')
    if require_enabled and not enabled(db, tenant_id):
        raise HTTPException(403, 'Empresa desativada')
    control = db.get(ConversationControl, conversation_id, populate_existing=True)
    if conversation.status != 'humano' or not control or control.operator_id != operator_id:
        raise HTTPException(409, 'Assuma o atendimento antes de ligar')
    chat = db.get(Chat, conversation_id, populate_existing=True)
    channel = db.get(Channel, chat.phone_number_id, populate_existing=True) if chat else None
    if not chat or not chat.sender or not channel or channel.tenant_id != tenant_id:
        raise HTTPException(409, 'Conversa sem canal WhatsApp válido')
    if require_enabled and not channel_enabled(db, tenant_id=tenant_id, phone_number_id=channel.phone_number_id):
        raise HTTPException(409, 'Chamadas indisponíveis neste canal')
    return chat


def has_active_call(db, *, tenant_id, conversation_id):
    if not schema_ready(db):
        return False
    return db.scalar(select(CallOperation.id).where(CallOperation.tenant_id == tenant_id,
        CallOperation.conversation_id == conversation_id, CallOperation.kind == 'call', CallOperation.active.is_(True))) is not None


def permission_state(db, *, tenant_id, phone_number_id, recipient):
    if not schema_ready(db):
        return 'unknown'
    row = db.get(CallPermission, (tenant_id, phone_number_id, recipient), populate_existing=True)
    if not row:
        return 'unknown'
    if row.state == 'granted' and not row.permanent and (not row.expires_at or utc(row.expires_at) <= now()):
        return 'expired'
    return row.state


def update_permission(db, *, tenant_id, phone_number_id, recipient, state, observed_at, expires_at=None, permanent=False):
    if state not in PERMISSION_STATES:
        raise ValueError('Invalid normalized permission state')
    channel = db.get(Channel, phone_number_id)
    chat = db.scalar(select(Chat).join(Conversation, Conversation.id == Chat.id).where(
        Chat.phone_number_id == phone_number_id, Chat.sender == recipient, Conversation.tenant_id == tenant_id))
    if not channel or channel.tenant_id != tenant_id or not chat:
        raise HTTPException(404, 'Destinatário não encontrado neste canal')
    lock_conversation(db, tenant_id, chat.id)
    row = db.get(CallPermission, (tenant_id, phone_number_id, recipient), populate_existing=True)
    # Graph events have second precision; queries must use the same clock domain.
    observed_at = utc(observed_at).replace(microsecond=0)
    if row:
        previous_observation = utc(row.observed_at).replace(microsecond=0)
        if observed_at < previous_observation:
            return False
        # Revocation wins ties because Graph timestamps can have second precision.
        if observed_at == previous_observation and not (state in {'revoked', 'denied', 'expired', 'absent'} and row.state == 'granted'):
            return False
    if not row:
        row = CallPermission(tenant_id=tenant_id, phone_number_id=phone_number_id, recipient=recipient, version=0)
        db.add(row)
    row.state = state
    row.permanent = bool(permanent and state == 'granted')
    row.expires_at = expires_at if state == 'granted' and not permanent else None
    row.observed_at = observed_at
    row.version += 1
    db.flush()
    return True


def _reserve(db, *, tenant_id, conversation_id, operator_id, idempotency_key, kind,
             tab_token=None, session_hash=None, offer_sdp=None, session_expires_at=None):
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
        raise HTTPException(422, 'Chave idempotente inválida')
    chat = _context(db, tenant_id, conversation_id, operator_id)
    if kind == 'call' and (not tab_token or len(tab_token) > 256 or not session_hash or len(session_hash) != 64 or not offer_sdp or len(offer_sdp) > 65536):
        raise HTTPException(422, 'Sessão de chamada inválida')
    if kind == 'call':
        login = db.get(LoginSession, session_hash, populate_existing=True)
        if not login or login.user_id != operator_id or (session_expires_at and utc(session_expires_at) <= now()):
            raise HTTPException(403, 'Sessão de chamada expirada')
    arguments_hash = token_hash(json.dumps([tenant_id, conversation_id, operator_id, chat.phone_number_id,
        chat.sender, kind, token_hash(tab_token) if tab_token else None, session_hash,
        token_hash(offer_sdp) if offer_sdp else None], separators=(',', ':')))
    existing = db.scalar(select(CallOperation).where(CallOperation.tenant_id == tenant_id,
        CallOperation.operator_id == operator_id, CallOperation.idempotency_key == idempotency_key))
    if existing:
        if existing.arguments_hash != arguments_hash:
            raise HTTPException(409, 'Chave idempotente já utilizada com outros dados')
        existing.is_new = False
        return existing
    if kind == 'call' and permission_state(db, tenant_id=tenant_id, phone_number_id=chat.phone_number_id, recipient=chat.sender) != 'granted':
        raise HTTPException(409, 'O cliente ainda não autorizou esta chamada')
    op = CallOperation(tenant_id=tenant_id, conversation_id=conversation_id, operator_id=operator_id,
        phone_number_id=chat.phone_number_id, recipient=chat.sender, kind=kind,
        idempotency_key=idempotency_key, arguments_hash=arguments_hash,
        tab_token_hash=token_hash(tab_token) if tab_token else None, session_hash=session_hash,
        session_expires_at=session_expires_at or (now()+timedelta(days=1) if kind == 'call' else None),
        lease_expires_at=now()+timedelta(seconds=LEASE_SECONDS) if kind == 'call' else None)
    try:
        with db.begin_nested():
            db.add(op)
            db.flush()
    except IntegrityError:
        raise HTTPException(409, 'Já existe uma operação ativa para este operador ou conversa') from None
    op.is_new = True
    return op


def reserve_call(db, *, tenant_id, conversation_id, operator_id, idempotency_key, tab_token, session_hash, offer_sdp, session_expires_at=None):
    return _reserve(db, tenant_id=tenant_id, conversation_id=conversation_id, operator_id=operator_id,
        idempotency_key=idempotency_key, kind='call', tab_token=tab_token, session_hash=session_hash,
        offer_sdp=offer_sdp, session_expires_at=session_expires_at)


def reserve_permission(db, *, tenant_id, conversation_id, operator_id, idempotency_key):
    return _reserve(db, tenant_id=tenant_id, conversation_id=conversation_id, operator_id=operator_id,
        idempotency_key=idempotency_key, kind='permission')


def update_operation(db, operation, *, state=None, external_id=None, answer_sdp=None, public_error=None, event_at=None):
    lock_conversation(db, operation.tenant_id, operation.conversation_id)
    db.refresh(operation)
    if not operation.active:
        return False
    if state and (state not in CALL_STATES | {'sent'} or (state == 'sent' and operation.kind == 'call')):
        raise ValueError('Invalid normalized operation state')
    stale_event = bool(event_at and operation.event_at and utc(event_at) < utc(operation.event_at))
    ranks = {'reserved': 0, 'initiating': 1, 'ringing': 2, 'accepted': 3, 'terminating': 4}
    if ((stale_event and state not in TERMINAL_STATES)
            or (state in ranks and operation.state in ranks and ranks[state] < ranks[operation.state])):
        state = None
        # A late connect can still carry the first SDP answer after accepted.
        if answer_sdp is None and not external_id and not public_error:
            return False
    new_binding = bool(external_id and not operation.external_id)
    if external_id:
        if operation.external_id and operation.external_id != external_id:
            raise HTTPException(409, 'Identificador externo divergente')
        operation.external_id = external_id
    if answer_sdp is not None:
        if len(answer_sdp) > 65536:
            raise ValueError('SDP exceeds limit')
        operation.answer_sdp = answer_sdp
    if state:
        operation.state = state
        if state == 'terminating' and operation.reconcile_after is None:
            # A scheduled termination survives late connect results and webhooks.
            operation.reconcile_after = now()
    if public_error:
        operation.public_error = public_error
    if event_at and not stale_event:
        operation.event_at = event_at
    operation.updated_at = now()
    operation.version += 1
    if operation.state in TERMINAL_STATES:
        operation.active = False
        operation.answer_sdp = None
        operation.lease_expires_at = None
        operation.reconcile_after = None
        operation.ended_at = now()
    db.flush()
    if new_binding:
        reconcile_call_events(db, operation)
    return True


def authorize_operation(db, *, tenant_id, operation_id, operator_id, tab_token, session_hash, require_enabled=False):
    op = db.scalar(select(CallOperation).where(CallOperation.id == operation_id, CallOperation.tenant_id == tenant_id))
    if not op:
        raise HTTPException(404, 'Chamada não encontrada')
    chat = _context(db, tenant_id, op.conversation_id, operator_id, require_enabled=require_enabled)
    db.refresh(op)
    login = db.get(LoginSession, session_hash, populate_existing=True)
    if (op.operator_id != operator_id or not login or login.user_id != operator_id
            or not op.session_expires_at or utc(op.session_expires_at) <= now()
            or not op.session_hash or not hmac.compare_digest(op.session_hash, session_hash)
            or not op.tab_token_hash or not hmac.compare_digest(op.tab_token_hash, token_hash(tab_token))
            or op.phone_number_id != chat.phone_number_id or op.recipient != chat.sender):
        raise HTTPException(403, 'Esta chamada pertence a outra sessão ou aba')
    return op


def heartbeat(db, *, tenant_id, operation_id, operator_id, tab_token, session_hash, browser_state):
    if browser_state not in {'new', 'connecting', 'connected', 'disconnected', 'failed', 'closed'}:
        raise HTTPException(422, 'Estado de conexão inválido')
    op = authorize_operation(db, tenant_id=tenant_id, operation_id=operation_id,
        operator_id=operator_id, tab_token=tab_token, session_hash=session_hash)
    if not op.active:
        return op
    op.browser_state = browser_state
    op.heartbeat_at = now()
    op.lease_expires_at = now()+timedelta(seconds=LEASE_SECONDS)
    if browser_state == 'connected' and not op.connected_at:
        op.connected_at = now()
    op.updated_at = now()
    op.version += 1
    db.flush()
    return op


@dataclass(frozen=True)
class NormalizedCallEvent:
    event_id: str
    kind: str
    state: str
    occurred_at: datetime
    external_id: str | None = None
    operation_id: str | None = None
    recipient: str | None = None
    answer_sdp: str | None = None
    expires_at: datetime | None = None
    permanent: bool = False


def apply_call_event(db, *, channel, event):
    _lock_channel(db, channel.tenant_id, channel.phone_number_id)
    if not channel_enabled(db, tenant_id=channel.tenant_id, phone_number_id=channel.phone_number_id):
        return False
    if event.kind not in {'call', 'permission'} or not event.event_id or len(event.event_id) > 240:
        raise ValueError('Invalid normalized event')
    if event.kind == 'call' and event.state not in CALL_STATES:
        raise ValueError('Invalid normalized call state')
    if event.answer_sdp and len(event.answer_sdp) > 65536:
        raise ValueError('SDP exceeds limit')
    if db.get(CallEvent, (channel.phone_number_id, event.event_id)):
        return False
    query = select(CallOperation).where(CallOperation.tenant_id == channel.tenant_id,
        CallOperation.phone_number_id == channel.phone_number_id, CallOperation.kind == event.kind)
    if event.operation_id:
        query = query.where(CallOperation.id == event.operation_id)
    elif event.external_id:
        query = query.where(CallOperation.external_id == event.external_id)
    else:
        query = None
    op = db.scalar(query) if query is not None else None
    if event.kind == 'call' and not op and not event.external_id:
        return False
    if op:
        lock_conversation(db, channel.tenant_id, op.conversation_id)
        db.refresh(op)
        if (event.recipient and event.recipient != op.recipient) or (event.external_id and op.external_id and event.external_id != op.external_id):
            return False
    if event.kind == 'permission':
        recipient = event.recipient or (op.recipient if op else None)
        chat = db.scalar(select(Chat).join(Conversation, Conversation.id == Chat.id).where(
            Chat.phone_number_id == channel.phone_number_id, Chat.sender == recipient, Conversation.tenant_id == channel.tenant_id))
        if not chat:
            return False
        lock_conversation(db, channel.tenant_id, chat.id)
    saved = CallEvent(phone_number_id=channel.phone_number_id, event_id=event.event_id, tenant_id=channel.tenant_id,
        operation_id=op.id if op else None, external_id=event.external_id, recipient=event.recipient,
        answer_sdp=event.answer_sdp if event.state not in TERMINAL_STATES else None,
        kind=event.kind, state=event.state, occurred_at=event.occurred_at)
    db.add(saved)
    db.flush()
    if event.kind == 'permission':
        changed = update_permission(db, tenant_id=channel.tenant_id, phone_number_id=channel.phone_number_id,
            recipient=recipient, state=event.state, observed_at=event.occurred_at, expires_at=event.expires_at, permanent=event.permanent)
        if op and changed:
            update_operation(db, op, state='sent')
        saved.processed = True
        saved.answer_sdp = None
    elif not op:
        # Exact external correlation is required; never guess from an active chat.
        changed = False
    else:
        saved.processed = True
        saved.answer_sdp = None
        changed = update_operation(db, op, state=event.state, external_id=event.external_id,
            answer_sdp=event.answer_sdp, event_at=event.occurred_at)
    db.flush()
    return changed


def reconcile_call_events(db, operation):
    lock_conversation(db, operation.tenant_id, operation.conversation_id)
    db.refresh(operation)
    if not operation.external_id:
        return False
    events = list(db.scalars(select(CallEvent).where(CallEvent.tenant_id == operation.tenant_id,
        CallEvent.phone_number_id == operation.phone_number_id, CallEvent.external_id == operation.external_id,
        CallEvent.kind == operation.kind, CallEvent.processed.is_(False)).order_by(CallEvent.occurred_at, CallEvent.received_at)))
    changed = False
    for saved in events:
        if saved.operation_id and saved.operation_id != operation.id:
            continue
        if saved.recipient and saved.recipient != operation.recipient:
            saved.answer_sdp = None
            saved.processed = True
            continue
        answer_sdp = saved.answer_sdp
        saved.operation_id = operation.id
        saved.processed = True
        saved.answer_sdp = None
        changed = update_operation(db, operation, state=saved.state, answer_sdp=answer_sdp,
                                   event_at=saved.occurred_at) or changed
    db.flush()
    return changed


def purge_expired_event_sdp(db):
    """Bound unmatched SDP retention; this never declares a call terminated."""
    result = db.execute(update(CallEvent).where(CallEvent.answer_sdp.is_not(None),
        CallEvent.received_at < now()-timedelta(minutes=5)).values(answer_sdp=None))
    return result.rowcount
