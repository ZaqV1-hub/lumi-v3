import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app import main
from app.db import Session
from app.models import Tenant, User


class StartupSeedTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        engine = create_engine('sqlite:///' + self.folder.name + '/startup.db')
        self.addCleanup(engine.dispose)
        self.addCleanup(Session.configure, bind=Session.kw['bind'])
        Session.configure(bind=engine)

    def test_imported_environment_does_not_create_demo_accounts_or_tenants(self):
        with patch.dict(os.environ, {'LUMI_SEED_DEMO': 'false'}), TestClient(main.app):
            with Session() as db:
                self.assertEqual(db.scalar(select(func.count()).select_from(Tenant)), 0)
                self.assertEqual(db.scalar(select(func.count()).select_from(User)), 0)

    def test_explicit_demo_setup_keeps_existing_installation_behavior(self):
        with patch.dict(os.environ, {'LUMI_SEED_DEMO': 'true'}), TestClient(main.app):
            with Session() as db:
                self.assertGreater(db.scalar(select(func.count()).select_from(Tenant)), 0)


if __name__ == '__main__':
    unittest.main()
