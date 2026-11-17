"""Banco exclusivo do serviço. Migrações versionadas sem tocar no banco da Lumi."""
import os
import sqlite3
from pathlib import Path


def connect():
    root = Path(os.environ["LUMI_SCHEDULING_DATA"])
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "scheduling.sqlite3", timeout=25)
    db.row_factory = sqlite3.Row
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, 2, 3):
        db.close()
        raise RuntimeError("Versão de armazenamento não suportada")
    if version == 0:
        with db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS slots (
                  id TEXT PRIMARY KEY, tenant TEXT NOT NULL, conversation TEXT NOT NULL,
                  scope TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS bookings (
                  id TEXT PRIMARY KEY, slot TEXT NOT NULL, tenant TEXT NOT NULL,
                  conversation TEXT NOT NULL, scope TEXT NOT NULL, start TEXT NOT NULL,
                  end TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL, topic TEXT NOT NULL,
                  source_message TEXT NOT NULL, state TEXT NOT NULL, event TEXT NOT NULL,
                  result TEXT, created REAL NOT NULL, UNIQUE(tenant,conversation,slot));
                CREATE INDEX IF NOT EXISTS booking_calendar ON bookings(scope,start,end,state);
                PRAGMA user_version=1;
            """)
    if version < 2:
        db.executescript("""BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS participant_changes (
              id TEXT PRIMARY KEY, booking TEXT NOT NULL, state TEXT NOT NULL,
              result TEXT, created REAL NOT NULL,
              FOREIGN KEY(booking) REFERENCES bookings(id));
            CREATE INDEX IF NOT EXISTS participant_booking ON participant_changes(booking,state);
            PRAGMA user_version=2;
            COMMIT;""")
    if version < 3:
        db.executescript("""BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS description_changes (
              id TEXT PRIMARY KEY, booking TEXT NOT NULL, state TEXT NOT NULL,
              description TEXT NOT NULL, created REAL NOT NULL,
              FOREIGN KEY(booking) REFERENCES bookings(id));
            CREATE INDEX IF NOT EXISTS description_booking ON description_changes(booking,state);
            PRAGMA user_version=3;
            COMMIT;""")
    return db


def scoped(db, booking_id, tenant, conversation):
    return db.execute("SELECT * FROM bookings WHERE id=? AND tenant=? AND conversation=?",
                      (booking_id, tenant, conversation)).fetchone()


def overlap(db, scope, start, end, exclude=""):
    return db.execute("""SELECT 1 FROM bookings WHERE scope=? AND id<>? AND start<? AND end>?
        AND state IN ('creating','unknown','confirmed') LIMIT 1""", (scope, exclude, end, start)).fetchone() is not None
