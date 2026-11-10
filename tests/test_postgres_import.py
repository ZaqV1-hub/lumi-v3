"""Conversão com dados fictícios; PostgreSQL só por URL de teste explícita."""
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from app.import_sqlite import ImportRejected, convert_value, import_sqlite
from app.schema import metadata


class ConversionTest(unittest.TestCase):
    def test_types_do_not_silently_change_invalid_data(self):
        self.assertIs(convert_value(Boolean(), 0), False)
        self.assertIs(convert_value(Boolean(), 1), True)
        with self.assertRaises(ImportRejected):
            convert_value(Boolean(), 2)
        self.assertEqual(convert_value(Date(), '2026-11-05'), date(2026, 11, 5))
        self.assertEqual(convert_value(DateTime(timezone=True), '2026-11-05 12:00:00'),
                         datetime(2026, 11, 5, 12, tzinfo=timezone.utc))


@unittest.skipUnless(os.getenv('LUMI_TEST_POSTGRES_URL'), 'PostgreSQL de teste não configurado')
class PostgresImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Cria e remove somente banco com nome aleatório criado por esta suíte.
        base_url = make_url(os.environ['LUMI_TEST_POSTGRES_URL'])
        if base_url.get_backend_name() != 'postgresql':
            raise RuntimeError('URL de teste deve usar PostgreSQL')
        cls.admin = create_engine(base_url, isolation_level='AUTOCOMMIT', hide_parameters=True)
        cls.database = 'lumi_import_test_' + uuid4().hex
        with cls.admin.connect() as db:
            db.execute(text('CREATE DATABASE ' + cls.database))
        cls.target = create_engine(base_url.set(database=cls.database), hide_parameters=True)

    @classmethod
    def tearDownClass(cls):
        cls.target.dispose()
        with cls.admin.connect() as db:
            db.execute(text('DROP DATABASE ' + cls.database + ' WITH (FORCE)'))
        cls.admin.dispose()

    def setUp(self):
        with self.target.begin() as db:
            db.execute(text('DROP SCHEMA public CASCADE'))
            db.execute(text('CREATE SCHEMA public'))
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.source = Path(self.folder.name) / 'source.db'
        engine = create_engine('sqlite:///' + str(self.source))
        metadata.create_all(engine)
        self.source_tables = set(inspect(engine).get_table_names())
        with engine.begin() as db:
            db.execute(metadata.tables['tenants'].insert(), dict(id='tenant-test', name='Empresa fictícia',
                       slug='empresa-teste', identity='Identidade de teste', personality='Tom neutro'))
            db.execute(metadata.tables['tenant_runtime'].insert(), dict(tenant_id='tenant-test', listed=True, lumi_enabled=False))
            db.execute(metadata.tables['image_assets'].insert(), dict(id='image-test', tenant_id='tenant-test',
                       name='Imagem teste', description='Descrição', when_to_use='Teste', data=b'\x00\xffPNG\x80', enabled=True))
            db.execute(metadata.tables['tenant_features'].insert(), dict(id='feature-test', tenant_id='tenant-test',
                       name='consulta_teste', description='Consulta fictícia', endpoint='http://127.0.0.1:9/disabled/feature-test',
                       roles='cliente', enabled=False))
            db.execute(metadata.tables['tool_contracts'].insert(), dict(feature_id='feature-test',
                       parameters_schema='{"type":"object","properties":{}}', secret_env='TEST_SECRET'))
        engine.dispose()

    def test_import_preserves_ids_blob_types_source_and_disabled_state(self):
        with sqlite3.connect(self.source) as db:
            db.execute('CREATE TABLE legacy_empty (id TEXT)')
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        report = import_sqlite(self.source, self.target)
        self.assertEqual(report['tables']['tenants'], 1)
        self.assertEqual(report['ignored_empty_tables'], ['legacy_empty'])
        self.assertEqual(report['source_sha256'], before)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)
        self.assertEqual(set(inspect(self.target).get_table_names()), self.source_tables)
        with self.target.connect() as db:
            self.assertEqual(db.scalar(select(metadata.tables['image_assets'].c.data)), b'\x00\xffPNG\x80')
            self.assertIs(db.scalar(select(metadata.tables['tenant_runtime'].c.lumi_enabled)), False)
            self.assertIs(db.scalar(select(metadata.tables['image_assets'].c.enabled)), True)
            self.assertEqual(db.scalar(select(metadata.tables['tool_contracts'].c.parameters_schema)),
                             '{"type":"object","properties":{}}')

    def test_refuses_existing_target_without_touching_it(self):
        with self.target.begin() as db:
            db.execute(text('CREATE TABLE existing_data (id integer)'))
            db.execute(text('INSERT INTO existing_data VALUES (7)'))
        with self.assertRaises(ImportRejected):
            import_sqlite(self.source, self.target)
        with self.target.connect() as db:
            self.assertEqual(db.scalar(text('SELECT id FROM existing_data')), 7)
        self.assertEqual(inspect(self.target).get_table_names(), ['existing_data'])

    def test_rejects_non_sanitized_sources_before_creating_tables(self):
        for mutation in [
            'UPDATE tenant_runtime SET lumi_enabled=1',
            'DELETE FROM tenant_runtime',
            'UPDATE tenant_features SET enabled=1',
            "UPDATE tenant_features SET endpoint='https://live.example/execute'",
            "INSERT INTO login_sessions VALUES ('private-session','operator')",
            'CREATE TABLE unexpected (id TEXT); INSERT INTO unexpected VALUES (\'x\')',
            'UPDATE image_assets SET enabled=2',
            "UPDATE image_assets SET tenant_id='missing-tenant'",
        ]:
            with self.subTest(mutation=mutation):
                copy = Path(self.folder.name) / 'invalid.db'
                copy.write_bytes(self.source.read_bytes())
                with sqlite3.connect(copy) as db:
                    db.executescript(mutation)
                with self.assertRaises(ImportRejected):
                    import_sqlite(copy, self.target)
                self.assertEqual(inspect(self.target).get_table_names(), [])
                copy.unlink()

    def test_failure_rolls_back_schema_and_records_without_leaking_data(self):
        with sqlite3.connect(self.source) as db:
            db.execute('UPDATE tenants SET name=?', ('private-value-' * 20,))
        with self.assertRaises(ImportRejected) as error:
            import_sqlite(self.source, self.target)
        self.assertNotIn('private-value', str(error.exception))
        self.assertEqual(inspect(self.target).get_table_names(), [])

    def test_two_imports_do_not_duplicate_data(self):
        def run():
            try:
                import_sqlite(self.source, self.target)
                return 'imported'
            except ImportRejected:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: run(), range(2))), ['imported', 'rejected'])
        with self.target.connect() as db:
            self.assertEqual(db.scalar(text('SELECT count(*) FROM tenants')), 1)


if __name__ == '__main__':
    unittest.main()
