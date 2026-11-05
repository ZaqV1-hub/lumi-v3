"""Exporta somente integrações revisadas; não copia núcleo, histórico ou configuração privada."""
import argparse
import ast
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES = ("web_tools", "rincao", "estancia")
SITE_FILES = (
    "src/lib/lumi-access.ts", "src/lib/lumi-access.test.ts", "src/lib/lumi-catalog.ts",
    "src/lib/lumi-commerce.ts", "src/app/api/lumi/[action]/route.ts",
    "src/app/lumi/checkout/[token]/page.tsx", "scripts/lumi-hml-schema.sql", "docs/lumi-hml.md",
)


def allowed(path):
    return path.is_file() and path.suffix.lower() in {".py", ".js", ".cjs", ".mjs", ".ts", ".mts", ".css", ".html", ".json", ".png", ".md", ".sql", ".txt"} and "__pycache__" not in path.parts


def export(destination, estancia_site=None):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Use uma pasta vazia; nenhum trabalho existente será sobrescrito")
    destination.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "integration-kit").rglob("*"):
        if source.is_file() and (allowed(source) or source.name in {".gitignore", ".env.example"}):
            relative = source.relative_to(ROOT / "integration-kit")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (destination / "services").mkdir(exist_ok=True)
    (destination / "services/__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(ROOT / "services/handover.py", destination / "services/handover.py")
    for service in SERVICES:
        for source in (ROOT / "services" / service).rglob("*"):
            if allowed(source):
                target = destination / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for source in (ROOT / "integrations/rincao-site").rglob("*"):
        if allowed(source) or source.suffix == ".patch":
            target = destination / "site-adapters/rincao" / source.relative_to(ROOT / "integrations/rincao-site")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    if estancia_site:
        estancia_site = Path(estancia_site)
        for name in SITE_FILES:
            target = destination / "site-adapters/estancia" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(estancia_site / name, target)
        # Só os trechos desta integração; não exporta alterações anteriores do site.
        (destination / "site-adapters/estancia/README.md").write_text(
            "Este adaptador depende do projeto do site Estância. Os arquivos novos estão aqui; "
            "o checkout existente também precisa encaminhar lumi_token e usar checkoutSession nas rotas "
            "checkout-link, status e cielo3ds-token. Não substitua arquivos completos do site por versões "
            "antigas. A revisão dessas mudanças acontece no repositório do site e somente no HML.\n", encoding="utf-8")
    docs = destination / "docs"
    docs.mkdir(exist_ok=True)
    for name in ("arquitetura-e-colaboracao.md", "contrato-de-integracoes.md", "desenvolvimento-e-passagem.md"):
        shutil.copy2(ROOT / "docs" / name, docs / name)
    # Essa dependência não é exportada como serviço independente.
    (docs / "gestao-brevia.md").write_text(
        "O serviço de projetos da Brevia ainda depende dos modelos e permissões do núcleo. "
        "Não está incluído neste repositório. Para desenvolver algo nessa área, a equipe define "
        "um contrato de dados e uma API de teste ou trabalha no projeto completo; a separação física exige revisão específica. "
        "Não copiar modelos internos ou o banco da Lumi para contornar essa dependência.\n", encoding="utf-8")
    manifest = {}
    for source in destination.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(destination).as_posix()
        if source.suffix == ".py":
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig"))):
                modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else [item.name for item in node.names] if isinstance(node, ast.Import) else []
                if any(module == "app" or module.startswith("app.") for module in modules):
                    raise ValueError(f"Integração depende do núcleo: {relative}")
        manifest[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
    (destination / "manifest.json").write_text(json.dumps({"source": "Lumi integration export", "files": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--estancia-site")
    args = parser.parse_args()
    files = export(args.output, args.estancia_site)
    print(f"Projeto independente preparado: {len(files)} arquivos; núcleo e credenciais não incluídos.")
