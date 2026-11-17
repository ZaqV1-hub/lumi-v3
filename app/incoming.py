"""Recebimento e acesso a anexos por conversa, com tenant definido pelo servidor."""
import asyncio
import io
from urllib.parse import unquote
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import APIRouter, Request, HTTPException, Response, Depends
from sqlalchemy import select
from .access import current_user
from .conversations import visitor, conversation
from .db import Session
from .incoming_models import IncomingAttachment
from .media_models import ContactGate
from .models import Message
from .schemas import TextInput

router = APIRouter()


def validated_file(binary, mime, caption=""):
    from .audio import audio_format
    mime = mime.split(";")[0].lower()
    kind = "image" if mime.startswith("image/") else "audio" if mime.startswith("audio/") else None
    if not kind: raise HTTPException(415, "Envie uma imagem ou um áudio.")
    if not binary or len(binary) > (5 if kind=="image" else 12)*1024*1024:
        raise HTTPException(422, "Arquivo vazio ou grande demais. Imagem: 5 MB; áudio: 12 MB.")
    if len(caption)>2000: raise HTTPException(422, "Use uma legenda de até 2.000 caracteres.")
    if kind=="image": binary=image_bytes(binary);mime="image/jpeg"
    else:
        try: format=audio_format(binary)
        except ValueError as exc: raise HTTPException(422,str(exc)) from None
        mime={"wav":"audio/wav","ogg":"audio/ogg","matroska":"audio/webm","mov":"audio/mp4","mp3":"audio/mpeg"}[format]
    return {"kind":kind,"mime":mime,"data":binary,"caption":caption}


def image_bytes(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP") or image.width*image.height > 16_000_000:
                raise ValueError()
            image.load(); image = ImageOps.exif_transpose(image).convert("RGBA")
            image.thumbnail((1600,1600), Image.Resampling.LANCZOS)
            background = Image.new("RGB", image.size, "white"); background.paste(image, mask=image.getchannel("A"))
            out = io.BytesIO(); background.save(out, format="JPEG", quality=85)
            return out.getvalue()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(422, "Envie uma imagem JPG, PNG ou WebP válida, até 5 MB e 16 megapixels.") from None


@router.post("/api/client/{token}/attachments")
async def upload(token: str, request: Request):
    from .client import receive_message, process_message
    with Session() as db:
        session = visitor(db, token); chat = conversation(db, session.tenant_id, session.conversation_id)
        gate = db.get(ContactGate, chat.contact_id)
        if gate and gate.blocked: return {"ok": True, "blocked": True}
    mime = request.headers.get("content-type", "").split(";")[0].lower()
    kind = "image" if mime.startswith("image/") else "audio" if mime.startswith("audio/") else None
    if not kind: raise HTTPException(415, "Envie uma imagem ou um áudio.")
    limit = (5 if kind == "image" else 12)*1024*1024
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw)>limit: raise HTTPException(413, "Arquivo muito grande. Imagens: até 5 MB; áudios: até 12 MB e dois minutos.")
    if not raw: raise HTTPException(422, "O arquivo está vazio.")
    caption = unquote(request.headers.get("x-lumi-caption", "")).strip()
    if len(caption)>2000: raise HTTPException(422, "Use uma legenda de até 2.000 caracteres.")
    attachment = await asyncio.to_thread(validated_file, bytes(raw), mime, caption)
    receipt = receive_message(token, TextInput(content=caption or ("[Imagem enviada]" if kind=="image" else "[Áudio enviado]")),
        attachment=attachment)
    if not receipt.get("accepted"): return {"ok": True, "blocked": receipt.get("blocked", False)}
    return await asyncio.to_thread(process_message, receipt)


def prepare_attachment(receipt):
    loader = receipt.pop("attachment_loader", None)
    if loader is None:
        return
    attachment = loader()
    with Session.begin() as db:
        message = db.get(Message, receipt["message_id"])
        if not message or message.tenant_id != receipt["tenant_id"] or message.conversation_id != receipt["conversation_id"]:
            raise HTTPException(404, "Mensagem não encontrada")
        db.add(IncomingAttachment(message_id=message.id, tenant_id=message.tenant_id,
            conversation_id=message.conversation_id, **attachment))


def prepare_audio(receipt):
    with Session() as db:
        attachment = db.get(IncomingAttachment, receipt["message_id"])
        if not attachment or attachment.kind != "audio": return
        if attachment.tenant_id != receipt["tenant_id"] or attachment.conversation_id != receipt["conversation_id"]:
            raise HTTPException(404, "Anexo não encontrado")
        binary, caption = attachment.data, attachment.caption
    from .audio import transcribe
    try:
        text, seconds = transcribe(binary)
    except ValueError as exc:
        with Session.begin() as db: db.get(IncomingAttachment, receipt["message_id"]).state = "failed"
        raise HTTPException(422, str(exc)) from None
    except Exception:
        with Session.begin() as db: db.get(IncomingAttachment, receipt["message_id"]).state = "failed"
        raise HTTPException(503, "A transcrição está temporariamente indisponível. Tente novamente ou envie por texto.") from None
    with Session.begin() as db:
        attachment = db.get(IncomingAttachment, receipt["message_id"])
        attachment.transcript, attachment.duration_seconds, attachment.state = text, seconds, "transcribed"
        content = (caption + "\n" if caption else "") + "[Transcrição do áudio]\n" + text
        db.get(Message, receipt["message_id"]).content = content
        receipt["data"] = TextInput(content=content)


def file_response(db, tid, cid, mid):
    from .documents import document_response, message_document

    document = message_document(db, tid, cid, mid)
    if document:
        return document_response(document)
    row = db.scalar(select(IncomingAttachment).where(IncomingAttachment.tenant_id==tid,
        IncomingAttachment.conversation_id==cid, IncomingAttachment.message_id==mid))
    if not row: raise HTTPException(404, "Anexo não encontrado")
    headers = {"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff", "Content-Security-Policy":"default-src 'none'"}
    if row.kind == "document":
        headers["Content-Disposition"] = 'attachment; filename="Documento.pdf"'
    return Response(row.data, media_type=row.mime, headers=headers)


@router.get("/api/client/{token}/attachments/{mid}")
def client_file(token: str, mid: str):
    with Session() as db:
        session = visitor(db, token)
        return file_response(db, session.tenant_id, session.conversation_id, mid)


@router.get("/api/admin/conversations/{cid}/attachments/{mid}")
def admin_file(cid: str, mid: str, user=Depends(current_user)):
    with Session() as db:
        conversation(db, user.tenant_id, cid)
        return file_response(db, user.tenant_id, cid, mid)
