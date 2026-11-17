import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base, Session
from app.models import Contact, Conversation, FeatureCall, Message, Tenant
from app.seed import seed


class AdminHistoryTest(unittest.TestCase):
    def setUp(self):
        self.old = Session.kw["bind"]
        self.db = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.db)
        Session.configure(bind=self.db)
        self.addCleanup(self.db.dispose)
        self.addCleanup(Session.configure, bind=self.old)
        seed()
        self.http = TestClient(main.app)
        self.addCleanup(self.http.close)
        self.http.post("/api/login", json={"email": "isaque@rincao.local", "password": "demo1234"}).raise_for_status()
        self.t = datetime(2026, 11, 10, 3, tzinfo=timezone.utc)
        with Session.begin() as db:
            self.tid = db.scalar(select(Tenant.id).where(Tenant.slug == "rincao"))
            self.other = db.scalar(select(Tenant.id).where(Tenant.slug == "breve"))
            for i in range(24):
                status = "aguardando" if i < 12 else "humano"
                db.add(Contact(id=f"p{i:02}", tenant_id=self.tid, name=f"Pessoa {i:02}"))
                db.add(Conversation(id=f"c{i:02}", tenant_id=self.tid, contact_id=f"p{i:02}",
                                    status=status, created_at=self.t - timedelta(hours=1)))
                db.add(Message(id=f"initial{i:02}", tenant_id=self.tid, conversation_id=f"c{i:02}",
                               sender="cliente", content="fixture", created_at=self.t + timedelta(minutes=i)))
                if status == "aguardando":
                    db.add(FeatureCall(tenant_id=self.tid, conversation_id=f"c{i:02}", feature="handover",
                                       parameters="{}", result="{}", duration_ms="0",
                                       created_at=self.t + timedelta(minutes=12 - i)))
            db.add(Conversation(id="duplicate", tenant_id=self.tid, contact_id="p00",
                                status="lumi", created_at=self.t - timedelta(days=2)))
            db.add(Contact(id="foreign-contact", tenant_id=self.other, name="Outra empresa"))
            db.add(Conversation(id="foreign", tenant_id=self.other, contact_id="foreign-contact", created_at=self.t))
            for i in range(42):
                db.add(Message(id=f"history{i:02}", tenant_id=self.tid, conversation_id="c23",
                               sender="cliente" if i % 2 else "lumi", content=str(i),
                               created_at=self.t + timedelta(hours=1, minutes=i // 2)))
            db.add(Message(id="before-today", tenant_id=self.tid, conversation_id="c23",
                           sender="cliente", content="ontem", created_at=self.t - timedelta(seconds=1)))

    def get(self, path, **params):
        return self.http.get("/api/admin/" + path, params=params).raise_for_status().json()

    def test_contact_filters_are_paginated_and_search_is_global(self):
        first = self.get("conversation-page")
        self.assertEqual(len(first["items"]), 10)
        self.assertEqual(first["items"][0]["id"], "c23")
        self.assertNotIn("messages", first["items"][0])
        self.assertEqual(first["items"][0]["last_message"]["content"], "41")
        self.assertEqual(first["waiting_count"], 12)
        next_page = self.get("conversation-page", cursor=first["next_cursor"])
        end = self.get("conversation-page", cursor=next_page["next_cursor"])
        found = first["items"] + next_page["items"] + end["items"]
        self.assertEqual(len(found), 24)
        self.assertEqual(len({item["contact_id"] for item in found}), 24)
        self.assertIsNone(end["next_cursor"])
        self.assertEqual(self.get("conversation-page", q="#p00")["items"][0]["id"], "c00")
        self.assertEqual(self.get("conversation-page", q="Pessoa 00")["items"][0]["id"], "c00")
        self.assertEqual(self.get("conversation-page", q="foreign")["items"], [])

        waiting = self.get("conversation-page", status="aguardando")
        self.assertEqual([item["id"] for item in waiting["items"]], [f"c{i:02}" for i in range(11, 1, -1)])
        self.assertEqual(len(self.get("conversation-page", status="aguardando", cursor=waiting["next_cursor"])["items"]), 2)
        human = self.get("conversation-page", status="humano")
        self.assertEqual(len(human["items"]), 10)
        self.assertEqual(len(self.get("conversation-page", status="humano", cursor=human["next_cursor"])["items"]), 2)

    def test_history_starts_with_latest_twenty_and_keeps_tied_rows(self):
        path = "conversations/c23/history"
        latest = self.get(path)
        self.assertEqual([m["content"] for m in latest["messages"]], [str(i) for i in range(22, 42)])
        middle = self.get(path, cursor=latest["next_cursor"])
        self.assertEqual([m["content"] for m in middle["messages"]], [str(i) for i in range(2, 22)])
        oldest = self.get(path, cursor=middle["next_cursor"])
        self.assertEqual([m["id"] for m in oldest["messages"]], ["before-today", "initial23", "history00", "history01"])
        self.assertIsNone(oldest["next_cursor"])
        self.assertEqual(self.http.get("/api/admin/conversations/foreign/history").status_code, 404)
        self.assertEqual(self.http.get("/api/admin/" + path, params={"cursor": "[]"}).status_code, 422)

    def test_dashboard_uses_local_day_and_counts_beyond_the_visible_page(self):
        today = self.get("dashboard", start="2026-11-10", end="2026-11-10")
        self.assertEqual((today["att"], today["msg"], today["opened"], today["total"]), (24, 45, 0, 25))
        self.assertEqual(today["channels"], {"simulator": 24})
        self.assertEqual(today["statuses"], {"aguardando": 12, "humano": 12})
        self.assertEqual(len(today["recent"]), 4)
        yesterday = self.get("dashboard", start="2026-11-09", end="2026-11-09")
        self.assertEqual((yesterday["att"], yesterday["msg"], yesterday["opened"]), (1, 1, 24))
        self.assertEqual(yesterday["recent"][0]["last_message"]["content"], "ontem")