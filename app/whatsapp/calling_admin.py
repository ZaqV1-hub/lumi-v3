"""Authenticated human calling controls. Graph credentials never leave the server."""
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from ..access import current_user
from ..conversations import conversation, timestamp
from ..db import Session
from ..media_models import ConversationControl
from ..models import Message, User, now
from ..tenant_runtime import enabled
from . import calling, calling_graph as graph
from .calling_models import CallOperation
from .models import Channel, Chat

router = APIRouter(prefix='/api/admin/conversations/{cid}/calling')
log = logging.getLogger(__name__)


class OperationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=1, max_length=128)


class CallInput(OperationInput):
    sdp_offer: str = Field(min_length=1, max_length=65536)

    @field_validator('sdp_offer')
    @classmethod
    def audio_only(cls, value):
        media = re.findall(r'^m=([^\s]+)', value, re.MULTILINE)
        if (len(value.encode()) > 65536 or media != ['audio'] or not value.startswith('v=0')
                or not re.search(r'^a=rtpmap:\d+ opus/48000/2\r?$', value, re.MULTILINE)
                or 'a=fingerprint:sha-256 ' not in value or 'a=ice-ufrag:' not in value):
            raise ValueError('Oferta de áudio WebRTC inválida')
        return value


class HeartbeatInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    browser_state: str = Field(pattern=r'^(new|connecting|connected|disconnected|failed|closed)$')


def write_origin(request):
    origin = request.headers.get('origin', '')
    if origin != str(request.base_url).rstrip('/') or request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Origem da solicitação inválida')


def credentials(request, user):
    tab = request.headers.get('x-calling-tab', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', tab):
        raise HTTPException(403, 'Identificação da aba inválida')
    cookie = request.cookies.get('lumi_session', '')
    return dict(operator_id=user.id, tab_token=tab,
                session_hash=hashlib.sha256(cookie.encode()).hexdigest())


def summary(op, *, media=False):
    return {'id': op.id, 'state': op.state, 'active': op.active, 'version': op.version,
            'browser_state': op.browser_state, 'connected_at': timestamp(op.connected_at) if op.connected_at else None,
            'ended_at': timestamp(op.ended_at) if op.ended_at else None, 'error_code': op.public_error,
            **({'answer_sdp': op.answer_sdp} if media else {})}


def context(db, cid, user, *, owner=False):
    c = conversation(db, user.tenant_id, cid)
    chat = db.get(Chat, cid)
    channel = db.get(Channel, chat.phone_number_id) if chat else None
    available = bool(channel and channel.tenant_id == user.tenant_id and enabled(db, user.tenant_id)
                     and calling.channel_enabled(db, tenant_id=user.tenant_id, phone_number_id=channel.phone_number_id))
    control = db.get(ConversationControl, cid)
    responsible = bool(c.status == 'humano' and control and control.operator_id == user.id and user.console_role != 'leitura')
    if owner and (not available or not responsible):
        raise HTTPException(409, 'Assuma o atendimento em um canal com chamadas habilitadas')
    return chat, channel, available, responsible


def permission_snapshot(cid, request, user):
    observed_at = now()
    with Session() as db:
        chat, channel, _, _ = context(db, cid, user, owner=True)
        phone, recipient, token_env = channel.phone_number_id, chat.sender, channel.token_env
    try:
        result = graph.get_permission(phone, token_env, recipient)
    except graph.GraphError as error:
        raise HTTPException(503, error.code) from None
    # A response from an earlier request must not overwrite a newer revocation.
    user = current_user(request)
    with Session.begin() as db:
        context(db, cid, user, owner=True)
        calling.update_permission(db, tenant_id=user.tenant_id, phone_number_id=phone,
            recipient=recipient, state=result['state'], permanent=result['permanent'],
            expires_at=result['expires_at'], observed_at=observed_at)
        result['state'] = calling.permission_state(db, tenant_id=user.tenant_id, phone_number_id=phone, recipient=recipient)
        result['can_call'] = result['can_call'] and result['state'] == 'granted'
        result['can_request'] = result['can_request'] and result['state'] != 'granted'
    return result


@router.get('')
def status(cid: str, request: Request, response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    permission = {'state': 'unknown', 'expires_at': None, 'can_call': False, 'can_request': False}
    with Session() as db:
        _, _, available, responsible = context(db, cid, user)
    reason = None if available and responsible else ('Assuma o atendimento para ligar.' if available else 'Chamadas indisponíveis neste canal.')
    if available and responsible:
        try:
            permission = permission_snapshot(cid, request, user)
        except HTTPException as error:
            if error.status_code != 503:
                raise
            reason = 'Não foi possível consultar a permissão. Tente novamente.'
    with Session() as db:
        schema_ready = calling.schema_ready(db)
        active = db.scalar(select(CallOperation).where(CallOperation.tenant_id == user.tenant_id,
            CallOperation.conversation_id == cid, CallOperation.kind == 'call', CallOperation.active.is_(True))) if schema_ready else None
        history = [{**summary(op), 'created_at': timestamp(op.created_at), 'operator_name': operator_name}
            for op, operator_name in db.execute(select(CallOperation, User.name).join(User, User.id == CallOperation.operator_id)
                .where(CallOperation.tenant_id == user.tenant_id, CallOperation.conversation_id == cid, CallOperation.kind == 'call')
                .order_by(CallOperation.created_at.desc(), CallOperation.id.desc()).limit(10))] if schema_ready else []
        latest = db.scalar(select(CallOperation).where(CallOperation.tenant_id == user.tenant_id,
            CallOperation.conversation_id == cid, CallOperation.kind == 'permission').order_by(CallOperation.created_at.desc())) if available else None
        pending = bool(latest and latest.state in {'reserved', 'initiating', 'uncertain', 'sent'}
                       and permission['state'] in {'unknown', 'absent'})
        if pending:
            permission['state'] = 'pending'
        window = db.scalar(select(func.max(Message.created_at)).where(Message.tenant_id == user.tenant_id,
            Message.conversation_id == cid, Message.sender == 'cliente'))
        in_window = bool(window and calling.utc(window) > now() - timedelta(hours=24))
        if not in_window and not permission['can_call'] and available and responsible:
            reason = 'Aguarde uma nova mensagem do cliente para pedir permissão.'
        return {'enabled': available, 'can_call': available and responsible and permission['can_call'] and not active,
                'can_request_permission': available and responsible and permission['can_request'] and in_window and not (latest and latest.active),
                'block_reason': reason, 'permission': {'state': permission['state'],
                    'expires_at': timestamp(permission['expires_at']) if permission['expires_at'] else None},
                'active_call': summary(active) if active else None, 'history': history}


def record_result(operation_id, *, external_id=None, error=None, permission=False):
    with Session.begin() as db:
        op = db.get(CallOperation, operation_id)
        if error:
            calling.lock_conversation(db, op.tenant_id, op.conversation_id)
            db.refresh(op)
            # An authenticated webhook is stronger evidence than a late HTTP error.
            state = None if op.external_id else 'uncertain' if error.uncertain else 'failed'
            calling.update_operation(db, op, state=state, public_error=error.code)
        else:
            calling.update_operation(db, op, external_id=external_id, state='sent' if permission else None)
        return summary(op, media=True)


@router.post('/permission')
def request_permission(cid: str, data: OperationInput, request: Request, response: Response, user=Depends(current_user)):
    write_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    with Session() as db:
        context(db, cid, user, owner=True)
        existing = db.scalar(select(CallOperation).where(CallOperation.tenant_id == user.tenant_id,
            CallOperation.operator_id == user.id, CallOperation.idempotency_key == data.idempotency_key))
        if existing:
            if existing.conversation_id != cid or existing.kind != 'permission':
                raise HTTPException(409, 'Chave idempotente já utilizada')
            return summary(existing)
    permission = permission_snapshot(cid, request, user)
    if permission['state'] == 'granted':
        raise HTTPException(409, 'O cliente já autorizou ligações')
    if not permission['can_request']:
        raise HTTPException(409, 'A Meta não permite solicitar permissão neste momento')
    with Session.begin() as db:
        last = db.scalar(select(func.max(Message.created_at)).where(Message.tenant_id == user.tenant_id,
            Message.conversation_id == cid, Message.sender == 'cliente'))
        if not last or calling.utc(last) <= now() - timedelta(hours=24):
            raise HTTPException(409, 'Aguarde uma nova mensagem do cliente para pedir permissão')
        user = current_user(request)
        op = calling.reserve_permission(db, tenant_id=user.tenant_id, conversation_id=cid,
                                      operator_id=user.id, idempotency_key=data.idempotency_key)
        if not op.is_new:
            return summary(op)
        calling.update_operation(db, op, state='initiating')
        opid, phone, recipient = op.id, op.phone_number_id, op.recipient
        token_env = db.get(Channel, phone).token_env
    try:
        external_id = graph.request_permission(phone, token_env, recipient, opid)
    except graph.GraphError as error:
        return record_result(opid, error=error, permission=True)
    except Exception as error:
        log.error('Calling permission result uncertain: %s', type(error).__name__)
        return record_result(opid, error=graph.GraphError('result_uncertain', uncertain=True), permission=True)
    return record_result(opid, external_id=external_id, permission=True)


@router.post('/calls')
def create_call(cid: str, data: CallInput, request: Request, response: Response, user=Depends(current_user)):
    write_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    owner = credentials(request, user)
    with Session() as db:
        context(db, cid, user, owner=True)
        existing = db.scalar(select(CallOperation.id).where(CallOperation.tenant_id == user.tenant_id,
            CallOperation.operator_id == user.id, CallOperation.idempotency_key == data.idempotency_key))
    if not existing:
        permission = permission_snapshot(cid, request, user)
        if not permission['can_call']:
            raise HTTPException(409, 'O cliente não autorizou ou a Meta bloqueou a chamada neste momento')
    user = current_user(request)
    with Session.begin() as db:
        op = calling.reserve_call(db, tenant_id=user.tenant_id, conversation_id=cid,
            idempotency_key=data.idempotency_key, offer_sdp=data.sdp_offer, **owner,
            session_expires_at=datetime.fromtimestamp(int(request.cookies['lumi_session'].split('.')[0]), timezone.utc) + timedelta(days=1))
        if not op.is_new:
            return {**summary(op, media=True), 'tab_token': owner['tab_token']}
        calling.update_operation(db, op, state='initiating')
        opid, phone, recipient = op.id, op.phone_number_id, op.recipient
        token_env = db.get(Channel, phone).token_env
    try:
        external_id = graph.connect(phone, token_env, recipient, data.sdp_offer, opid)
    except graph.GraphError as error:
        result = record_result(opid, error=error)
    except Exception as error:
        log.error('Calling connect result uncertain: %s', type(error).__name__)
        result = record_result(opid, error=graph.GraphError('result_uncertain', uncertain=True))
    else:
        result = record_result(opid, external_id=external_id)
    return {**result, 'tab_token': owner['tab_token']}


def owned(db, cid, call_id, request, user):
    op = calling.authorize_operation(db, tenant_id=user.tenant_id, operation_id=call_id, **credentials(request, user))
    if op.conversation_id != cid:
        raise HTTPException(404, 'Chamada não encontrada')
    return op


@router.get('/calls/by-key/{idempotency_key}')
def call_attempt(cid: str, idempotency_key: str, request: Request, response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    credentials(request, user)
    with Session.begin() as db:
        context(db, cid, user)
        op = db.scalar(select(CallOperation).where(CallOperation.tenant_id == user.tenant_id,
            CallOperation.conversation_id == cid, CallOperation.operator_id == user.id,
            CallOperation.kind == 'call', CallOperation.idempotency_key == idempotency_key))
        return {'call': summary(owned(db, cid, op.id, request, user), media=True) if op else None}


@router.get('/calls/{call_id}')
def call_status(cid: str, call_id: str, request: Request, response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    with Session.begin() as db:
        return summary(owned(db, cid, call_id, request, user), media=True)


@router.post('/calls/{call_id}/heartbeat')
def heartbeat(cid: str, call_id: str, data: HeartbeatInput, request: Request, response: Response, user=Depends(current_user)):
    write_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    with Session.begin() as db:
        owned(db, cid, call_id, request, user)
        op = calling.heartbeat(db, tenant_id=user.tenant_id, operation_id=call_id,
                              **credentials(request, user), browser_state=data.browser_state)
        return summary(op)


@router.post('/calls/{call_id}/terminate')
def terminate(cid: str, call_id: str, data: OperationInput, request: Request, response: Response, user=Depends(current_user)):
    write_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    with Session.begin() as db:
        op = owned(db, cid, call_id, request, user)
        if op.active and op.state != 'terminating':
            calling.update_operation(db, op, state='terminating')
        result = summary(op)
    from .calling_reconcile import terminate_one
    terminate_one(call_id)
    return result
