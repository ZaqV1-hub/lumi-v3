"""Paginated admin conversations and server-side dashboard totals."""
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select

from .access import current_user
from .admin import _conversation_name
from .channels import channel_name
from .conversations import before_cursor, conversation, messages, timestamp
from .db import Session
from .instagram.comment_models import CommentJob
from .instagram.models import Chat as InstagramChat
from .media_models import ContactGate, ConversationControl
from .models import Contact, Conversation, FeatureCall, Message, User
from .onboarding import profile_state
from .visit_goal import confirmed_conversations
from .whatsapp.calling_timeline import call_timeline, with_calls
from .whatsapp.models import ArchivedChat, Chat as WhatsAppChat

router = APIRouter(prefix="/api/admin")
ZONE = ZoneInfo("America/Sao_Paulo")


def cursor_value(value, key):
    return json.dumps([value, key], separators=(",", ":"))


def read_cursor(raw, *, event=False):
    if raw is None:
        return None
    try:
        parts = json.loads(raw)
        if not isinstance(parts, list) or len(parts) != 2:
            raise ValueError
        value, key = parts
        if not isinstance(value, str) or not isinstance(key, str):
            raise ValueError
        if not key or len(key) > (41 if event else 36):
            raise ValueError
        at = datetime.fromisoformat(value)
        if not at.tzinfo or not 1 < at.year < 9999:
            raise ValueError
        return at.astimezone(timezone.utc), key
    except (ValueError, OverflowError):
        raise HTTPException(422, "Página inválida") from None


def latest_at(tid):
    recent = (select(Message.created_at)
              .where(Message.tenant_id == tid, Message.conversation_id == Conversation.id)
              .order_by(Message.created_at.desc(), Message.id.desc()).limit(1).scalar_subquery())
    return func.coalesce(recent, Conversation.created_at)


def sort_rows(db, tid, status, query, after, limit):
    waiting = status == "aguardando"
    ordered_at = latest_at(tid)
    if waiting:
        requested_at = (select(func.max(FeatureCall.created_at))
                        .where(FeatureCall.tenant_id == tid, FeatureCall.conversation_id == Conversation.id,
                               FeatureCall.feature == "handover").scalar_subquery())
        ordered_at = func.coalesce(requested_at, Conversation.created_at)
    # Keep distinct people in the general list while preserving every active ticket.
    keys = [Conversation.id.label("cid"), ordered_at.label("ordered_at")]
    if not status:
        keys.append(func.row_number().over(
            partition_by=Conversation.contact_id,
            order_by=(ordered_at.desc(), Conversation.id.desc()),
        ).label("contact_rank"))
    candidates = select(*keys).where(Conversation.tenant_id == tid)
    if status:
        candidates = candidates.where(Conversation.status == status)
    if query:
        term = query.lstrip("#").strip().lower()
        candidates = candidates.join(Contact, and_(Contact.tenant_id == tid, Contact.id == Conversation.contact_id))
        candidates = candidates.where(or_(
            func.lower(Contact.name).contains(query.lower(), autoescape=True)
            if not re.fullmatch(r"[+#\d().\s-]+", query) else False,
            Conversation.contact_id.contains(term, autoescape=True) if term else False,
            Conversation.id.contains(term, autoescape=True) if term else False,
        ))
    scope = candidates.subquery()
    at, cid = scope.c.ordered_at, scope.c.cid
    out = select(cid, at)
    if not status:
        out = out.where(scope.c.contact_rank == 1)
    if after:
        bound, key = after
        out = out.where(or_(at > bound, and_(at == bound, cid > key)) if waiting else before_cursor(at, cid, after))
    order = (at.asc(), cid.asc()) if waiting else (at.desc(), cid.desc())
    return db.execute(out.order_by(*order).limit(limit)).all()


def preview(db, tid, cid, period=None):
    rows = messages(db, tid, cid, limit=1, period=period)
    if not rows:
        return None
    row = rows[0]
    return {key: row[key] for key in ("id", "sender", "created_at", "attachment_name", "attachment_kind")} | {
        "content": row["content"][:200],
    }


def conversation_summary(db, user, c, confirmed, *, detail=False, period=None):
    tid = user.tenant_id
    contact = db.get(Contact, c.contact_id)
    channel = channel_name(db, c.id)
    profile = profile_state(db, tid, c.contact_id) if detail or channel == "whatsapp" else {}
    state = db.get(ConversationControl, c.id) if c.status == "humano" else None
    operator = db.get(User, state.operator_id) if state and state.operator_id else None
    item = {
        "id": c.id, "contact_id": c.contact_id, "channel": channel, "status": c.status,
        "role": contact.role, "created_at": timestamp(c.created_at),
        "name": _conversation_name(contact.name, channel, profile),
        "visit_confirmed": c.id in confirmed,
        "operator_name": operator.name if operator else None,
        "can_reply": bool(state and state.operator_id == user.id and user.console_role != "leitura"),
        "blocked": bool((gate := db.get(ContactGate, c.contact_id)) and gate.blocked),
    }
    if detail:
        item["profile"] = profile
    else:
        item["last_message"] = preview(db, tid, c.id, period)
    return item


@router.get("/conversation-page")
def conversation_page(
    status: Literal["", "lumi", "aguardando", "humano"] = "",
    q: str = Query("", max_length=160),
    cursor: str | None = Query(None, max_length=160),
    user=Depends(current_user),
):
    with Session() as db:
        tid = user.tenant_id
        rows = sort_rows(db, tid, status, q.strip(), read_cursor(cursor), 11)
        ids = [cid for cid, _ in rows[:10]]
        confirmed = confirmed_conversations(db, tid, conversation_ids=ids)
        items = [conversation_summary(db, user, db.get(Conversation, cid), confirmed) for cid in ids]
        next_cursor = cursor_value(timestamp(rows[9][1]), rows[9][0]) if len(rows) > 10 else None
        count = db.scalar(select(func.count(func.distinct(Conversation.contact_id))).where(
            Conversation.tenant_id == tid, Conversation.status == "aguardando"))
        return {"items": items, "next_cursor": next_cursor, "waiting_count": count}


@router.get("/conversations/{cid}/history")
def conversation_history(cid: str, cursor: str | None = Query(None, max_length=160), user=Depends(current_user)):
    with Session() as db:
        tid = user.tenant_id
        c = conversation(db, tid, cid)
        before = read_cursor(cursor, event=True)
        items = with_calls(messages(db, tid, c.id, limit=21, before=before),
                           call_timeline(db, tid, c.id, limit=21, before=before).get(c.id))
        page = items[-20:]
        next_cursor = cursor_value(page[0]["created_at"], page[0]["id"]) if len(items) > 20 else None
        result = {"messages": page, "next_cursor": next_cursor}
        if before is None:
            result["conversation"] = conversation_summary(
                db, user, c, confirmed_conversations(db, tid, conversation_id=c.id), detail=True)
        return result


def channel_expression():
    def linked(model, key="id"):
        return select(getattr(model, key)).where(getattr(model, key) == Conversation.id).exists()
    return case(
        (or_(linked(WhatsAppChat), linked(ArchivedChat)), "whatsapp"),
        (linked(InstagramChat), "instagram"),
        (linked(CommentJob, "conversation_id"), "instagram_comment"),
        else_="simulator",
    )


@router.get("/dashboard")
def dashboard(start: date, end: date, user=Depends(current_user)):
    if start > end or end >= date.max or start <= date.min:
        raise HTTPException(422, "Período inválido")
    at = datetime.combine(start, time.min, ZONE).astimezone(timezone.utc)
    until = datetime.combine(end + timedelta(days=1), time.min, ZONE).astimezone(timezone.utc)
    tid = user.tenant_id
    incoming = (
        select(Message.conversation_id.label("cid"), func.count().label("messages"), func.max(Message.created_at).label("latest"))
        .where(Message.tenant_id == tid, Message.sender == "cliente", Message.created_at >= at, Message.created_at < until)
        .group_by(Message.conversation_id).subquery()
    )
    with Session() as db:
        channels, statuses, received = {}, {}, 0
        channel = channel_expression().label("channel")
        for name, status, count, count_messages in db.execute(
            select(channel, Conversation.status, func.count(), func.sum(incoming.c.messages))
            .join(incoming, incoming.c.cid == Conversation.id)
            .where(Conversation.tenant_id == tid).group_by(channel, Conversation.status)
        ):
            channels[name] = channels.get(name, 0) + count
            statuses[status] = statuses.get(status, 0) + count
            received += count_messages
        opened, total, waiting = db.execute(select(
            func.count().filter(Conversation.created_at >= at, Conversation.created_at < until),
            func.count(),
            func.count(func.distinct(Conversation.contact_id)).filter(Conversation.status == "aguardando"),
        ).where(Conversation.tenant_id == tid)).one()
        recent = db.scalars(select(Conversation).join(incoming, incoming.c.cid == Conversation.id)
                            .where(Conversation.tenant_id == tid)
                            .order_by(incoming.c.latest.desc(), Conversation.id.desc()).limit(4)).all()
        return {
            "att": sum(statuses.values()), "msg": received, "opened": opened, "total": total,
            "channels": channels, "statuses": statuses, "waiting_count": waiting,
            "recent": [conversation_summary(db, user, c, set(), period=(at, until)) for c in recent],
        }