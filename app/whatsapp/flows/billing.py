from sqlalchemy import select

from ..models import Channel
from .config import channel_config
from .models import FlowPricing


def record_pricing(db, phone, delivery):
    config = channel_config(phone)
    pricing = delivery.get('pricing')
    channel = db.get(Channel, phone)
    if not config or not channel or config['tenant_id'] != channel.tenant_id or not isinstance(pricing, dict):
        return
    external_id = delivery.get('id')
    if not isinstance(external_id, str) or len(external_id) > 240:
        return
    row = db.get(FlowPricing, external_id)
    if row and (row.tenant_id != channel.tenant_id or row.phone_number_id != phone):
        return
    if not row:
        row = FlowPricing(external_id=external_id, tenant_id=channel.tenant_id, phone_number_id=phone)
        db.add(row)
    row.category = str(pricing.get('category', ''))[:40]
    row.pricing_type = str(pricing.get('type', ''))[:40]
    row.billable = pricing.get('billable') if isinstance(pricing.get('billable'), bool) else None
