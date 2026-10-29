from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from .access import current_user
from .db import Session
from .models import Conversation, Contact, Message, MessageAuthor, Tenant, KnowledgeItem
from .schemas import TextInput, Settings, Knowledge
from .conversations import conversation, messages, timestamp
from .media_models import TenantPreferences, ContactGate
from .spam import admission_lock, control
from .whatsapp.models import Chat
from .onboarding import profile_state

router = APIRouter()


@router.get("/api/admin/conversations")
def conversations(user=Depends(current_user)):
    with Session() as db:
        rows = db.scalars(
            select(Conversation)
            .where(Conversation.tenant_id == user.tenant_id)
            .order_by(Conversation.created_at.desc())
        )
        return [
            {
                "id": c.id,
                "profile": profile_state(db, user.tenant_id, c.contact_id),
                "status": c.status,
                "name": db.get(Contact, c.contact_id).name,
                "channel": "whatsapp" if db.get(Chat, c.id) else "simulator",
                "created_at": timestamp(c.created_at),
                "blocked": bool(
                    db.get(ContactGate, c.contact_id)
                    and db.get(ContactGate, c.contact_id).blocked
                ),
                "messages": messages(db, user.tenant_id, c.id),
            }
            for c in rows
        ]


@router.get("/api/admin/conversations/{cid}")
def detail(cid: str, user=Depends(current_user)):
    with Session() as db:
        c = conversation(db, user.tenant_id, cid)
        return {"status": c.status, "messages": messages(db, user.tenant_id, cid)}


@router.post("/api/admin/conversations/{cid}/claim")
def claim(cid: str, user=Depends(current_user)):
    with admission_lock, Session.begin() as db:
        c = conversation(db, user.tenant_id, cid)
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
        c = conversation(db, user.tenant_id, cid)
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
                    content=f"{user.name} saiu da conversa. A Lumi voltou ao atendimento.",
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
