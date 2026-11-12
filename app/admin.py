import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from .access import current_user
from .db import Session
from .models import Conversation, Contact, Message, MessageAuthor, Tenant, KnowledgeItem
from .schemas import TextInput, Settings, Knowledge, ContactRole
from .conversations import conversation, messages, timestamp
from .media_models import TenantPreferences, ContactGate, ConversationControl
from .spam import admission_lock, control
from .whatsapp.models import Chat
from .channels import channel_name
from .tenant_runtime import assistant_name
from .onboarding import profile_state
from .visit_goal import confirmed_conversations
from .role_instructions import RoleInstruction
from .whatsapp.calling import lock_conversation, has_active_call
from .whatsapp.calling_timeline import call_timeline, with_calls

router = APIRouter()


def _conversation_name(name, channel, profile):
    if channel != "whatsapp":
        return name
    name_fields = [field for field in profile["fields"] if field["updates_name"]]
    if name_fields:
        name = next((field["value"] for field in name_fields if field["value"]), "")
    name = name.strip()
    if not name or re.fullmatch(r"[+\d().\s-]+", name):
        return "Nome não informado"
    return name


@router.get("/api/admin/conversations")
def conversations(user=Depends(current_user)):
    with Session() as db:
        activity = (select(Message.conversation_id, func.max(Message.created_at).label("latest"))
            .where(Message.tenant_id == user.tenant_id)
            .group_by(Message.conversation_id).subquery())
        rows = db.scalars(
            select(Conversation)
            .outerjoin(activity, activity.c.conversation_id == Conversation.id)
            .where(Conversation.tenant_id == user.tenant_id)
            .order_by(func.coalesce(activity.c.latest, Conversation.created_at).desc(),
                      Conversation.created_at.desc(), Conversation.id.desc())
        )
        calls = call_timeline(db, user.tenant_id)
        confirmed_visits = confirmed_conversations(db, user.tenant_id)
        result = []
        for c in rows:
            contact = db.get(Contact, c.contact_id)
            profile = profile_state(db, user.tenant_id, c.contact_id)
            channel = channel_name(db, c.id)
            state = db.get(ConversationControl, c.id) if c.status == 'humano' else None
            result.append({
                "id": c.id,
                "contact_id": c.contact_id,
                "profile": profile,
                "visit_confirmed": c.id in confirmed_visits,
                "status": c.status,
                "can_reply": bool(state and state.operator_id == user.id and user.console_role != 'leitura'),
                "name": _conversation_name(contact.name, channel, profile),
                "role": contact.role,
                "channel": channel,
                "created_at": timestamp(c.created_at),
                "blocked": bool(
                    db.get(ContactGate, c.contact_id)
                    and db.get(ContactGate, c.contact_id).blocked
                ),
                "messages": with_calls(messages(db, user.tenant_id, c.id), calls.get(c.id)),
            })
        return result


@router.get("/api/admin/conversations/{cid}")
def detail(cid: str, user=Depends(current_user)):
    with Session() as db:
        c = conversation(db, user.tenant_id, cid)
        calls = call_timeline(db, user.tenant_id, cid)
        return {"status": c.status, "messages": with_calls(messages(db, user.tenant_id, cid), calls.get(cid))}


@router.put("/api/admin/conversations/{cid}/role")
def change_role(cid: str, data: ContactRole, user=Depends(current_user)):
    from .tenant_runtime import allows_role
    with admission_lock, Session.begin() as db:
        c = conversation(db, user.tenant_id, cid)
        contact = db.get(Contact, c.contact_id)
        if not allows_role(db, user.tenant_id, data.role) or not db.get(RoleInstruction, (user.tenant_id, data.role)):
            raise HTTPException(400, "Papel não cadastrado nesta empresa")
        if data.role == "administrador" and user.console_role != "brevia":
            raise HTTPException(403, "Somente a equipe Brevia pode autorizar este papel")
        if contact.role != data.role:
            contact.role = data.role
            control(db, cid).revision += 1
    return {"role": data.role}


@router.post("/api/admin/conversations/{cid}/claim")
def claim(cid: str, user=Depends(current_user)):
    with admission_lock, Session.begin() as db:
        c = lock_conversation(db, user.tenant_id, cid)
        state = control(db, cid)
        if state.operator_id and state.operator_id != user.id:
            raise HTTPException(409, "Outro operador está atendendo esta conversa")
        if c.status != "humano":
            db.add(
                Message(
                    tenant_id=user.tenant_id,
                    conversation_id=cid,
                    sender="sistema",
                    content=f"{user.name} assumiu a conversa.",
                )
            )
        state.operator_id = user.id
        state.revision += 1
        c.status = "humano"
    return {"ok": True}


@router.post("/api/admin/conversations/{cid}/release")
def release(cid: str, user=Depends(current_user)):
    with admission_lock, Session.begin() as db:
        c = lock_conversation(db, user.tenant_id, cid)
        if has_active_call(db, tenant_id=user.tenant_id, conversation_id=cid):
            raise HTTPException(409, f"Encerre a ligação e aguarde a confirmação antes de devolver à {assistant_name(db.get(Tenant, user.tenant_id))}")
        state = control(db, cid)
        if state.operator_id and state.operator_id != user.id:
            raise HTTPException(
                409, "Somente o operador responsável pode sair do atendimento"
            )
        if c.status == "humano":
            db.add(
                Message(
                    tenant_id=user.tenant_id,
                    conversation_id=cid,
                    sender="sistema",
                    content=f"{user.name} saiu da conversa. A {assistant_name(db.get(Tenant, user.tenant_id))} voltou ao atendimento.",
                )
            )
            c.status = "lumi"
            state.operator_id = None
            state.revision += 1
    return {"ok": True}


@router.post("/api/admin/conversations/{cid}/unblock")
def unblock(cid: str, user=Depends(current_user)):
    with admission_lock, Session.begin() as db:
        c = conversation(db, user.tenant_id, cid)
        gate = db.get(ContactGate, c.contact_id)
        if gate:
            gate.blocked = False
            gate.warnings = 0
    return {"ok": True}


@router.post("/api/admin/conversations/{cid}/messages")
def human_message(cid: str, data: TextInput, user=Depends(current_user)):
    with admission_lock, Session.begin() as db:
        c = conversation(db, user.tenant_id, cid)
        state = control(db, cid)
        if c.status != "humano" or state.operator_id != user.id:
            raise HTTPException(409, "Assuma o atendimento antes de responder")
        message = Message(
            tenant_id=user.tenant_id,
            conversation_id=cid,
            sender="humano",
            content=data.content,
        )
        db.add(message)
        db.flush()
        db.add(MessageAuthor(message_id=message.id, name=user.name))
    return {"ok": True}


@router.get("/api/admin/settings")
def settings(user=Depends(current_user)):
    with Session() as db:
        tenant = db.get(Tenant, user.tenant_id)
        prefs = db.get(TenantPreferences, user.tenant_id)
        return {
            "identity": tenant.identity,
            "personality": tenant.personality,
            "tone": prefs.tone if prefs else "Neutro",
            "length": prefs.length if prefs else "Curto",
            "style": prefs.style if prefs else "Objetivo",
            "max_pending": prefs.max_pending if prefs else 3,
        }


@router.put("/api/admin/settings")
def save_settings(data: Settings, user=Depends(current_user)):
    with Session.begin() as db:
        tenant = db.get(Tenant, user.tenant_id)
        tenant.identity, tenant.personality = data.identity, data.personality
        prefs = db.get(TenantPreferences, user.tenant_id)
        if not prefs:
            prefs = TenantPreferences(tenant_id=user.tenant_id)
            db.add(prefs)
        prefs.tone, prefs.length, prefs.style, prefs.max_pending = (
            data.tone,
            data.length,
            data.style,
            data.max_pending,
        )
    return {"ok": True}


@router.get("/api/admin/knowledge")
def knowledge(user=Depends(current_user)):
    with Session() as db:
        return [
            {"id": k.id, "title": k.title, "content": k.content}
            for k in db.scalars(
                select(KnowledgeItem).where(KnowledgeItem.tenant_id == user.tenant_id)
            )
        ]


@router.post("/api/admin/knowledge")
def add_knowledge(data: Knowledge, user=Depends(current_user)):
    with Session.begin() as db:
        db.add(KnowledgeItem(tenant_id=user.tenant_id, **data.model_dump()))
    return {"ok": True}


@router.delete("/api/admin/knowledge/{kid}")
def remove_knowledge(kid: str, user=Depends(current_user)):
    with Session.begin() as db:
        item = db.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.id == kid, KnowledgeItem.tenant_id == user.tenant_id
            )
        )
        if not item:
            raise HTTPException(404, "Conhecimento não encontrado")
        db.delete(item)
    return {"ok": True}


@router.put("/api/admin/knowledge/{kid}")
def edit_knowledge(kid: str, data: Knowledge, user=Depends(current_user)):
    with Session.begin() as db:
        item = db.scalar(
            select(KnowledgeItem).where(
                KnowledgeItem.id == kid, KnowledgeItem.tenant_id == user.tenant_id
            )
        )
        if not item:
            raise HTTPException(404, "Conhecimento não encontrado")
        item.title, item.content = data.title, data.content
    return {"ok": True}
