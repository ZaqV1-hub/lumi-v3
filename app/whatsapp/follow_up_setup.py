"""Provisiona retomadas e PDFs para um canal existente."""

import argparse
from pathlib import Path

from sqlalchemy import select

from ..db import Session
from ..documents import DocumentAsset
from ..models import Tenant
from .follow_up import FollowUpChannel
from .models import Channel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--filename")
    parser.add_argument("--title")
    parser.add_argument("--description")
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    data = None
    if args.pdf:
        if args.disable or not (args.filename and args.title and args.description):
            parser.error("Informe filename, title e description para cadastrar o PDF.")
        if args.pdf.stat().st_size > 100_000_000:
            parser.error("PDF excede o limite do canal.")
        data = args.pdf.read_bytes()
        if not data.startswith(b"%PDF-") or not args.filename.lower().endswith(".pdf"):
            parser.error("Arquivo PDF inválido.")
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.slug).with_for_update())
        if not tenant:
            parser.error("Empresa não encontrada.")
        channels = list(db.scalars(select(Channel).where(Channel.tenant_id == tenant.id).with_for_update()))
        if len(channels) != 1:
            parser.error("A empresa precisa ter um único canal WhatsApp para esta operação.")
        channel = channels[0]
        setting = db.get(FollowUpChannel, channel.phone_number_id)
        if setting and setting.tenant_id != tenant.id:
            parser.error("Configuração pertence a outro vínculo de canal.")
        if args.disable:
            if setting:
                db.delete(setting)
            for document in db.scalars(select(DocumentAsset).where(DocumentAsset.tenant_id == tenant.id)):
                document.enabled = False
        else:
            if not setting:
                db.add(FollowUpChannel(phone_number_id=channel.phone_number_id, tenant_id=tenant.id))
            if data is not None:
                existing = db.scalar(select(DocumentAsset).where(
                    DocumentAsset.tenant_id == tenant.id, DocumentAsset.filename == args.filename
                ))
                if existing and existing.data != data:
                    parser.error("Já existe um PDF diferente com esse nome. Cadastre uma nova versão.")
                if existing:
                    existing.enabled = True
                else:
                    db.add(DocumentAsset(tenant_id=tenant.id, filename=args.filename, title=args.title,
                                         description=args.description, data=data))
    print("Configuração aplicada ao canal selecionado.")


if __name__ == "__main__":
    main()
