import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Response
from ..db import Session
from ..media_models import ImageAsset, MessageImage
from ..models import Message
from ..operator_media import operator_attachment
from .config import value
from .models import Channel, Chat, MediaAccess

router=APIRouter()


def public_image(db, message_id):
    if not db.get(MessageImage,message_id) and not operator_attachment(db, db.get(Message, message_id)):
        return None
    base=value("INSTAGRAM_PUBLIC_BASE_URL").rstrip("/")
    url=urlsplit(base)
    if url.scheme!="https" or not url.hostname or url.username or url.query or url.fragment:
        raise RuntimeError("Configure o endereço HTTPS de mídia do Instagram")
    nonce=secrets.token_urlsafe(40)
    db.add(MediaAccess(token=nonce,message_id=message_id,expires_at=datetime.now(timezone.utc)+timedelta(minutes=15)))
    return base+"/channels/instagram/media/"+nonce


@router.get("/channels/instagram/media/{token}")
def image(token:str):
    with Session() as db:
        access=db.get(MediaAccess,token)
        expires=access.expires_at.replace(tzinfo=timezone.utc) if access and not access.expires_at.tzinfo else access.expires_at if access else None
        if not access or expires<datetime.now(timezone.utc):raise HTTPException(404)
        message=db.get(Message,access.message_id)
        chat=db.get(Chat,message.conversation_id) if message else None
        channel=db.get(Channel,chat.profile_id) if chat else None
        attached=db.get(MessageImage,message.id) if message else None
        asset=db.get(ImageAsset,attached.image_id) if attached else None
        if not channel or message.tenant_id != channel.tenant_id:
            raise HTTPException(404)
        attachment = operator_attachment(db, message)
        headers = {"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}
        if attachment and attachment.kind in ("image", "audio", "video"):
            return Response(attachment.data, media_type=attachment.mime, headers=headers)
        if not asset or asset.tenant_id != channel.tenant_id:
            raise HTTPException(404)
        return Response(asset.data, media_type="image/jpeg", headers=headers)
