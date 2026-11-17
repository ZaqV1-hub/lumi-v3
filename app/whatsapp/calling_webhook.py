"""Calling events enter here only after the entire webhook signature is verified."""
from datetime import datetime, timezone
import hashlib
import json
import logging
from dataclasses import replace

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ..db import Session
from . import calling_graph
from .calling import NormalizedCallEvent, apply_call_event, channel_enabled
from .calling_models import CallEvent, CallPermission, CallingChannel
from .models import Channel


logger = logging.getLogger(__name__)


def _string(value, limit=240):
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise ValueError('Invalid calling field')
    return value


def _timestamp(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ValueError('Invalid calling timestamp')
    try:
        return datetime.fromtimestamp(int(value), timezone.utc)
    except (OverflowError, OSError) as error:
        raise ValueError('Invalid calling timestamp') from error


def _event_id(parts):
    return hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()


def _call_event(item, *, status=False):
    external = _string(item.get('id'))
    occurred = _timestamp(item.get('timestamp'))
    answer = None
    if status:
        if item.get('type') != 'call':
            return None
        state = {'RINGING':'ringing','ACCEPTED':'accepted','REJECTED':'rejected'}.get(item.get('status'))
        recipient = item.get('recipient_id')
        event_name = 'status'
    else:
        if item.get('direction') != 'BUSINESS_INITIATED':
            return None
        recipient = item.get('to')
        event_name = item.get('event')
        if event_name == 'connect':
            session = item.get('session')
            if not isinstance(session, dict) or session.get('sdp_type') != 'answer':
                raise ValueError('Invalid answer')
            answer = _string(session.get('sdp'), 65536)
            if len(answer.encode()) > 65536:
                raise ValueError('Invalid answer size')
            state = 'initiating'
        elif event_name == 'terminate':
            state = {'COMPLETED':'ended','FAILED':'failed'}.get(item.get('status'))
        else:
            return None
    if state is None:
        return None
    recipient = _string(recipient, 40)
    operation_id = item.get('biz_opaque_callback_data')
    if operation_id is not None:
        operation_id = _string(operation_id, 512)
    return NormalizedCallEvent(event_id=_event_id([external,event_name,item.get('status'),item.get('timestamp')]),
        kind='call',state=state,occurred_at=occurred,external_id=external,
        operation_id=operation_id,recipient=recipient,answer_sdp=answer)


def is_permission_reply(message):
    return isinstance(message, dict) and isinstance(message.get('interactive'), dict) and message['interactive'].get('type') == 'call_permission_reply'


def _permission_event(message):
    reply = message['interactive'].get('call_permission_reply')
    if not isinstance(reply, dict) or reply.get('response') not in {'accept','reject'} or reply.get('response_source') not in {'user_action','automatic'}:
        raise ValueError('Invalid permission reply')
    permanent = reply.get('is_permanent') is True
    expires = None
    if reply['response'] == 'accept':
        if type(reply.get('is_permanent')) is not bool:
            raise ValueError('Invalid permission duration')
        if not permanent:
            expires = _timestamp(reply.get('expiration_timestamp'))
        state = 'granted'
    else:
        state = 'revoked' if reply['response_source'] == 'automatic' else 'denied'
        permanent = False
    context = message.get('context', {})
    if not isinstance(context, dict):
        raise ValueError('Invalid permission context')
    external = context.get('id')
    if external is not None:
        external = _string(external)
    return NormalizedCallEvent(event_id=_event_id(['permission',_string(message.get('id'))]),
        kind='permission',state=state,occurred_at=_timestamp(message.get('timestamp')),
        recipient=_string(message.get('from'),40),external_id=external,permanent=permanent,expires_at=expires)


def process_permission(phone_id, message):
    with Session.begin() as db:
        channel = db.get(Channel,phone_id)
        if not channel or not channel_enabled(db,tenant_id=channel.tenant_id,phone_number_id=phone_id):
            return
        try:
            event = _permission_event(message)
        except (ValueError, TypeError, KeyError, AttributeError):
            logger.warning('calling_permission_invalid')
            return
        previous = db.get(CallPermission,(channel.tenant_id,phone_id,event.recipient))
        if event.state == 'denied' and previous and previous.state in {'granted','revoked'}:
            event = replace(event,state='revoked')
        apply_call_event(db,channel=channel,event=event)


def _incoming(phone_id, item):
    external = _string(item.get('id'))
    occurred = _timestamp(item.get('timestamp'))
    event_id = 'incoming:'+_event_id([external])
    if item.get('event') != 'connect':
        if item.get('event') == 'terminate' and item.get('status') in {'COMPLETED','FAILED'}:
            with Session.begin() as db:
                channel = db.get(Channel,phone_id)
                if channel and channel_enabled(db,tenant_id=channel.tenant_id,phone_number_id=phone_id):
                    row = db.get(CallEvent,(phone_id,event_id))
                    if row:
                        row.state = 'ended' if item['status'] == 'COMPLETED' else 'failed'
        return
    try:
        with Session.begin() as db:
            channel = db.get(Channel,phone_id)
            if not channel or not channel_enabled(db,tenant_id=channel.tenant_id,phone_number_id=phone_id):
                return
            db.execute(update(CallingChannel).where(CallingChannel.phone_number_id == phone_id)
                .values(updated_at=CallingChannel.updated_at))
            if not channel_enabled(db,tenant_id=channel.tenant_id,phone_number_id=phone_id) or db.get(CallEvent,(phone_id,event_id)):
                return
            db.add(CallEvent(phone_number_id=phone_id,event_id=event_id,tenant_id=channel.tenant_id,
                            external_id=external,kind='incoming',state='rejecting',occurred_at=occurred))
            token_env = channel.token_env
    except IntegrityError:
        return
    # Persist before the effect: a timeout or crash must never cause a second rejection.
    state = 'rejected'
    try:
        calling_graph.reject(phone_id,token_env,external)
    except calling_graph.GraphError as error:
        state = 'uncertain' if error.uncertain else 'failed'
        logger.warning('calling_incoming_reject_%s',error.code)
    with Session.begin() as db:
        row = db.get(CallEvent,(phone_id,event_id))
        if row and row.state == 'rejecting':
            row.state = state


def process_calls(phone_id, value):
    with Session() as db:
        channel = db.get(Channel,phone_id)
        if not channel or not channel_enabled(db,tenant_id=channel.tenant_id,phone_number_id=phone_id):
            return
    for key in ('calls','statuses'):
        items = value.get(key, [])
        if not isinstance(items,list):
            logger.warning('calling_event_invalid')
            continue
        for item in items:
            try:
                if not isinstance(item,dict):
                    raise ValueError('Invalid calling event')
                if key == 'calls' and item.get('direction') == 'USER_INITIATED':
                    _incoming(phone_id,item)
                    continue
                event = _call_event(item,status=key == 'statuses')
            except (ValueError,TypeError,KeyError,AttributeError):
                logger.warning('calling_event_invalid')
                continue
            if event:
                with Session.begin() as db:
                    channel = db.get(Channel,phone_id)
                    if channel:
                        apply_call_event(db,channel=channel,event=event)
