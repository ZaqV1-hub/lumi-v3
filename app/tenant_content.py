"""Importa conteúdo revisado para o banco, sem criar logins ou ligar canais."""
import argparse
import re
from pathlib import Path
from sqlalchemy import select
from .db import Session
from .models import Tenant, KnowledgeItem


def parse_content(text):
    text = re.split(r"(?mi)^## PENDÊNCIAS\b", text, maxsplit=1)[0]
    identity = re.search(r"(?ms)^## 1\. IDENTIDADE\s*\n(.*?)^## 2\. INSTRUÇÕES LIVRES\s*\n", text)
    instructions = re.search(r"(?ms)^## 2\. INSTRUÇÕES LIVRES\s*\n(.*?)^## 3\. BASE DE CONHECIMENTO\s*\n", text)
    items = re.findall(r"(?ms)^### Título:\s*([^\n]+)\n(.*?)(?=^### Título:|\Z)", text)
    clean = lambda value: re.sub(r"\n---\s*$", "", value.strip()).strip()
    if not identity or not instructions or not items:
        raise ValueError("Informe identidade, instruções livres e itens com Título + Conteúdo")
    knowledge = [(title.strip(), clean(content)) for title, content in items]
    if len({title for title, _ in knowledge}) != len(knowledge) or any(not content for _, content in knowledge):
        raise ValueError("Títulos devem ser únicos e os conteúdos não podem estar vazios")
    return clean(identity[1]), clean(instructions[1]), knowledge


def import_content(db, slug, text):
    identity, instructions, knowledge = parse_content(text)
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if not tenant:
        raise ValueError("Cadastre a empresa antes de importar conteúdo")
    tenant.identity, tenant.personality = identity, instructions
    for title, content in knowledge:
        item = db.scalar(select(KnowledgeItem).where(KnowledgeItem.tenant_id == tenant.id, KnowledgeItem.title == title))
        if not item:
            item = KnowledgeItem(tenant_id=tenant.id, title=title)
            db.add(item)
        item.content, item.enabled = content, True
    return len(knowledge)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    with Session.begin() as db:
        count = import_content(db, args.tenant, Path(args.file).read_text(encoding="utf-8-sig"))
    print(f"Conteúdo salvo no banco: {count} itens. Canais e acessos preservados.")
