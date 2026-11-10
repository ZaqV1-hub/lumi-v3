"""Startup keeps Calling migration explicit; shutdown drains dispatched work."""
import asyncio
import threading
import unittest
from unittest.mock import patch


class CallingLifecycleTest(unittest.TestCase):
    def setUp(self):
        from test_whatsapp_calling import CallingStateTest
        CallingStateTest.setUp(self)
        from app.db import Base, Session
        from app.whatsapp.calling_models import CALLING_TABLES
        previous = Session.kw['bind']
        Session.configure(bind=self.engine)
        self.addCleanup(Session.configure, bind=previous)
        Base.metadata.drop_all(self.engine, tables=list(reversed(CALLING_TABLES)))

    def test_real_admin_and_webhook_lifespans_leave_calling_schema_absent(self):
        from app import main
        from app.whatsapp import webhook
        async def exercise(module):
            async with module.lifespan(module.app):
                self.assertFalse(any(self.setup.inspect_schema(self.engine).values()))
                with self.session() as db:
                    self.assertFalse(self.calling.channel_enabled(db, tenant_id='tenant', phone_number_id='channel'))
        with patch.dict('os.environ', {'LUMI_SEED_DEMO': 'false'}), patch.object(main, 'load_config'), \
             patch.object(webhook, 'deliver_one', return_value=False), \
             patch.object(webhook, 'deliver_instagram', return_value=False), \
             patch.object(webhook, 'deliver_comment', return_value=False):
            for module in [main, webhook]:
                with self.subTest(module=module.__name__):
                    asyncio.run(exercise(module))
        self.setup.prepare_schema(self.engine)
        with self.session.begin() as db:
            self.setup.set_channel_enabled(db, tenant_id='tenant', phone_number_id='channel', enabled=True)
            self.assertTrue(self.calling.channel_enabled(db, tenant_id='tenant', phone_number_id='channel'))

    def test_reconciler_shutdown_waits_for_dispatched_work(self):
        from app.whatsapp import calling_reconcile
        entered = threading.Event()
        finish = threading.Event()
        completed = threading.Event()
        def dispatched():
            entered.set()
            finish.wait(timeout=5)
            completed.set()
        async def exercise():
            task = asyncio.create_task(calling_reconcile.run_reconciler())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertFalse(completed.is_set())
                finish.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=5)
                self.assertTrue(completed.is_set())
            finally:
                finish.set()
        with patch.object(calling_reconcile, 'reconcile_once', side_effect=dispatched) as work:
            asyncio.run(exercise())
            self.assertEqual(work.call_count, 1)
