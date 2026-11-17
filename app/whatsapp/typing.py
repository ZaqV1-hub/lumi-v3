"""Sinal de processamento da Meta: opcional e sem bloquear o atendimento."""
import logging
import httpx
from ..db import Session
from ..models import Conversation
from ..media_models import ContactGate, ConversationControl
from ..reply_delivery import ReplyDelivery
from ..tenant_runtime import enabled
from .models import Chat, Channel
from .config import required, access_token
from .graph import check
import re

log = logging.getLogger(__name__)


def notify_processing(receipt):
    external_id = receipt.get("whatsapp_external_id")
    if not external_id:
        return
    try:
        with Session() as db:
            tid, cid = receipt["tenant_id"], receipt["conversation_id"]
            settings = db.get(ReplyDelivery, tid)
            conversation = db.get(Conversation, cid)
            state = db.get(ConversationControl, cid)
            gate = db.get(ContactGate, receipt["contact_id"])
            chat = db.get(Chat, cid)
            channel = db.get(Channel, chat.phone_number_id) if chat else None
            if not (settings and settings.typing and conversation and conversation.tenant_id == tid
                    and conversation.status == "lumi" and enabled(db, tid)
                    and (state.revision if state else 0) == receipt["revision"]
                    and not (gate and gate.blocked) and channel and channel.tenant_id == tid):
                return
            phone_id, token_env = channel.phone_number_id, channel.token_env
        version = required("WHATSAPP_GRAPH_VERSION")
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise ValueError("graph_version")
        with httpx.Client(timeout=2, headers={"Authorization": "Bearer " + access_token(token_env)}) as client:
            check(client.post(f"https://graph.facebook.com/{version}/{phone_id}/messages", json={
                "messaging_product": "whatsapp", "status": "read", "message_id": external_id,
                "typing_indicator": {"type": "text"}}))
    except Exception:
        # Nunca registrar token, resposta Graph ou dados do cliente.
        log.warning("WhatsApp typing indicator failed; reply processing continues")
