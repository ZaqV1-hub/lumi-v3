"""Transferência operacional explícita; não modifica a conta Meta nem apaga histórico."""
from sqlalchemy import select, update
from ..models import Tenant, Conversation, Message
from ..media_models import ContactGate, ConversationControl
from ..spam import control
from .models import Channel, Chat, ArchivedChat, Outbox, Inbox


def transfer_channel(db, phone_id, target_tenant_id):
    channel = db.get(Channel, phone_id, with_for_update=True)
    if not channel or not db.get(Tenant, target_tenant_id):
        raise ValueError("Canal ou tenant não encontrado")
    if channel.tenant_id == target_tenant_id:
        return {"changed": False, "archived": 0, "restored": 0}
    if db.scalar(select(Inbox.external_id).where(Inbox.phone_number_id == phone_id,
                                               Inbox.status == "processing").limit(1)):
        raise ValueError("Há mensagens em processamento; aguarde antes de transferir")
    chats = db.scalars(select(Chat).where(Chat.phone_number_id == phone_id).with_for_update()).all()
    conversations = []
    for chat in chats:
        conversation = db.get(Conversation, chat.id, with_for_update=True)
        if not conversation or conversation.tenant_id != channel.tenant_id:
            raise ValueError("Vínculo antigo incompatível com o tenant do canal")
        gate = db.get(ContactGate, conversation.contact_id)
        if gate and gate.pending:
            raise ValueError("Há respostas em andamento; aguarde antes de transferir")
        if db.get(ArchivedChat, chat.id):
            raise ValueError("Arquivo de conversa já existe; revise o estado")
        conversations.append(conversation)
    # Todos os vínculos são validados antes da primeira escrita.
    for chat, conversation in zip(chats, conversations):
        db.add(ArchivedChat(id=chat.id, tenant_id=conversation.tenant_id,
                           phone_number_id=chat.phone_number_id, sender=chat.sender,
                           token=chat.token, previous_status=conversation.status))
        conversation.status = "humano"
        state = control(db, conversation.id)
        state.revision += 1
        state.operator_id = None
        mids = select(Message.id).where(Message.conversation_id == conversation.id,
                                        Message.tenant_id == conversation.tenant_id)
        sending = db.scalar(select(Outbox.message_id).where(Outbox.message_id.in_(mids),
                                                           Outbox.status == "sending").limit(1))
        if sending:
            raise ValueError("Há envio em trânsito; confira a entrega antes de transferir")
        db.execute(update(Outbox).where(Outbox.message_id.in_(mids), Outbox.status == "pending")
                   .values(status="cancelled", error="Canal transferido; histórico preservado no tenant original."))
        db.delete(chat)
    db.flush()
    channel.tenant_id = target_tenant_id
    previous = db.scalars(select(ArchivedChat).where(ArchivedChat.phone_number_id == phone_id,
                                                    ArchivedChat.tenant_id == target_tenant_id)).all()
    for archived in previous:
        conversation = db.get(Conversation, archived.id)
        if not conversation or conversation.tenant_id != target_tenant_id:
            raise ValueError("Histórico arquivado incompatível com o destino")
        db.add(Chat(id=archived.id, phone_number_id=phone_id, sender=archived.sender, token=archived.token))
        conversation.status = archived.previous_status
        control(db, conversation.id).revision += 1
        db.delete(archived)
    db.flush()
    return {"changed": True, "archived": len(chats), "restored": len(previous)}
