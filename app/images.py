import base64
import binascii
import io
from PIL import Image, UnidentifiedImageError
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from .access import current_user
from .db import Session
from .media_models import ImageAsset, MessageImage
from .models import Message
from .conversations import visitor

router = APIRouter()


class ImageInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=240)
    when_to_use: str = Field(min_length=1, max_length=200)
    src: str | None = Field(default=None, max_length=7100000)


def decode_image(src):
    try:
        header, encoded = src.split(",", 1)
        if header not in (
            "data:image/png;base64",
            "data:image/jpeg;base64",
            "data:image/webp;base64",
        ):
            raise ValueError()
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError()
        with Image.open(io.BytesIO(data)) as im:
            if (
                im.format not in ("PNG", "JPEG", "WEBP")
                or im.width * im.height > 16000000
            ):
                raise ValueError()
            im.load()
            out = io.BytesIO()
            im.convert("RGB").save(out, format="JPEG", quality=90)
            return out.getvalue()
    except (
        ValueError,
        binascii.Error,
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ) as exc:
        raise HTTPException(
            422, "Envie uma imagem PNG, JPG ou WebP válida, até 5 MB e 16 megapixels."
        ) from exc


@router.get("/api/admin/images")
def list_images(user=Depends(current_user)):
    with Session() as db:
        return [
            {
                "id": i.id,
                "name": i.name,
                "desc": i.description,
                "when": i.when_to_use,
                "src": f"/api/admin/images/{i.id}/file",
            }
            for i in db.scalars(
                select(ImageAsset).where(
                    ImageAsset.tenant_id == user.tenant_id, ImageAsset.enabled == True
                )
            )
        ]


def save(data, user, image_id=None):
    binary = decode_image(data.src) if data.src else None
    with Session.begin() as db:
        if image_id:
            image = db.scalar(
                select(ImageAsset).where(
                    ImageAsset.id == image_id,
                    ImageAsset.tenant_id == user.tenant_id,
                    ImageAsset.enabled == True,
                )
            )
            if not image:
                raise HTTPException(404, "Imagem não encontrada")
        else:
            if binary is None:
                raise HTTPException(422, "Escolha uma imagem")
            image = ImageAsset(tenant_id=user.tenant_id, data=binary)
            db.add(image)
        image.name, image.description, image.when_to_use = (
            data.name,
            data.description,
            data.when_to_use,
        )
        if binary:
            image.data = binary
    return {"ok": True}


@router.post("/api/admin/images")
def create(data: ImageInput, user=Depends(current_user)):
    return save(data, user)


@router.put("/api/admin/images/{image_id}")
def edit(image_id: str, data: ImageInput, user=Depends(current_user)):
    return save(data, user, image_id)


@router.delete("/api/admin/images/{image_id}")
def delete(image_id: str, user=Depends(current_user)):
    with Session.begin() as db:
        image = db.scalar(
            select(ImageAsset).where(
                ImageAsset.id == image_id, ImageAsset.tenant_id == user.tenant_id
            )
        )
        if not image:
            raise HTTPException(404, "Imagem não encontrada")
        image.enabled = False
    return {"ok": True}


def image_response(db, image_id, tenant_id):
    image = db.scalar(
        select(ImageAsset).where(
            ImageAsset.id == image_id, ImageAsset.tenant_id == tenant_id
        )
    )
    if not image:
        raise HTTPException(404, "Imagem não encontrada")
    return Response(
        image.data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/api/admin/images/{image_id}/file")
def admin_file(image_id: str, user=Depends(current_user)):
    with Session() as db:
        return image_response(db, image_id, user.tenant_id)


@router.get("/api/client/{token}/images/{image_id}")
def client_file(token: str, image_id: str):
    with Session() as db:
        v = visitor(db, token)
        sent = db.scalar(
            select(MessageImage)
            .join(Message, Message.id == MessageImage.message_id)
            .where(
                Message.tenant_id == v.tenant_id,
                Message.conversation_id == v.conversation_id,
                MessageImage.image_id == image_id,
            )
        )
        if not sent:
            raise HTTPException(404, "Imagem não enviada nesta conversa")
        return image_response(db, image_id, v.tenant_id)
