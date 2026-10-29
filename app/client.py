import secrets
import subprocess
import json
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from .db import Session
from .models import (
    Tenant,
    Contact,
    Conversation,
    VisitorSession,
    Feature,
    Message,
    KnowledgeItem,
    FeatureCall,
)
from .schemas import Start, TextInput
from .conversations import conversation, messages, visitor
from .features import request_handover, asks_for_human
from .prompt import build_prompt
from .providers import reply
from .onboarding import profile_state, prompt_context, save_profile
from .media_models import ContactGate, ImageAsset, MessageImage, ConversationControl
from .spam import admission_lock, admit, finish, generation_lock, control

router = APIRouter()


@router.post("/api/public/{slug}/start")
def start(slug: str, data: Start):
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
        if not tenant:
            raise HTTPException(404, "Empresa não encontrada")
        contact = Contact(tenant_id=tenant.id, name=data.name, role="cliente")
        db.add(contact)
        db.flush()
        c = Conversation(tenant_id=tenant.id, contact_id=contact.id)
        db.add(c)
        db.flush()
        token = secrets.token_urlsafe(32)
        db.add(VisitorSession(token=token, tenant_id=tenant.id, conversation_id=c.id))
        return {"token": token, "tenant": tenant.name}


@router.get("/api/client/{token}")
def client_messages(token: str):
    with Session() as db:
        v = visitor(db, token)
        c = conversation(db, v.tenant_id, v.conversation_id)
        gate = db.get(ContactGate, c.contact_id)
        items = messages(db, v.tenant_id, c.id)
        for item in items:
            if item.get("image_id"):
                item["image_url"] = f"/api/client/{token}/images/{item['image_id']}"
        return {
            "status": c.status,
            "blocked": bool(gate and gate.blocked),
            "messages": items,
        }


def handover(tid, cid, role, reason):
    from sqlalchemy import update

    with Session.begin() as db:
        feature = db.scalar(
            select(Feature).where(
                Feature.tenant_id == tid,
                Feature.name == "handover",
                Feature.enabled == True,
            )
        )
        if not feature or role not in feature.roles.split(","):
            raise HTTPException(
                403, "Atendimento humano indisponível para este contato"
            )
        changed = db.execute(
            update(Conversation)
            .where(
                Conversation.id == cid,
                Conversation.tenant_id == tid,
                Conversation.status == "lumi",
            )
            .values(status="aguardando")
        ).rowcount
    if not changed:
        return {"ok": True}
    try:
        request_handover(tid, cid, role, reason)
    except RuntimeError as exc:
        # O pedido continua visível no admin mesmo se o serviço externo cair.
        raise HTTPException(
            503,
            "Seu pedido ficou registrado. A confirmação do atendimento está indisponível no momento.",
        ) from exc
    with Session.begin() as db:
        db.add(
            Message(
                tenant_id=tid,
                conversation_id=cid,
                sender="sistema",
                content="Seu pedido de atendimento humano foi registrado. A equipe vai responder por aqui.",
            )
        )
    return {"ok": True}


@router.post("/api/client/{token}/messages")
def client_send(token: str, data: TextInput):
    receipt = receive_message(token, data)
    if not receipt.get("accepted"):
        return {"ok": True, "blocked": receipt.get("blocked", False)}
    return process_message(receipt)


def receive_message(token, data):
    """Admite a mensagem antes de esperar a IA, inclusive no canal WhatsApp."""
    with admission_lock, Session.begin() as db:
        v = visitor(db, token)
        c = conversation(db, v.tenant_id, v.conversation_id)
        contact_id = c.contact_id
        gate = db.get(ContactGate, contact_id)
        if gate and gate.blocked:
            return {"accepted": False, "blocked": True}
        incoming = Message(
            tenant_id=v.tenant_id,
            conversation_id=c.id,
            sender="cliente",
            content=data.content,
        )
        db.add(incoming)
        db.flush()
        cutoff = incoming.created_at
        if c.status != "lumi":
            return {"accepted": False}
        if not admit(db, v.tenant_id, c.id, contact_id):
            return {"accepted": False}
        revision = control(db, c.id).revision
    return {
        "accepted": True,
        "token": token,
        "data": data,
        "cutoff": cutoff,
        "revision": revision,
        "contact_id": contact_id,
    }


def process_message(receipt):
    contact_id = receipt["contact_id"]
    try:
        with generation_lock(contact_id):
            return answer_message(
                receipt["token"],
                receipt["data"],
                receipt["cutoff"],
                receipt["revision"],
            )
    finally:
        finish(contact_id)


def answer_message(token, data, cutoff, revision):
    # Persistir a mensagem antes da chamada lenta permite intervenção do atendente.
    with Session.begin() as db:
        v = visitor(db, token)
        tid, cid = v.tenant_id, v.conversation_id
        c = conversation(db, tid, cid)
        human = c.status != "lumi" or control(db, cid).revision != revision
        contact = db.get(Contact, c.contact_id)
        role = contact.role
    if human:
        return {"ok": True}
    if asks_for_human(data.content):
        return handover(tid, cid, role, data.content)
    with Session() as db:
        tenant = db.get(Tenant, tid)
        contact = db.get(Contact, conversation(db, tid, cid).contact_id)
        history = list(
            db.scalars(
                select(Message)
                .where(Message.tenant_id == tid, Message.conversation_id == cid)
                .where((Message.sender != "cliente") | (Message.created_at <= cutoff))
                .where(Message.sender != "sistema")
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(20)
            )
        )[::-1]
        facts = list(
            db.scalars(
                select(KnowledgeItem).where(
                    KnowledgeItem.tenant_id == tid, KnowledgeItem.enabled == True
                )
            )
        )
        features = list(
            db.scalars(
                select(Feature).where(Feature.tenant_id == tid, Feature.enabled == True)
            )
        )
        onboarding = profile_state(db, tid, contact.id)
        name_confirmed = not onboarding["enabled"] or any(
            f["updates_name"] and f["value"] for f in onboarding["fields"])
        prompt = build_prompt(tenant, contact, facts, history, name_confirmed=name_confirmed)
        prompt += "\nFuncionalidades habilitadas: " + "; ".join(
            f.description for f in features if role in f.roles.split(",")
        )
        from .media_models import TenantPreferences

        prefs = db.get(TenantPreferences, tid)
        if prefs:
            prompt += f"\nPersonalidade: tom {prefs.tone}, tamanho {prefs.length}, estilo {prefs.style}."
        images = list(
            db.scalars(
                select(ImageAsset).where(
                    ImageAsset.tenant_id == tid, ImageAsset.enabled == True
                )
            )
        )
        prompt += (
            "\nImagens disponíveis (action=send_image, image_id=id):\n"
            + "\n".join(
                f"{i.id}: {i.name}; descrição: {i.description}; quando usar: {i.when_to_use}"
                for i in images
            )
        )
        prompt += "\nEnvie imagem apenas quando a instrução de uso corresponder ao pedido claro do cliente. Nunca invente IDs. Não envie imagens em conversas genéricas."
    prompt += prompt_context(onboarding, data.content)
    try:
        answer = reply(prompt)
    except (RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(
            503,
            "Não consegui responder agora. Sua mensagem foi salva; tente novamente em instantes.",
        ) from exc
    image_id = None
    profile_answer = answer if isinstance(answer, dict) else {}
    if isinstance(answer, dict):
        if answer.get("action") == "handover":
            return handover(tid, cid, role, data.content)
        if answer.get("action") == "send_image":
            image_id = answer.get("image_id")
        answer = answer["reply"]
    with admission_lock, Session.begin() as db:
        # Compare-and-set no banco: resposta em andamento não pode passar pelo handover.
        from sqlalchemy import update

        if control(db, cid).revision != revision:
            return {"ok": True}
        allowed = db.execute(
            update(Conversation)
            .where(
                Conversation.id == cid,
                Conversation.tenant_id == tid,
                Conversation.status == "lumi",
            )
            .values(status="lumi")
        ).rowcount
        if allowed:
            save_profile(db, tid, contact_id=contact.id, answer=profile_answer, incoming=data.content)
            image = (
                db.scalar(
                    select(ImageAsset).where(
                        ImageAsset.id == image_id,
                        ImageAsset.tenant_id == tid,
                        ImageAsset.enabled == True,
                    )
                )
                if image_id
                else None
            )
            if image_id:
                db.add(
                    FeatureCall(
                        tenant_id=tid,
                        conversation_id=cid,
                        feature="send_image",
                        parameters=json.dumps({"image_id": image_id}),
                        result=json.dumps({"accepted": bool(image)}),
                        duration_ms="0",
                    )
                )
            if image_id and not image:
                answer = "Não encontrei uma imagem disponível para esse pedido."
            message = Message(
                tenant_id=tid, conversation_id=cid, sender="lumi", content=answer
            )
            db.add(message)
            db.flush()
            if image:
                db.add(MessageImage(message_id=message.id, image_id=image.id))
    return {"ok": True}
