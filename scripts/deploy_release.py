"""Pacote Git verificável e operações restritas às instalações existentes da V3."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED


BRANCHES = {"develop": "HML", "main": "PROD"}
REQUIRED = {"app/main.py", "app/whatsapp/webhook.py", "web/console.html",
            "requirements.txt", "requirements-vm.lock"}
EXTRA = {"requirements.txt", "requirements-vm.lock", "scripts/deploy_release.py",
         "scripts/export-analytics.py",
         "scripts/windows/deploy-release.ps1", "docs/privacy-policy.html",
         "docs/privacy-policy-draft.html"}


def allowed_path(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or str(path) != name or any(p in {".", "..", "__pycache__", "node_modules"}
                                       or p.startswith(".") or p.rstrip(" .") != p
                                       or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]",
                                                       p.split(".")[0], re.IGNORECASE)
                                       for p in path.parts)):
        return False
    if path.suffix.lower() in {".env", ".db", ".sqlite", ".sqlite3", ".dump", ".log",
                               ".zip", ".pem", ".key", ".pyc", ".pfx", ".p12", ".bak"}:
        return False
    return name in EXTRA or path.parts[0] in {"app", "web", "services", "demo"}


def validate_identity(commit, branch):
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or branch not in BRANCHES:
        raise ValueError("Commit ou branch inválidos")


def build_package(repo, output, commit, branch):
    validate_identity(commit, branch)
    records = subprocess.check_output(
        ["git", "ls-tree", "-rz", commit], cwd=repo).split(b"\0")
    files = {}
    for record in filter(None, records):
        metadata, raw_name = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        name = raw_name.decode()
        if not allowed_path(name):
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("Pacote não aceita links ou submódulos")
        files[name] = subprocess.check_output(["git", "cat-file", "blob", oid], cwd=repo)
    if not REQUIRED <= files.keys():
        raise ValueError("Arquivos obrigatórios ausentes")
    files["deployment.json"] = json.dumps({"commit": commit, "branch": branch}, sort_keys=True).encode()
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    files["release-manifest.json"] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return {"sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "files": len(files)}


def prepare_release(root, archive, expected_hash, commit, branch, release_id):
    validate_identity(commit, branch)
    if not re.fullmatch(r"gha-" + commit[:12] + r"-\d+-\d+", release_id):
        raise ValueError("Identificador de release inválido")
    release = root / "releases" / release_id
    if release.exists():
        raise ValueError("Release já existe; use uma nova tentativa")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("Hash do pacote divergente")
    with ZipFile(archive) as zip_file:
        infos = zip_file.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or len(names) != len({n.casefold() for n in names}):
            raise ValueError("Entradas duplicadas")
        if sum(i.file_size for i in infos) > 100 * 1024 * 1024:
            raise ValueError("Pacote excede limite de tamanho")
        for i in infos:
            if (i.is_dir() or stat.S_ISLNK(i.external_attr >> 16)
                    or (i.filename not in {"deployment.json", "release-manifest.json"}
                        and not allowed_path(i.filename))):
                raise ValueError("Caminho ou tipo não permitido")
        if not REQUIRED | {"deployment.json", "release-manifest.json"} <= set(names):
            raise ValueError("Pacote incompleto")
        manifest = json.loads(zip_file.read("release-manifest.json"))
        if not isinstance(manifest, dict) or set(manifest) != set(names) - {"release-manifest.json"}:
            raise ValueError("Manifesto incompleto")
        files = {name: zip_file.read(name) for name in names}
        if any(hashlib.sha256(files[name]).hexdigest() != value for name, value in manifest.items()):
            raise ValueError("Arquivo divergente do manifesto")
        if json.loads(files["deployment.json"]) != {"commit": commit, "branch": branch}:
            raise ValueError("Metadados não correspondem à publicação")
        # O venv é compartilhado pelas releases deste ambiente; não o modificar no deploy.
        for name in ("requirements.txt", "requirements-vm.lock"):
            if files[name] != (root / "current" / name).read_bytes():
                raise ValueError("Dependências alteradas: preparar migração do venv separadamente")
    release.mkdir(parents=True, exist_ok=False)
    try:
        for name, data in files.items():
            destination = release / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    except Exception:
        shutil.rmtree(release)
        raise
    return release


def database_config(root, environment):
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url
    config = dotenv_values(root / "private" / f"{environment.lower()}.env")
    url = make_url(config["DATABASE_URL"])
    port = 5442 if environment == "HML" else 5441
    expected = "lumi_v3_" + environment.lower()
    if (url.host not in {"127.0.0.1", "localhost"} or url.port != port
            or url.database != expected or url.username != expected
            or config.get("LUMI_SEED_DEMO", "").lower() != "false"):
        raise ValueError("Configuração do ambiente fora do escopo autorizado")
    return url


def backup_database(root, environment, release_id):
    url = database_config(root, environment)
    pg_bin = Path("C:/Lumi/runtime/pg17/pgsql/bin" if environment == "HML" else "C:/pgsql/16/bin")
    destination = root / "backups" / f"before-{release_id}.dump"
    partial = destination.with_suffix(".partial")
    if destination.exists() or partial.exists():
        raise ValueError("Backup já existe")
    env = dict(os.environ, PGPASSWORD=url.password or "", PGCONNECT_TIMEOUT="15")
    result = subprocess.run([str(pg_bin / "pg_dump.exe"), "-w", "-h", url.host,
                             "-p", str(url.port), "-U", url.username, "-d", url.database,
                             "-Fc", "-f", str(partial)], env=env, capture_output=True, timeout=180)
    if result.returncode or not partial.exists() or not partial.stat().st_size:
        raise RuntimeError("Backup falhou; saída privada não exibida")
    result = subprocess.run([str(pg_bin / "pg_restore.exe"), "-l", str(partial)],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Backup não passou na leitura do catálogo")
    partial.rename(destination)


def migrate_whatsapp_follow_up(root, environment, release_id):
    if not release_id or not re.fullmatch(r"gha-[0-9a-f]{12}-\d+-\d+", release_id):
        raise ValueError("Identificador de migração inválido")
    url = database_config(root, environment)
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    sys.path.insert(0, str(root / "releases" / release_id))
    from app.db import Base, engine
    from app.documents import DocumentAsset, MessageDocument
    from app.whatsapp.follow_up import FollowUp, FollowUpChannel

    with engine.begin() as connection:
        Base.metadata.create_all(connection, tables=[
            DocumentAsset.__table__, MessageDocument.__table__, FollowUpChannel.__table__, FollowUp.__table__
        ])


def health(root, environment):
    import psycopg
    url = database_config(root, environment)
    port = 8012 if environment == "HML" else 8014
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/admin", timeout=5) as response:
                if response.status != 200 or b"<html" not in response.read().lower():
                    raise RuntimeError("Painel indisponível")
            try:
                urlopen(f"http://127.0.0.1:{port + 1}/webhooks/whatsapp", timeout=5)
                raise RuntimeError("Receptor não rejeitou challenge sem credencial")
            except HTTPError as exc:
                if exc.code != 403:
                    raise
            with psycopg.connect(host=url.host, port=url.port, dbname=url.database,
                                 user=url.username, password=url.password, connect_timeout=5) as db:
                with db.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM tenant_ai_settings LIMIT 1")
            return
        except (OSError, URLError, RuntimeError, psycopg.Error):
            time.sleep(3)
    raise RuntimeError("Saúde da V3 não confirmada no prazo")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["package", "prepare", "backup", "migrate-whatsapp-follow-up", "health"])
    parser.add_argument("--environment", choices=["HML", "PROD"])
    parser.add_argument("--commit")
    parser.add_argument("--branch", choices=list(BRANCHES))
    parser.add_argument("--release-id")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.operation == "package":
        print(json.dumps(build_package(Path.cwd(), args.output, args.commit, args.branch)))
        return
    if os.name != "nt" or not args.environment:
        raise ValueError("Operações remotas exigem Windows e ambiente explícito")
    root = Path("C:/LumiV3-" + args.environment)
    if args.operation == "prepare":
        if BRANCHES.get(args.branch) != args.environment:
            raise ValueError("Branch incompatível com o ambiente")
        database_config(root, args.environment)
        prepare_release(root, args.archive, args.sha256, args.commit, args.branch, args.release_id)
    elif args.operation == "backup":
        if not args.release_id or not re.fullmatch(r"gha-[0-9a-f]{12}-\d+-\d+", args.release_id):
            raise ValueError("Identificador de backup inválido")
        backup_database(root, args.environment, args.release_id)
    elif args.operation == "migrate-whatsapp-follow-up":
        migrate_whatsapp_follow_up(root, args.environment, args.release_id)
    else:
        health(root, args.environment)
    print(json.dumps({"operation": args.operation, "environment": args.environment, "ok": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Exceções de banco/rede podem conter conexão e credenciais.
        print(f"Deploy falhou ({type(exc).__name__}); confira a etapa, sem expor configuração privada.", file=sys.stderr)
        sys.exit(1)
