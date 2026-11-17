"""Catálogo de PDFs enviados pelo atendimento no WhatsApp."""

import json
from urllib.parse import quote

from fastapi import Response
from sqlalchemy import ForeignKey, LargeBinary, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import Message, uid
from .whatsapp.models import Channel, Chat


class DocumentAsset(Base):
    __tablename__ = "document_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    filename: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    enabled: Mapped[bool] = mapped_column(default=True)


class MessageDocument(Base):
    __tablename__ = "message_documents"

    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document_assets.id"))


def available_documents(db, tenant_id, conversation_id):
    return list(db.scalars(select(DocumentAsset).where(
        DocumentAsset.tenant_id == tenant_id, DocumentAsset.enabled.is_(True),
        select(Chat.id).join(Channel, Channel.phone_number_id == Chat.phone_number_id)
        .where(Chat.id == conversation_id, Channel.tenant_id == tenant_id).exists(),
    ).order_by(DocumentAsset.title, DocumentAsset.id)))


def document_context(documents):
    if not documents:
        return ""
    catalog = [{"id": doc.id, "título": doc.title, "descrição": doc.description} for doc in documents]
    return (
        '\nSe o cliente pedir um book, PDF ou material do catálogo de documentos, use action="send_document" '
        'com document_id do catálogo. Se o empreendimento for incerto, pergunte. Envie somente o material '
        'solicitado. Se as instruções da empresa pedirem foto e book para a mesma apresentação, '
        'use action="send_image_and_document", com image_id e document_id do mesmo empreendimento '
        'e image_intent="send_catalog". O campo reply acompanha a foto e deve caber na legenda. '
        'Pedido apenas de foto ou planta continua no catálogo de imagens. '
        'Catálogo de documentos: ' + json.dumps(catalog, ensure_ascii=False)
    )


def message_document(db, tenant_id, conversation_id, message_id):
    return db.scalar(
        select(DocumentAsset)
        .join(MessageDocument, MessageDocument.document_id == DocumentAsset.id)
        .join(Message, Message.id == MessageDocument.message_id)
        .where(Message.id == message_id, Message.tenant_id == tenant_id,
               Message.conversation_id == conversation_id, DocumentAsset.tenant_id == tenant_id)
    )


def document_response(document):
    return Response(document.data, media_type="application/pdf", headers={
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(document.filename, safe=""),
    })
