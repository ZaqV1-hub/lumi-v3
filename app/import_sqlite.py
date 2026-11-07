"""Importa configuração sanitizada de SQLite em PostgreSQL vazio, atomicamente."""
import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from sqlalchemy import Boolean, Date, DateTime, LargeBinary, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError

# Histórico, logins, canais e transações não pertencem à cópia de desenvolvimento.
CONFIGURATION_TABLES = frozenset({
    'tenants', 'tenant_runtime', 'tenant_chat_policies', 'knowledge_items',
    'image_assets', 'tenant_preferences', 'onboarding_objectives',
    'role_instructions', 'tenant_features', 'tool_contracts', 'business_report_grants',
})
IMPORT_LOCK = 437271902147


class ImportRejected(ValueError):
    """Erro público de importação, sem valores de registros ou conexão."""


def convert_value(column_type, value):
    if value is None:
        return None
    if isinstance(column_type, Boolean):
        if value not in (0, 1) or not isinstance(value, int):
            raise ImportRejected('Valor booleano inválido na origem.')
        return bool(value)
    if isinstance(column_type, DateTime):
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        if column_type.timezone and result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result
    if isinstance(column_type, Date):
        return date.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(column_type, LargeBinary):
        if not isinstance(value, (bytes, memoryview)):
            raise ImportRejected('Conteúdo binário inválido na origem.')
        return bytes(value)
    return value


def _read_source(source):
    """Lê um snapshot somente leitura, validando dados antes de tocar no destino."""
    from .schema import metadata

    source = Path(source).resolve(strict=True)
    if any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-journal')):
        raise ImportRejected('Use um backup SQLite independente, sem WAL ou journal.')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ImportRejected('Integridade SQLite inválida.')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ImportRejected('Relacionamentos inválidos na origem.')
        names = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not CONFIGURATION_TABLES.issubset(names):
            raise ImportRejected('Tabelas de configuração ausentes na origem.')
        rows, ignored = {}, []
        for name in sorted(names):
            quoted = '"' + name.replace('"', '""') + '"'
            count = db.execute('SELECT count(*) FROM ' + quoted).fetchone()[0]
            table = metadata.tables.get(name)
            if table is None:
                if count:
                    raise ImportRejected('Tabela desconhecida contém dados.')
                ignored.append(name)
                continue
            actual_columns = {r[1] for r in db.execute('PRAGMA table_info(' + quoted + ')')}
            if actual_columns != set(table.c.keys()):
                raise ImportRejected('Schema da origem incompatível com esta versão.')
            if name not in CONFIGURATION_TABLES and count:
                raise ImportRejected('A origem contém dados operacionais não sanitizados.')
            values = db.execute('SELECT * FROM ' + quoted).fetchall() if count else []
            rows[name] = [
                {c.name: convert_value(c.type, row[c.name]) for c in table.c}
                for row in values
            ]
        for name in metadata.tables:
            rows.setdefault(name, [])
        tenant_ids = {r['id'] for r in rows['tenants']}
        states = rows['tenant_runtime']
        if {r['tenant_id'] for r in states} != tenant_ids or any(r['lumi_enabled'] for r in states):
            raise ImportRejected('Todos os tenants precisam ter estado explicitamente desativado.')
        for row in rows['tenant_features']:
            if row['enabled'] or not row['endpoint'].startswith('http://127.0.0.1:9/disabled/'):
                raise ImportRejected('Ferramenta ativa ou endpoint não bloqueado na origem.')
        if any(r['enabled'] for r in rows['business_report_grants']):
            raise ImportRejected('Permissão de gestão ativa na origem.')
        return rows, ignored


def _comparable(rows, table):
    keys = [c.name for c in table.primary_key]
    return sorted(rows, key=lambda row: tuple(str(row[k]) for k in keys))


def import_sqlite(source, target_engine):
    """Preserva a origem; recusa destino existente e reverte toda falha de cópia."""
    if target_engine.dialect.name != 'postgresql':
        raise ImportRejected('O destino deve ser PostgreSQL.')
    try:
        from .schema import metadata

        source = Path(source).resolve(strict=True)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        rows, ignored = _read_source(source)
        if hashlib.sha256(source.read_bytes()).hexdigest() != before:
            raise ImportRejected('A origem mudou durante a leitura. Use um backup estável.')
        with target_engine.begin() as db:
            # Serializa dois importadores no mesmo banco antes de verificar o schema.
            db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': IMPORT_LOCK})
            db.execute(text('SET LOCAL search_path TO public'))
            occupied = db.scalar(text("""
                SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f','S'))
            """))
            if occupied:
                raise ImportRejected('O schema public do destino precisa estar vazio.')
            metadata.create_all(db)
            for table in metadata.sorted_tables:
                if rows[table.name]:
                    db.execute(table.insert(), rows[table.name])
            for table in metadata.sorted_tables:
                copied = [dict(row) for row in db.execute(select(table)).mappings()]
                if _comparable(copied, table) != _comparable(rows[table.name], table):
                    raise ImportRejected('Verificação dos registros importados falhou.')
            if hashlib.sha256(source.read_bytes()).hexdigest() != before:
                raise ImportRejected('A origem mudou durante a importação.')
        return {
            'source_sha256': before,
            'tables': {name: len(values) for name, values in sorted(rows.items())},
            'image_sha256': {r['id']: hashlib.sha256(r['data']).hexdigest() for r in rows['image_assets']},
            'ignored_empty_tables': ignored,
        }
    except ImportRejected:
        raise
    except (SQLAlchemyError, sqlite3.Error, OSError, ValueError, TypeError, AttributeError):
        # Exceções SQL podem conter senhas, textos e imagens nos parâmetros.
        raise ImportRejected('Importação recusada; confira conexão, schema, tipos e limites dos campos. Nenhum dado parcial foi confirmado.') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='Backup SQLite sanitizado')
    args = parser.parse_args()
    url = os.getenv('DATABASE_URL', '').strip()
    if not url:
        raise SystemExit('Defina DATABASE_URL para um PostgreSQL novo e exclusivo.')
    engine = None
    try:
        engine = create_engine(url, hide_parameters=True)
        report = import_sqlite(args.source, engine)
    except ImportRejected as error:
        raise SystemExit(str(error)) from None
    except (SQLAlchemyError, ValueError, ImportError):
        raise SystemExit('Importação recusada. Confira origem sanitizada, versão e PostgreSQL vazio; nenhum dado parcial foi confirmado.') from None
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
