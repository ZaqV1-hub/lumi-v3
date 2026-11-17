"""Direct Meta Calling contract; credentials stay server-side, writes never retry."""
from datetime import datetime, timezone
import logging
import re

import httpx

from .config import access_token, required

log = logging.getLogger(__name__)


class GraphError(RuntimeError):
    def __init__(self, code, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


def _request(phone_id, token_env, endpoint, *, payload=None, params=None):
    if not isinstance(phone_id, str) or not re.fullmatch(r'\d{1,80}', phone_id):
        raise GraphError('invalid_channel')
    try:
        version = required('WHATSAPP_GRAPH_VERSION')
        token = access_token(token_env)
    except RuntimeError:
        raise GraphError('channel_not_configured') from None
    if not re.fullmatch(r'v\d+\.\d+', version):
        raise GraphError('channel_not_configured')
    writing = payload is not None
    try:
        with httpx.Client(timeout=20, follow_redirects=False,
                          headers={'Authorization':'Bearer '+token, 'Content-Type':'application/json'}) as client:
            response = client.request('POST' if writing else 'GET',
                f'https://graph.facebook.com/{version}/{phone_id}/{endpoint}', json=payload, params=params)
    except httpx.RequestError:
        raise GraphError('service_unavailable', uncertain=writing) from None
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code != 200 or (isinstance(data, dict) and 'error' in data):
        error = data.get('error', {}) if isinstance(data, dict) else {}
        code = error.get('code') if isinstance(error, dict) else None
        code = code if type(code) is int else None
        subcode = error.get('error_subcode') if isinstance(error, dict) else None
        subcode = subcode if type(subcode) is int else None
        log.warning('WhatsApp calling rejected: endpoint=%s action=%s http_status=%s meta_code=%s meta_subcode=%s',
                    endpoint, payload.get('action') if writing else None, response.status_code, code, subcode)
        public = {138006:'permission_required', 190:'channel_unauthorized', 10:'channel_unauthorized',
                  200:'channel_unauthorized', 4:'rate_limited', 80007:'rate_limited',
                  131047:'message_window_closed', 131048:'rate_limited', 138037:'rate_limited'}.get(code)
        public = public or ('rate_limited' if response.status_code == 429 else
                           'service_unavailable' if response.status_code >= 500 else 'request_rejected')
        raise GraphError(public, uncertain=writing and response.status_code >= 500)
    if not isinstance(data, dict):
        raise GraphError('invalid_response', uncertain=writing)
    return data


def _recipient(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{7,20}', value):
        raise GraphError('invalid_recipient')
    return value


def _external_id(data, key):
    items = data.get(key)
    value = items[0].get('id') if isinstance(items, list) and items and isinstance(items[0], dict) else None
    if not isinstance(value, str) or not 1 <= len(value) <= 240:
        raise GraphError('invalid_response', uncertain=True)
    return value


def get_permission(phone_id, token_env, recipient):
    data = _request(phone_id, token_env, 'call_permissions', params={'user_wa_id':_recipient(recipient)})
    permission = data.get('permission')
    if not isinstance(permission, dict) or permission.get('status') not in ('no_permission','temporary','permanent'):
        raise GraphError('invalid_response')
    status = permission['status']
    expires = None
    if status == 'temporary':
        stamp = permission.get('expiration_time')
        if type(stamp) is not int:
            raise GraphError('invalid_response')
        try:
            expires = datetime.fromtimestamp(stamp, timezone.utc)
        except (ValueError, OverflowError, OSError):
            raise GraphError('invalid_response') from None
    state = 'absent' if status == 'no_permission' else 'granted'
    if expires and expires <= datetime.now(timezone.utc):
        state = 'expired'
    actions = data.get('actions', [])
    if not isinstance(actions, list) or any(not isinstance(a, dict) for a in actions):
        raise GraphError('invalid_response')
    def allowed(name):
        matches = [a for a in actions if a.get('action_name') == name]
        return len(matches) == 1 and matches[0].get('can_perform_action') is True
    can_call = state == 'granted' and allowed('start_call')
    return {'state':state, 'permanent':status == 'permanent', 'expires_at':expires,
            'can_request':allowed('send_call_permission_request'), 'can_call':can_call,
            'block_reason':None if can_call else 'permission_required' if state != 'granted' else 'calling_restricted'}


def request_permission(phone_id, token_env, recipient, operation_id):
    # Meta documents context.id correlation, not an opaque request token here.
    data = _request(phone_id, token_env, 'messages', payload={
        'messaging_product':'whatsapp','recipient_type':'individual','to':_recipient(recipient),
        'type':'interactive','interactive':{'type':'call_permission_request','action':{'name':'call_permission_request'}}})
    return _external_id(data, 'messages')


def connect(phone_id, token_env, recipient, sdp_offer, operation_id):
    if not isinstance(sdp_offer, str) or not 1 <= len(sdp_offer.encode()) <= 65536:
        raise GraphError('invalid_sdp')
    if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 512:
        raise GraphError('invalid_operation')
    data = _request(phone_id, token_env, 'calls', payload={
        'messaging_product':'whatsapp','to':_recipient(recipient),'action':'connect',
        'session':{'sdp_type':'offer','sdp':sdp_offer},'biz_opaque_callback_data':operation_id})
    return _external_id(data, 'calls')


def _end(phone_id, token_env, external_id, action):
    if not isinstance(external_id, str) or not 1 <= len(external_id) <= 240:
        raise GraphError('invalid_call')
    data = _request(phone_id, token_env, 'calls', payload={
        'messaging_product':'whatsapp','call_id':external_id,'action':action})
    if data.get('success') is not True:
        raise GraphError('invalid_response', uncertain=True)


def terminate(phone_id, token_env, external_id):
    _end(phone_id, token_env, external_id, 'terminate')


def reject(phone_id, token_env, external_id):
    _end(phone_id, token_env, external_id, 'reject')
