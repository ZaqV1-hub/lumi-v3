"""Controle por contato; a seção crítica é curta e não inclui inferência."""

import threading
from collections import deque
from contextlib import contextmanager
from .db import Session
from .media_models import ContactGate, TenantPreferences, ConversationControl
from .models import Message

admission_lock = threading.RLock()
_turns = {}
_changed = threading.Condition(admission_lock)


def reserve_turn(contact_id, message_id):
    with _changed:
        _turns.setdefault(contact_id, deque()).append(message_id)


def cancel_turn(contact_id, message_id):
    with _changed:
        queue = _turns.get(contact_id)
        if queue and message_id in queue:
            queue.remove(message_id)
            if not queue:
                del _turns[contact_id]
        _changed.notify_all()


@contextmanager
def generation_lock(contact_id, message_id):
    with _changed:
        _changed.wait_for(lambda: _turns.get(contact_id, [None])[0] == message_id)
    try:
        yield
    finally:
        cancel_turn(contact_id, message_id)


def control(db, cid):
    row = db.get(ConversationControl, cid)
    if not row:
        row = ConversationControl(conversation_id=cid, revision=0)
        db.add(row)
        db.flush()
    return row


def admit(db, tid, cid, contact_id):
    gate = db.get(ContactGate, contact_id, with_for_update=True)
    if not gate:
        gate = ContactGate(contact_id=contact_id, pending=0, warnings=0, blocked=False)
        db.add(gate)
    if gate.blocked:
        return False
    settings = db.get(TenantPreferences, tid)
    limit = settings.max_pending if settings else 3
    if gate.pending >= limit:
        gate.warnings += 1
        if gate.warnings == 1:
            text = f"Só alguns instantes. Ainda estou respondendo às suas últimas {limit} mensagens. Aguarde um pouquinho."
        elif gate.warnings == 2:
            text = "Por favor, aguarde as respostas. Se continuar enviando mensagens agora, vou bloquear seu atendimento."
        else:
            gate.blocked = True
            text = "Seu atendimento foi bloqueado por excesso de mensagens. A equipe poderá liberar o acesso."
        db.add(
            Message(tenant_id=tid, conversation_id=cid, sender="sistema", content=text)
        )
        return False
    gate.pending += 1
    return True


def finish(contact_id):
    with admission_lock, Session.begin() as db:
        gate = db.get(ContactGate, contact_id, with_for_update=True)
        gate.pending = max(0, gate.pending - 1)
        if not gate.pending and not gate.blocked:
            gate.warnings = 0
