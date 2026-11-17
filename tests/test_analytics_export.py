import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, select, text


class AnalyticsExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {"LUMI_DATA_DIR": cls.environment.name,
                                         "DATABASE_URL": "sqlite:///:memory:"})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.environment.cleanup()

    def setUp(self):
        from app.models import FeatureCall
        self.assertTrue(hasattr(FeatureCall, "created_at"), "Tool audit needs its actual event timestamp")
        from app import analytics_export as export
        from app.analytics_models import AnalyticsActivation, AnalyticsReceipt
        from app.db import Base, Session
        from app.incoming_models import IncomingAttachment
        from app.media_models import ContactGate
        from app.models import Tenant, Contact, Conversation, Message
        from app.whatsapp.models import Channel, Chat
        self.export = export
        self.session = Session
        self.previous = Session.kw["bind"]
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + self.directory.name + "/analytics.db")
        Base.metadata.create_all(self.engine)
        Session.configure(bind=self.engine)
        self.addCleanup(self.cleanup)
        self.config = export.Config("tenant-a", "http://127.0.0.1:8011/analytics", "ANALYTICS_TEST_SECRET", "visits-sheet")
        self.start = datetime(2030, 1, 1, tzinfo=timezone.utc)
        with Session.begin() as db:
            for suffix in ("a", "b"):
                db.add(Tenant(id="tenant-" + suffix, name="Fictional " + suffix, slug=suffix,
                              identity="", personality=""))
                db.flush()
                db.add(Contact(id="contact-" + suffix, tenant_id="tenant-" + suffix, name="Fictional", role="cliente"))
                db.flush()
                db.add(Conversation(id="conversation-" + suffix, tenant_id="tenant-" + suffix,
                                    contact_id="contact-" + suffix, status="lumi"))
                db.add(Channel(phone_number_id="channel-" + suffix, tenant_id="tenant-" + suffix))
                db.flush()
                db.add(Chat(id="conversation-" + suffix, phone_number_id="channel-" + suffix,
                            sender="5511000000000", token="fictional"))
        export.prepare(self.config, engine=self.engine, activated_at=self.start)

    def cleanup(self):
        self.session.configure(bind=self.previous)
        self.engine.dispose()
        self.directory.cleanup()

    def message(self, identifier, *, tenant="a", at=None, content="Tem piscina?", sender="cliente"):
        from app.models import Message
        with self.session.begin() as db:
            db.add(Message(id=identifier, tenant_id="tenant-" + tenant,
                           conversation_id="conversation-" + tenant, sender=sender,
                           content=content, created_at=at or self.start + timedelta(seconds=1)))

    def records(self):
        with self.session() as db:
            return self.export.collect(db, self.config)

    def test_only_new_whatsapp_messages_from_configured_tenant(self):
        from app.models import Conversation, Message
        self.message("old", at=self.start - timedelta(seconds=1))
        self.message("new")
        self.message("foreign", tenant="b")
        with self.session.begin() as db:
            db.add(Conversation(id="simulator", tenant_id="tenant-a", contact_id="contact-a"))
            db.flush()
            db.add(Message(id="simulated", tenant_id="tenant-a", conversation_id="simulator",
                           sender="cliente", content="private", created_at=self.start + timedelta(seconds=2)))
        self.assertEqual([r["id"] for r in self.records()], ["message-new"])
        self.assertEqual(self.records()[0]["content"], "Tem piscina?")

    def test_late_committed_source_is_not_skipped_by_a_timestamp_cursor(self):
        self.message("first", at=self.start + timedelta(seconds=10))
        self.export.run(self.config, send=lambda c, rs: [r["id"] for r in rs])
        self.message("late", at=self.start + timedelta(seconds=2))
        self.assertEqual([r["id"] for r in self.records()], ["message-late"])

    def test_timeout_and_partial_ack_leave_unconfirmed_records_pending(self):
        self.message("one")
        self.message("two")
        with self.assertRaises(TimeoutError):
            self.export.run(self.config, send=lambda *_: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(len(self.records()), 2)
        self.export.run(self.config, max_batches=1, send=lambda c, rs: [rs[0]["id"]])
        self.assertEqual(len(self.records()), 1)
        self.export.run(self.config, send=lambda c, rs: [r["id"] for r in rs])
        self.assertEqual(self.records(), [])

    def test_long_text_is_split_stably_without_loss_or_duplicate_acked_parts(self):
        content = "=literal" + "á" * 90000
        self.message("long", content=content)
        rows = self.records()
        self.assertEqual("".join(r["content"] for r in rows), content)
        self.assertTrue(all(len(r["content"]) <= 45000 for r in rows))
        self.assertTrue(all(r["message_id"] == "long" for r in rows))
        first = rows[0]["id"]
        self.export.run(self.config, max_batches=1, send=lambda c, rs: [first])
        self.assertNotIn(first, [r["id"] for r in self.records()])
        self.export.run(self.config, send=lambda c, rs: [r["id"] for r in rs])
        self.assertEqual(self.records(), [])

    def test_pending_contact_and_audio_do_not_freeze_unfinished_transcription(self):
        from app.media_models import ContactGate
        from app.incoming_models import IncomingAttachment
        from app.models import Message
        self.message("audio", content="[Áudio enviado]")
        with self.session.begin() as db:
            db.add(ContactGate(contact_id="contact-a", pending=1))
        self.assertEqual(self.records(), [])
        with self.session.begin() as db:
            db.add(IncomingAttachment(message_id="audio", tenant_id="tenant-a", conversation_id="conversation-a",
                                      kind="audio", mime="audio/ogg", data=b"fictional", state="received"))
        self.assertEqual(self.records(), [])
        with self.session.begin() as db:
            db.get(ContactGate, "contact-a").pending = 0
            db.get(IncomingAttachment, "audio").state = "transcribed"
            db.get(Message, "audio").content = "[Transcrição do áudio]\nQuero visitar"
        self.assertIn("Quero visitar", self.records()[0]["content"])

    def test_untranscribed_audio_without_pending_ai_is_still_exported(self):
        from app.incoming_models import IncomingAttachment
        from app.models import Conversation
        self.message("human-audio", content="[Áudio enviado]")
        with self.session.begin() as db:
            db.get(Conversation, "conversation-a").status = "humano"
            db.add(IncomingAttachment(message_id="human-audio", tenant_id="tenant-a", conversation_id="conversation-a",
                                      kind="audio", mime="audio/ogg", data=b"fictional", state="received"))
        self.assertEqual(self.records()[0]["content"], "[Áudio enviado]")

    def test_event_duration_above_sink_limit_is_not_a_poison_record(self):
        from app.models import FeatureCall
        self.message("duration")
        with self.session.begin() as db:
            db.add(FeatureCall(id="duration-event", tenant_id="tenant-a", conversation_id="conversation-a",
                message_id="duration", created_at=self.start + timedelta(seconds=2), feature="reservar_visita",
                parameters="{}", result='{"ok":false}', duration_ms="86400001"))
        event = next(r for r in self.records() if r["kind"] == "event")
        self.assertIsNone(event["duration_ms"])

    def test_events_are_linked_and_project_only_public_fields(self):
        from app.models import FeatureCall
        from app.usage_models import ModelCall
        self.message("question")
        with self.session.begin() as db:
            db.add(FeatureCall(id="tool1", tenant_id="tenant-a", conversation_id="conversation-a",
                message_id="question", created_at=self.start + timedelta(seconds=2), feature="reservar_visita",
                parameters=json.dumps({"secret": "must-not-leak"}),
                result=json.dumps({"data": {"ok": False, "error": "ocupado", "detail": "must-not-leak"}}), duration_ms="53"))
            db.add(FeatureCall(id="wrong", tenant_id="tenant-b", conversation_id="conversation-b",
                message_id="question", created_at=self.start + timedelta(seconds=2), feature="private",
                parameters="{}", result="{}", duration_ms="0"))
            db.add(ModelCall(id="model1", tenant_id="tenant-a", conversation_id="conversation-a",
                message_id="question", provider="codex", model="fixture", status="completed", duration_ms=20,
                created_at=self.start + timedelta(seconds=3)))
        rows = self.records()
        self.assertEqual({r["id"] for r in rows}, {"message-question", "tool-tool1", "model-model1"})
        event = next(r for r in rows if r["id"] == "tool-tool1")
        self.assertEqual(event["error_code"], "ocupado")
        self.assertEqual(event["duration_ms"], 53)
        self.assertNotIn("must-not-leak", json.dumps(rows))

    def test_scope_is_validated_before_recording_message_id(self):
        from app.analytics_models import scoped_message_id
        from app.usage import usage_scope
        self.assertIsNone(scoped_message_id("tenant-a", "conversation-a"))
        with usage_scope("tenant-a", "conversation-a", "question"):
            self.assertEqual(scoped_message_id("tenant-a", "conversation-a"), "question")
            self.assertIsNone(scoped_message_id("tenant-b", "conversation-a"))

    def test_tool_audit_captures_triggering_message_even_when_access_is_denied(self):
        from app import tools
        from app.db import Base
        from app.models import FeatureCall
        from app.usage import usage_scope
        Base.metadata.create_all(self.engine)
        self.message("trigger")
        with usage_scope("tenant-a", "conversation-a", "trigger"), \
                patch.object(tools.urllib.request, "urlopen", side_effect=AssertionError("No network")):
            self.assertEqual(tools.execute_tool("tenant-a", "conversation-a", {"name": "missing"}, 0),
                             {"error": "acesso_negado"})
        with self.session() as db:
            audit = db.scalar(select(FeatureCall))
            self.assertEqual(audit.message_id, "trigger")
            self.assertIsNotNone(audit.created_at)

    def test_handover_audit_preserves_message_scope_without_exporting_reason(self):
        from app import features
        from app.models import Feature, FeatureCall
        from app.usage import usage_scope
        self.message("handover")
        with self.session.begin() as db:
            db.add(Feature(tenant_id="tenant-a", name="handover", description="fixture",
                           endpoint="http://127.0.0.1:9999", roles="cliente", enabled=True))
        with usage_scope("tenant-a", "conversation-a", "handover"), \
                patch.object(features.urllib.request, "urlopen", return_value=io.BytesIO(b'{"accepted":true}')):
            features.request_handover("tenant-a", "conversation-a", "cliente", "must-not-leak")
        with self.session() as db:
            audit = db.scalar(select(FeatureCall))
            self.assertEqual(audit.message_id, "handover")
        self.assertNotIn("must-not-leak", json.dumps(self.records()))

    def test_prepare_is_preserving_and_rejects_destination_rebinding(self):
        from app.analytics_models import AnalyticsActivation
        self.message("kept")
        self.export.prepare(self.config, engine=self.engine, activated_at=self.start + timedelta(days=1))
        with self.session() as db:
            active = db.get(AnalyticsActivation, ("tenant-a", "visits-sheet"))
            self.assertEqual(active.activated_at.replace(tzinfo=timezone.utc), self.start)
        changed = self.export.Config("tenant-a", "https://other.example.test/analytics", "ANALYTICS_TEST_SECRET", "visits-sheet")
        with self.assertRaises(ValueError):
            self.export.prepare(changed, engine=self.engine)
        self.assertEqual([r["id"] for r in self.records()], ["message-kept"])

    def test_explicit_migration_adds_nullable_columns_without_backfilling(self):
        legacy = create_engine("sqlite:///:memory:")
        self.addCleanup(legacy.dispose)
        with legacy.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE tenants (id VARCHAR(36) PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO tenants VALUES ('tenant-a')")
            connection.exec_driver_sql("CREATE TABLE feature_calls (id VARCHAR(36) PRIMARY KEY, result TEXT)")
            connection.exec_driver_sql("INSERT INTO feature_calls VALUES ('old', 'preserve')")
        self.export.prepare(self.config, engine=legacy, activated_at=self.start)
        with legacy.connect() as connection:
            self.assertEqual(tuple(connection.execute(text("SELECT result, created_at, message_id FROM feature_calls")).one()),
                             ("preserve", None, None))

    def test_migrate_changes_schema_without_activating_export(self):
        from app.analytics_models import AnalyticsActivation
        config = self.export.Config("tenant-b", self.config.endpoint, self.config.secret_env, "visits-sheet")
        self.export.migrate(config, engine=self.engine)
        self.export.migrate(config, engine=self.engine)
        with self.session() as db:
            self.assertIsNone(db.get(AnalyticsActivation, ("tenant-b", "visits-sheet")))
            with self.assertRaises(ValueError):
                self.export.collect(db, config)

    def test_entrypoint_loads_selected_database_before_importing_application(self):
        folder = Path(self.directory.name)
        env_file = folder / 'export.env'
        env_file.write_text('DATABASE_URL=' + self.engine.url.render_as_string(hide_password=False) + '\n', encoding='utf-8')
        config_file = folder / 'export.json'
        config_file.write_text(json.dumps(self.config.__dict__), encoding='utf-8')
        script = Path(__file__).resolve().parent.parent / 'scripts' / 'export-analytics.py'
        result = subprocess.run([sys.executable, str(script), '--env-file', str(env_file),
            '--config', str(config_file), '--action', 'migrate'], capture_output=True, text=True,
            env=os.environ | {'DATABASE_URL': 'invalid://must-not-be-used'}, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['migrated'])

    def test_endpoint_and_ack_validation_prevent_credentials_leak_and_false_receipts(self):
        for endpoint in ("http://example.test/analytics", "https://user:secret@example.test/analytics",
                         "https://example.test/analytics?token=secret", "http://127.0.0.1:8011/other"):
            with self.assertRaises(ValueError):
                self.export.Config("tenant-a", endpoint, "ANALYTICS_TEST_SECRET", "visits-sheet").validate()
        self.message("one")
        with self.assertRaises(ValueError):
            self.export.run(self.config, send=lambda c, rs: ["not-in-batch"])
        self.assertEqual(len(self.records()), 1)
        with patch.dict(os.environ, {"ANALYTICS_TEST_SECRET": "a" * 32}), \
                patch("urllib.request.OpenerDirector.open", return_value=io.BytesIO(b'{"ok":true,"accepted":["message-one"]}')) as network:
            self.assertEqual(self.export.send_batch(self.config, self.records()), ["message-one"])
            self.assertEqual(network.call_args.args[0].headers["Authorization"], "Bearer " + "a" * 32)

    def test_non_public_error_text_is_not_exported(self):
        from app.models import FeatureCall
        self.message("failure")
        with self.session.begin() as db:
            db.add(FeatureCall(id="error", tenant_id="tenant-a", conversation_id="conversation-a",
                message_id="failure", created_at=self.start + timedelta(seconds=2), feature="handover",
                parameters="{}", result=json.dumps({"error": "Authorization: Bearer private-token"}), duration_ms="3"))
        event = next(r for r in self.records() if r["kind"] == "event")
        self.assertEqual(event["error_code"], "unclassified_error")
        self.assertNotIn("private-token", json.dumps(event))

    def test_batch_is_bounded_and_old_events_are_not_starved_by_new_messages(self):
        from app.models import FeatureCall
        self.message("trigger", at=self.start + timedelta(seconds=1))
        self.export.run(self.config, send=lambda c, rs: [r["id"] for r in rs])
        with self.session.begin() as db:
            db.add(FeatureCall(id="old-event", tenant_id="tenant-a", conversation_id="conversation-a",
                message_id="trigger", created_at=self.start + timedelta(seconds=2), feature="bad feature name",
                parameters="{}", result='{"ok":true}', duration_ms="1"))
        for index in range(25):
            self.message(f"bulk-{index:02}", at=self.start + timedelta(seconds=3), content="\x01" * 10000)
        rows = self.records()
        self.assertEqual(rows[0]["id"], "tool-old-event")
        self.assertEqual(rows[0]["operation"], "unknown")
        self.assertLessEqual(len(rows), 20)
        self.assertLessEqual(len(json.dumps({"tenant_id":"tenant-a", "records":rows},ensure_ascii=False).encode()), 256*1024)


if __name__ == "__main__":
    unittest.main()
