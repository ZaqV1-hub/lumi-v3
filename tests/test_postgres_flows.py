"""Executa os fluxos existentes com PostgreSQL real e banco novo por teste.

Somente a criação do engine da fixture é redirecionada; queries, transações,
API, permissões e concorrência usam o PostgreSQL. Nunca usa DATABASE_URL.
"""
from contextlib import ExitStack
import importlib
import io
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import sqlalchemy
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# unittest discover adiciona tests ao caminho de importação.
from test_isolation import FlowTest
from test_console import ConsoleTest
from test_message_order import MessageOrderTest
from test_tools import ToolsTest
from test_usage_report import UsageReportTest
from test_tenant_ai import TenantAITest


class PostgresFixture:
    def setUp(self):
        url = make_url(os.environ['LUMI_TEST_POSTGRES_URL'])
        if url.get_backend_name() != 'postgresql':
            raise RuntimeError('Use PostgreSQL de teste explícito')
        admin = create_engine(url, isolation_level='AUTOCOMMIT', hide_parameters=True)
        name = 'lumi_flow_test_' + uuid4().hex
        with admin.connect() as db:
            db.execute(text('CREATE DATABASE ' + name))
        engine = create_engine(url.set(database=name), hide_parameters=True)

        def cleanup():
            engine.dispose()
            with admin.connect() as db:
                db.execute(text('DROP DATABASE ' + name + ' WITH (FORCE)'))
            admin.dispose()

        self.addCleanup(cleanup)
        # A fixture original continua responsável pelos seus dados e cleanup.
        module = importlib.import_module(self.fixture_class.__module__)
        with ExitStack() as stack:
            factory = stack.enter_context(patch.object(sqlalchemy, 'create_engine', return_value=engine))
            if hasattr(module, 'create_engine'):
                factory = stack.enter_context(patch.object(module, 'create_engine', return_value=engine))
            super().setUp()
            if not factory.called:
                raise AssertionError('Fixture não utilizou o banco PostgreSQL de teste')


def postgres_case(base):
    cls = type('Postgres' + base.__name__, (PostgresFixture, base), {'fixture_class': base})
    return unittest.skipUnless(os.getenv('LUMI_TEST_POSTGRES_URL'), 'PostgreSQL de teste não configurado')(cls)


PostgresFlowTest = postgres_case(FlowTest)
PostgresConsoleTest = postgres_case(ConsoleTest)
PostgresMessageOrderTest = postgres_case(MessageOrderTest)
@unittest.skipUnless(os.getenv('LUMI_TEST_POSTGRES_URL'), 'PostgreSQL de teste não configurado')
class PostgresToolsTest(PostgresFixture, ToolsTest):
    fixture_class = ToolsTest

    def test_openai_tool_roundtrip_records_both_calls_in_postgres(self):
        from app import tools
        from app.usage_models import ModelCall
        from sqlalchemy import select

        answers = [
            {'reply': '', 'action': 'call_tool', 'tool_call': {
                'name': 'consultar_agenda', 'arguments': {'start_date': None, 'end_date': None}}},
            {'reply': 'Resultado fictício da consulta.', 'action': 'none', 'tool_call': None},
        ]
        requests = []

        def respond(request):
            requests.append(request)
            value = {**answers[len(requests)-1], 'image_id': None,
                     'profile_updates': [], 'asked_objective_id': None}
            return httpx.Response(200, json={'status': 'completed', 'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(value)}]}],
                'usage': {'input_tokens': 20, 'output_tokens': 10,
                          'input_tokens_details': {'cached_tokens': 0}}})

        client_class = httpx.Client
        from cryptography.fernet import Fernet
        from app.tenant_ai import TenantAI, encrypt_key
        with patch.dict(os.environ, {'LUMI_AI_SECRET_KEY': Fernet.generate_key().decode()}):
            with self.session.begin() as db:
                db.add(TenantAI(tenant_id=self.tid, provider='openai', model='test-model',
                               encrypted_api_key=encrypt_key(self.tid, 'sk-test-synthetic-key-for-postgres')))
            self._openai_roundtrip(client_class, respond, requests)
        with self.session() as db:
            calls = list(db.scalars(select(ModelCall).where(ModelCall.conversation_id == self.cid)))
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(c.provider == 'openai' and c.status == 'completed' for c in calls))
            self.assertTrue(all(c.input_tokens == 20 and c.estimated_usd is None for c in calls))

    def _openai_roundtrip(self, client_class, respond, requests):
        from app import tools
        with patch('app.openai_provider.httpx.Client',
                      side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(respond))), \
                patch.object(tools.urllib.request, 'urlopen',
                             return_value=io.BytesIO(b'{"ok":true,"available":true}')) as service:
            self.send('Consulte a agenda de teste.').raise_for_status()
        self.assertEqual(len(requests), 2)
        service.assert_called_once()

PostgresUsageReportTest = postgres_case(UsageReportTest)
PostgresTenantAITest = postgres_case(TenantAITest)


def load_tests(loader, tests, pattern):
    # Não descobrir novamente as classes SQLite importadas acima.
    return unittest.TestSuite(loader.loadTestsFromTestCase(cls) for cls in (
        PostgresFlowTest, PostgresConsoleTest, PostgresMessageOrderTest,
        PostgresToolsTest, PostgresUsageReportTest, PostgresTenantAITest,
    ))
