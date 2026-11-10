"""Entrega em partes, configurada no banco por empresa, sem nova inferência."""
import re
from datetime import timedelta
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import Message, Conversation, now
from .media_models import ConversationControl
from .tenant_runtime import enabled


class ReplyDelivery(Base):
    __tablename__ = "tenant_reply_delivery"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    max_chars: Mapped[int] = mapped_column(Integer, default=600)
    typing: Mapped[bool] = mapped_column(Boolean, default=True)


class ReplyPart(Base):
    __tablename__ = "reply_parts"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)


def split_reply(text, limit):
    # URLs e palavras permanecem inteiras. Parágrafos curtos ficam juntos.
    if limit <= 0 or len(text) <= limit:
        return [text]
    units = re.split(r"\n\s*\n", text.strip())
    parts, current = [], ""
    for unit in units:
        chunks = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý0-9])", unit)
        for chunk in chunks:
            separator = "\n\n" if current and chunk == chunks[0] else " "
            if current and len(current) + len(separator) + len(chunk) > limit:
                parts.append(current)
                current = ""
            # Frases enormes podem ser divididas entre palavras, nunca dentro de um link.
            if len(chunk) > limit:
                for word in chunk.split():
                    if current and len(current) + 1 + len(word) > limit:
                        parts.append(current)
                        current = ""
                    current = current + " " + word if current else word
            else:
                current = current + separator + chunk if current else chunk
    if current:
        parts.append(current)
    return parts or [text]


def save_reply(db, tid, cid, text, revision):
    setting = db.get(ReplyDelivery, tid)
    parts = split_reply(text, max(200, min(setting.max_chars, 1500))) if setting else [text]
    timestamp = now()
    rows = []
    for index, part in enumerate(parts):
        row = Message(tenant_id=tid, conversation_id=cid, sender="lumi", content=part,
                      created_at=timestamp + timedelta(microseconds=index))
        db.add(row)
        db.flush()
        if setting:
            db.add(ReplyPart(message_id=row.id, revision=revision))
        rows.append(row)
    return rows


def may_deliver(db, message):
    part = db.get(ReplyPart, message.id)
    if not part:
        return True
    conversation = db.get(Conversation, message.conversation_id)
    state = db.get(ConversationControl, message.conversation_id)
    return bool(conversation and conversation.tenant_id == message.tenant_id
                and conversation.status == "lumi" and enabled(db, message.tenant_id)
                and (state.revision if state else 0) == part.revision)
