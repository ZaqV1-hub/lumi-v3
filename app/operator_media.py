"""Media written by the operator responsible for a human conversation."""
import asyncio
import io
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from .access import current_user
from .channels import channel_name
from .conversations import conversation
from .db import Session
from .incoming import image_bytes
from .incoming_models import IncomingAttachment
from .models import Message, MessageAuthor
from .spam import admission_lock, control
from .whatsapp.calling import lock_conversation

router = APIRouter()
LIMITS = {'image': 5, 'audio': 12, 'video': 16, 'document': 16}
MIMES = {'image': 'image/jpeg', 'audio': 'audio/mpeg', 'video': 'video/mp4', 'document': 'application/pdf'}
FILENAMES = {'image': 'Imagem.jpg', 'audio': 'Audio.mp3', 'video': 'Video.mp4', 'document': 'Documento.pdf'}


def operator_attachment(db, message):
    if not message or message.sender != 'humano':
        return None
    row = db.get(IncomingAttachment, message.id)
    if row and row.tenant_id == message.tenant_id and row.conversation_id == message.conversation_id:
        return row
    return None


def encode_audio(raw):
    import av
    from .audio import decode

    try:
        samples, seconds = decode(raw)
        out = io.BytesIO()
        with av.open(out, mode='w', format='mp3') as container:
            stream = container.add_stream('libmp3lame', rate=16000)
            stream.layout = 'mono'
            stream.bit_rate = 64000
            for offset in range(0, len(samples), 16000):
                frame = av.AudioFrame.from_ndarray(samples[offset:offset + 16000].reshape(1, -1), format='fltp', layout='mono')
                frame.sample_rate = 16000
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        return out.getvalue(), seconds
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except Exception:
        raise HTTPException(422, 'Não foi possível preparar esse áudio. Grave novamente.') from None


def prepare_file(kind, data):
    if kind == 'image':
        return image_bytes(data), None
    if kind == 'audio':
        return encode_audio(data)
    if kind == 'document':
        if not data.startswith(b'%PDF-'):
            raise HTTPException(422, 'Envie um PDF válido.')
    if kind == 'video':
        import av
        try:
            if data[4:8] != b'ftyp':
                raise ValueError()
            with av.open(io.BytesIO(data), format='mov', options={'protocol_whitelist': 'file,pipe'}) as media:
                if (len(media.streams.video) != 1 or media.streams.video[0].codec_context.name != 'h264'
                        or len(media.streams.audio) > 1 or any(s.codec_context.name != 'aac' for s in media.streams.audio)):
                    raise ValueError()
        except Exception:
            raise HTTPException(422, 'Envie um vídeo MP4 com vídeo H.264 e áudio AAC.') from None
    return data, None


def require_owner(db, user, cid, kind):
    chat = conversation(db, user.tenant_id, cid)
    if chat.status != 'humano' or control(db, cid).operator_id != user.id:
        raise HTTPException(409, 'Assuma o atendimento antes de enviar um anexo.')
    channel = channel_name(db, cid)
    if channel not in ('whatsapp', 'simulator', 'instagram') or (channel == 'instagram' and kind == 'document'):
        raise HTTPException(415, 'Este canal não aceita esse tipo de anexo.')


def already_saved(db, mid, user, cid, kind, data, caption):
    message = db.get(Message, mid)
    if not message:
        return False
    if message.tenant_id == user.tenant_id and message.conversation_id == cid:
        previous = operator_attachment(db, message)
        if previous and (previous.kind, previous.data, previous.caption) == (kind, data, caption):
            return True
    raise HTTPException(409, 'Identificador já utilizado para outro envio.')


@router.post('/api/admin/conversations/{cid}/operator-attachment')
async def upload(cid: str, request: Request, user=Depends(current_user)):
    try:
        mid = str(UUID(request.headers.get('x-media-request', '')))
    except ValueError:
        raise HTTPException(422, 'Identificador do envio inválido.') from None
    kind = request.headers.get('x-media-kind')
    if kind not in LIMITS:
        raise HTTPException(415, 'Escolha uma imagem, áudio, vídeo MP4 ou PDF.')
    caption = unquote(request.headers.get('x-lumi-caption', '')).strip()
    if len(caption) > 850 or (kind == 'audio' and caption):
        raise HTTPException(422, 'Envie o áudio sem legenda ou use até 850 caracteres nos demais anexos.')
    with Session() as db:
        require_owner(db, user, cid, kind)
    raw = bytearray()
    async for part in request.stream():
        if len(raw) + len(part) > LIMITS[kind] * 1024 * 1024:
            raise HTTPException(413, f'O arquivo precisa ter até {LIMITS[kind]} MB.')
        raw.extend(part)
    if not raw:
        raise HTTPException(422, 'O arquivo está vazio.')
    data, seconds = await asyncio.to_thread(prepare_file, kind, bytes(raw))
    try:
        with admission_lock, Session.begin() as db:
            lock_conversation(db, user.tenant_id, cid)
            require_owner(db, user, cid, kind)
            if not already_saved(db, mid, user, cid, kind, data, caption):
                db.add(Message(id=mid, tenant_id=user.tenant_id, conversation_id=cid, sender='humano', content=caption))
                db.flush()
                db.add(MessageAuthor(message_id=mid, name=user.name))
                db.add(IncomingAttachment(message_id=mid, tenant_id=user.tenant_id, conversation_id=cid,
                    kind=kind, mime=MIMES[kind], data=data, caption=caption, duration_seconds=seconds, state='ready'))
    except IntegrityError:
        with Session() as db:
            if not already_saved(db, mid, user, cid, kind, data, caption):
                raise
    return {'ok': True, 'message_id': mid}
