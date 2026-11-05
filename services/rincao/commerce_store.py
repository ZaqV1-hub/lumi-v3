import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect():
    root = Path(os.getenv("RINCAO_COMMERCE_DATA_DIR", str(Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi")))
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "rincao-commerce.db", timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS checkouts (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
        expires_at REAL NOT NULL, quote TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'quoted',
        packet TEXT, order_id TEXT, payment_url TEXT, gateway_id TEXT,
        request_id TEXT UNIQUE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS payment_attempts (
        checkout_id TEXT NOT NULL, number INTEGER NOT NULL, reference TEXT NOT NULL UNIQUE,
        state TEXT NOT NULL, payment_id TEXT, public_data TEXT, created_at REAL NOT NULL,
        PRIMARY KEY(checkout_id,number))""")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def load(db, quote_id, tenant_id, conversation_id):
    row = db.execute("SELECT * FROM checkouts WHERE id=? AND tenant_id=? AND conversation_id=?",
                     (quote_id, tenant_id, conversation_id)).fetchone()
    if not row:
        raise ValueError("cotacao_nao_encontrada")
    return dict(row)


def unpack(row):
    return json.loads(row["quote"])
