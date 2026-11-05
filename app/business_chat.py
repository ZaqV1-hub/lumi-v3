"""A conversa de gestão exige sessão Brevia além do token do simulador."""
import secrets
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from .access import authenticated_user, console_user
from .business_models import ManagementChat, ReportGrant
from .db import Session
from .models import Contact, Conversation, Tenant, VisitorSession
from .tenant_runtime import enabled

router = APIRouter(prefix="/api/console/business")


@router.post("/chat")
def start_chat(actor=Depends(console_user)):
    with Session.begin() as db:
        grant = db.get(ReportGrant, (actor.tenant_id, "administrador"))
        if not grant or not grant.enabled or grant.scope != "all":
            raise HTTPException(403, "Ferramenta de gestão não habilitada para a equipe")
        if not enabled(db, actor.tenant_id):
            raise HTTPException(409, "A Lumi da equipe está desativada")
        tenant = db.get(Tenant, actor.tenant_id)
        contact = Contact(tenant_id=tenant.id, name=actor.name, role="administrador")
        db.add(contact); db.flush()
        conversation = Conversation(tenant_id=tenant.id, contact_id=contact.id)
        db.add(conversation); db.flush()
        token = secrets.token_urlsafe(32)
        db.add(VisitorSession(token=token, tenant_id=tenant.id, conversation_id=conversation.id))
        db.add(ManagementChat(conversation_id=conversation.id, actor_id=actor.id))
        return {"token": token, "slug": tenant.slug, "tenant_id": tenant.id, "tenant": tenant.name}


def guard_chat(request):
    parts = request.url.path.split("/")
    if len(parts) < 4 or parts[1:3] != ["api", "client"]:
        return None
    with Session() as db:
        visitor = db.get(VisitorSession, parts[3])
        chat = db.get(ManagementChat, visitor.conversation_id) if visitor else None
        if not chat:
            return None
        try:
            actor = authenticated_user(request)
        except HTTPException:
            return JSONResponse({"detail": "Entre no admin Brevia para acessar esta conversa"}, status_code=401)
        if actor.console_role not in ("brevia", "admin") or actor.must_change_password or actor.id != chat.actor_id:
            return JSONResponse({"detail": "Conversa de gestão restrita ao administrador responsável"}, status_code=403)
        contact = db.get(Contact, db.get(Conversation, chat.conversation_id).contact_id)
        if contact.role == "administrador" and actor.console_role != "brevia":
            return JSONResponse({"detail": "Conversa restrita à equipe Brevia"}, status_code=403)
        if actor.console_role != "brevia" and actor.tenant_id != visitor.tenant_id:
            return JSONResponse({"detail": "Conversa de outra empresa"}, status_code=403)
    return None
