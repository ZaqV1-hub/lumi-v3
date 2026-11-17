"""Explicit additive migration and selective calling provisioning."""
import argparse
import json

from fastapi import HTTPException
from sqlalchemy import inspect, select, update

from ..db import Base, Session, engine
from ..models import now
from .models import Channel
from .calling_models import CALLING_TABLES, CallOperation, CallingChannel


def prepare_schema(bind):
    # Only these new tables are migrated; existing channel/conversation data stays intact.
    Base.metadata.create_all(bind, tables=CALLING_TABLES, checkfirst=True)
    for table in CALLING_TABLES:
        for index in table.indexes:
            index.create(bind, checkfirst=True)


def inspect_schema(bind):
    inspector = inspect(bind)
    return {table.name: inspector.has_table(table.name) for table in CALLING_TABLES}


def set_channel_enabled(db, *, tenant_id, phone_number_id, enabled):
    db.execute(update(Channel).where(Channel.phone_number_id == phone_number_id, Channel.tenant_id == tenant_id)
        .values(tenant_id=Channel.tenant_id).execution_options(synchronize_session=False))
    channel = db.get(Channel, phone_number_id, populate_existing=True)
    if not channel or channel.tenant_id != tenant_id:
        raise HTTPException(404, 'Canal não encontrado nesta empresa')
    row = db.get(CallingChannel, phone_number_id)
    if row and row.tenant_id != tenant_id:
        raise HTTPException(409, 'Vínculo de canal divergente')
    if not enabled and db.scalar(select(CallOperation.id).where(CallOperation.tenant_id == tenant_id,
            CallOperation.phone_number_id == phone_number_id, CallOperation.kind == 'call', CallOperation.active.is_(True))):
        raise HTTPException(409, 'Encerre e reconcilie as chamadas antes de desativar o canal')
    if not row:
        row = CallingChannel(phone_number_id=phone_number_id, tenant_id=tenant_id)
        db.add(row)
    row.enabled = enabled
    row.updated_at = now()
    db.flush()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'migrate', 'enable', 'disable'])
    parser.add_argument('--tenant-id')
    parser.add_argument('--phone-number-id')
    args = parser.parse_args()
    if args.action == 'migrate':
        prepare_schema(engine)
    elif args.action in {'enable', 'disable'}:
        if not args.tenant_id or not args.phone_number_id:
            parser.error('enable/disable require --tenant-id and --phone-number-id')
        with Session.begin() as db:
            try:
                set_channel_enabled(db, tenant_id=args.tenant_id, phone_number_id=args.phone_number_id,
                                    enabled=args.action == 'enable')
            except HTTPException as error:
                parser.error(error.detail)
    print(json.dumps(inspect_schema(engine)))


if __name__ == '__main__':
    main()
