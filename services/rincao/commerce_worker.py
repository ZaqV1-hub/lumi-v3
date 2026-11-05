import asyncio
import logging
from .cielo_checkout import is_enabled
from .commerce_store import connect
from .commerce_status import reconcile

logger = logging.getLogger(__name__)


def poll_pending():
    if not is_enabled():
        return
    with connect() as db:
        rows = db.execute("SELECT id,tenant_id,conversation_id FROM checkouts WHERE state IN ('waiting_payment','unknown') AND order_id IS NOT NULL LIMIT 100").fetchall()
    for row in rows:
        try:
            reconcile(row["id"], row["tenant_id"], row["conversation_id"])
        except Exception:
            # Sem dados do comprador, URLs privadas ou resposta bruta do gateway no log.
            logger.info("Aguardando nova verificação do checkout %s", row["id"][:8])


async def watch_payments():
    while True:
        try:
            await asyncio.to_thread(poll_pending)
        except Exception:
            logger.warning("Monitor de pagamentos temporariamente indisponível")
        await asyncio.sleep(15)
