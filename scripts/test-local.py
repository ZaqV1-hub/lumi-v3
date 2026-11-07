"""Testes isolados; PostgreSQL opcional por arquivo privado, sem chamadas externas."""
import argparse
import ipaddress
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--postgres-env', type=Path, help='Arquivo com LUMI_TEST_POSTGRES_URL local e CREATEDB')
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
os.chdir(root)
sys.path.insert(0, str(root))
os.environ.pop('DATABASE_URL', None)
os.environ.pop('OPENAI_API_KEY', None)
os.environ.pop('LUMI_TEST_POSTGRES_URL', None)
if args.postgres_env:
    url = dotenv_values(args.postgres_env).get('LUMI_TEST_POSTGRES_URL')
    if not url or make_url(url).host not in {'localhost', '127.0.0.1', '::1'}:
        raise SystemExit('Informe uma conexão PostgreSQL de teste em loopback.')
    os.environ['LUMI_TEST_POSTGRES_URL'] = url

connect = socket.socket.connect
run = subprocess.run


def local_connect(sock, address):
    if isinstance(address, tuple):
        try:
            allowed = ipaddress.ip_address(address[0]).is_loopback
        except ValueError:
            allowed = address[0] == 'localhost'
        if not allowed:
            raise RuntimeError('Rede externa bloqueada nos testes locais')
    return connect(sock, address)


def no_real_codex(command, *args, **kwargs):
    executable = command[0] if isinstance(command, (list, tuple)) else command.split()[0]
    if Path(executable).stem.lower() == 'codex':
        raise RuntimeError('Codex real bloqueado nos testes; use mock do provider')
    return run(command, *args, **kwargs)


with tempfile.TemporaryDirectory(prefix='lumi-test-') as folder:
    os.environ.update(LUMI_DATA_DIR=folder, LOCALAPPDATA=folder,
                      LUMI_TOOLS_ENV=str(Path(folder) / 'tools.env'),
                      RINCAO_TOOLS_ENV=str(Path(folder) / 'rincao-tools.env'),
                      RINCAO_COMMERCE_DATA_DIR=folder,
                      LUMI_PROVIDER='codex', LUMI_SEED_DEMO='true')
    with patch.object(socket.socket, 'connect', local_connect), patch.object(subprocess, 'run', no_real_codex):
        suite = unittest.defaultTestLoader.discover('tests')
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
