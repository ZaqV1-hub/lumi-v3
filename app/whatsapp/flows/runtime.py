"""Flows reuse the conversation engine in a separate, non-WhatsApp thread."""
import hashlib
import logging
import secrets
from datetime import timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select

from ...db import Session
from ...models import Conversation, Message, Tenant, VisitorSession, now
from ...spam import admission_lock
from ...tenant_runtime import assistant_name, enabled
from ..models import Channel, Chat
from .config import channel_config
from .models import FlowLaunch, FlowSession, FlowTurn

log = logging.getLogger(__name__)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def source_chat(db, tid, cid):
    row = db.scalar(select(FlowSession).where(FlowSession.tenant_id == tid,
        FlowSession.conversation_id == cid))
    chat = db.get(Chat, row.source_id) if row else None
    channel = db.get(Channel, row.phone_number_id) if row else None
    original = db.get(Conversation, row.source_id) if row else None
    flow_conversation = db.get(Conversation, cid)
    return chat if (chat and channel and original and channel.tenant_id == tid
        and original.tenant_id == tid and flow_conversation and flow_conversation.tenant_id == tid
        and flow_conversation.contact_id == original.contact_id
        and chat.phone_number_id == row.phone_number_id) else None


def intercept(db, channel, chat, incoming):
    config = channel_config(channel.phone_number_id)
    if not config or config['tenant_id'] != channel.tenant_id:
        return False
    if config.get('recipients') and chat.sender not in config['recipients']:
        return False
    original = db.get(Conversation, chat.id)
    if original.status == 'humano' or not enabled(db, channel.tenant_id):
        return False
    if incoming.get('type') == 'interactive' and incoming.get('interactive', {}).get('type') == 'nfm_reply':
        return True  # Completion is not a new question for the AI.
    if incoming.get('type') != 'text':
        return False
    recent = db.scalar(select(FlowLaunch).join(Message, Message.id == FlowLaunch.message_id)
        .where(Message.tenant_id == channel.tenant_id, Message.conversation_id == chat.id)
        .order_by(Message.created_at.desc()).limit(1))
    if recent:
        anchor = db.get(Message, recent.message_id)
        if now() - utc(anchor.created_at) < timedelta(minutes=2):
            return True
    token = secrets.token_urlsafe(32)
    visitor_token = secrets.token_urlsafe(32)
    c = Conversation(tenant_id=channel.tenant_id, contact_id=original.contact_id)
    db.add(c); db.flush()
    # Deliberately no Chat row: engine/operator messages never enter WhatsApp Outbox.
    db.add(VisitorSession(token=visitor_token, tenant_id=channel.tenant_id, conversation_id=c.id))
    session = FlowSession(tenant_id=channel.tenant_id, conversation_id=c.id,
        source_id=chat.id, phone_number_id=channel.phone_number_id, token_hash=digest(token),
        nonce=secrets.token_urlsafe(24), expires_at=now()+timedelta(hours=24))
    db.add(session); db.flush()
    db.add(Message(tenant_id=channel.tenant_id, conversation_id=chat.id,
        sender='cliente', content=incoming['text']['body'][:10000]))
    name = assistant_name(db.get(Tenant, channel.tenant_id))
    launch = Message(tenant_id=channel.tenant_id, conversation_id=chat.id, sender='lumi',
        content=f'Abra o atendimento de teste com a {name} pelo botão abaixo. As respostas aparecem na tela do atendimento.')
    db.add(launch); db.flush()
    db.add(FlowLaunch(message_id=launch.id, session_id=session.id, token=token, flow_id=str(config['flow_id'])))
    return True


def require_session(db, phone, config, token):
    if not isinstance(token, str) or not 20 <= len(token) <= 120:
        raise HTTPException(403, 'Sessão inválida')
    row = db.scalar(select(FlowSession).where(FlowSession.token_hash == digest(token)).with_for_update())
    if (not row or row.tenant_id != config['tenant_id'] or row.phone_number_id != phone
        or utc(row.expires_at) <= now() or not enabled(db, row.tenant_id)
        or not source_chat(db, row.tenant_id, row.conversation_id)):
        raise HTTPException(403, 'Sessão indisponível')
    c = db.get(Conversation, row.conversation_id)
    original = db.get(Conversation, row.source_id)
    if not c or c.tenant_id != row.tenant_id or c.contact_id != original.contact_id:
        raise HTTPException(403, 'Sessão inválida')
    if original.status == 'humano':
        raise HTTPException(409, 'O atendimento está com a equipe no WhatsApp')
    return row


def screen(db, row, note=''):
    turns = list(db.scalars(select(FlowTurn).where(FlowTurn.session_id == row.id)
        .order_by(FlowTurn.created_at.desc()).limit(1)))
    pending = bool(turns and turns[0].state in ('preparing', 'generating'))
    history = list(db.scalars(select(Message).where(Message.tenant_id == row.tenant_id,
        Message.conversation_id == row.conversation_id).order_by(Message.created_at.desc(), Message.id.desc()).limit(6)))[::-1]
    name = assistant_name(db.get(Tenant, row.tenant_id))
    lines = [('Você' if m.sender == 'cliente' else name if m.sender == 'lumi' else 'Equipe')
        + ': ' + m.content[:900] for m in history]
    if pending:
        lines.append('Preparando a resposta. Toque em Ver resposta para atualizar.')
    elif turns and turns[0].state == 'interrupted':
        lines.append('A resposta foi interrompida. Consulte o histórico antes de repetir um pedido.')
    if note:
        lines.append(note)
    text = '\n\n'.join(lines)[-3500:] or 'Como posso ajudar? Digite sua pergunta abaixo.'
    return {'version':'3.0', 'screen':'CHAT', 'data':{'history':text,
        'nonce':row.nonce, 'can_ask':not pending, 'question_init':'',
        'action_label':'Ver resposta' if pending else 'Enviar pergunta'}}


def exchange(phone, config, payload, pool):
    if payload.get('action') == 'ping':
        return {'version':'3.0','data':{'status':'active'}}
    if payload.get('action') not in ('INIT', 'BACK', 'data_exchange'):
        raise HTTPException(400, 'Ação inválida')
    with admission_lock:
        receipt = None
        with Session.begin() as db:
            row = require_session(db, phone, config, payload.get('flow_token'))
            if payload['action'] in ('INIT','BACK'):
                return screen(db, row)
            data = payload.get('data', {})
            if not isinstance(data, dict):
                raise HTTPException(400, 'Dados inválidos')
            if data.get('operation') == 'close':
                return {'version':'3.0','screen':'FINISH','data':{}}
            question = data.get('question', '')
            if not isinstance(question, str) or len(question) > 2000:
                raise HTTPException(400, 'Pergunta inválida')
            nonce = data.get('nonce', '')
            if not isinstance(nonce, str) or not 1 <= len(nonce) <= 64:
                raise HTTPException(400, 'Pedido inválido')
            existing = db.scalar(select(FlowTurn).where(FlowTurn.session_id == row.id, FlowTurn.nonce == nonce))
            if existing:
                # A retry cannot create another question, tool operation, or inference.
                return screen(db, row)
            if nonce != row.nonce:
                return screen(db, row, 'A tela foi atualizada. Confira o histórico antes de enviar novamente.')
            pending = db.scalar(select(FlowTurn.id).where(FlowTurn.session_id == row.id,
                FlowTurn.state.in_(('preparing','generating'))).limit(1))
            if pending or not question.strip():
                return screen(db, row)
            count = db.scalar(select(func.count()).select_from(FlowTurn).where(FlowTurn.session_id == row.id))
            if count >= 30:
                return screen(db, row, 'Limite desta sessão de teste atingido. Abra uma nova sessão pelo WhatsApp.')
            turn = FlowTurn(session_id=row.id, nonce=nonce, question_hash=digest(question.strip()))
            db.add(turn); db.flush()
            turn_id, sid, cid, tid = turn.id, row.id, row.conversation_id, row.tenant_id
            visitor_token = db.scalar(select(VisitorSession.token).where(
                VisitorSession.conversation_id == cid, VisitorSession.tenant_id == tid))
        from ...client import receive_message
        from ...schemas import TextInput
        try:
            receipt = receive_message(visitor_token, TextInput(content=question.strip()))
            with Session.begin() as db:
                turn = db.get(FlowTurn, turn_id)
                turn.message_id = receipt.get('message_id')
                turn.state = 'generating' if receipt.get('accepted') else 'completed'
                db.get(FlowSession, sid).nonce = secrets.token_urlsafe(24)
            if receipt.get('accepted'):
                pool.submit(generate, turn_id, receipt)
        except Exception:
            if receipt and receipt.get('accepted'):
                from ...spam import cancel_turn, finish
                cancel_turn(receipt['contact_id'], receipt['message_id']); finish(receipt['contact_id'])
            with Session.begin() as db:
                db.get(FlowTurn, turn_id).state = 'interrupted'
            log.warning('Flow generation could not be scheduled; turn=%s', turn_id)
        with Session.begin() as db:
            return screen(db, require_session(db, phone, config, payload.get('flow_token')))


def generate(turn_id, receipt):
    state = 'interrupted'
    try:
        with Session() as db:
            turn = db.get(FlowTurn, turn_id)
            session = db.get(FlowSession, turn.session_id) if turn else None
            config = channel_config(session.phone_number_id) if session else None
            original = db.get(Conversation, session.source_id) if session else None
            if (not config or config['tenant_id'] != receipt['tenant_id']
                or not original or original.status == 'humano'
                or not source_chat(db, receipt['tenant_id'], receipt['conversation_id'])):
                from ...spam import cancel_turn, finish
                cancel_turn(receipt['contact_id'], receipt['message_id']); finish(receipt['contact_id'])
                return
        from ...client import process_message
        process_message(receipt)
        state = 'completed'
    except Exception:
        log.warning('Flow generation interrupted; turn=%s', turn_id)
    finally:
        with Session.begin() as db:
            row = db.get(FlowTurn, turn_id)
            if row:
                row.state = state
