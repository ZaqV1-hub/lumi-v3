"""Display existing WhatsApp calls in the admin conversation timeline only."""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from ..conversations import timestamp
from ..models import User
from .calling import schema_ready, utc
from .calling_models import CallOperation


CALL_LABELS = {
    'ringing': 'chamando',
    'accepted': 'atendida',
    'terminating': 'encerrando',
    'ended': 'encerrada',
    'rejected': 'recusada',
    'failed': 'falhou',
    'canceled': 'cancelada',
}


def call_timeline(db, tenant_id, conversation_id=None):
    events = defaultdict(list)
    if not schema_ready(db):
        return events
    query = (
        select(CallOperation, User.name)
        .join(User, User.id == CallOperation.operator_id)
        .where(CallOperation.tenant_id == tenant_id, CallOperation.kind == 'call',
               CallOperation.state.in_(CALL_LABELS))
    )
    if conversation_id:
        query = query.where(CallOperation.conversation_id == conversation_id)
    for call, operator in db.execute(query):
        label = CALL_LABELS[call.state]
        if call.connected_at and call.ended_at:
            seconds = max(0, int((utc(call.ended_at) - utc(call.connected_at)).total_seconds()))
            minutes, seconds = divmod(seconds, 60)
            label += f' · {minutes}:{seconds:02d}'
        events[call.conversation_id].append({
            'id': f'call:{call.id}',
            'sender': 'sistema',
            'event_kind': 'whatsapp_call',
            'content': f'Ligação pelo WhatsApp por {operator} · {label}',
            'created_at': timestamp(call.created_at),
        })
    return events


def with_calls(items, calls):
    if not calls:
        return items
    return sorted([*items, *calls], key=lambda item: (datetime.fromisoformat(item['created_at']), item['id']))
