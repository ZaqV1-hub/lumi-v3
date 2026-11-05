import unittest
from app.tenant_content import parse_content


class TenantContentTest(unittest.TestCase):
    def test_separates_blocks_and_excludes_pending_notes(self):
        text = "## 1. IDENTIDADE\nAssistente\n---\n## 2. INSTRUÇÕES LIVRES\nAcolha\n---\n## 3. BASE DE CONHECIMENTO\n### Título: Empresa\nConteúdo\n### Título: Contato\nTelefone\n---\n## PENDÊNCIAS (não entram)\nNotas privadas"
        identity, instructions, items = parse_content(text)
        self.assertEqual(identity, "Assistente")
        self.assertEqual(instructions, "Acolha")
        self.assertEqual(items, [("Empresa", "Conteúdo"), ("Contato", "Telefone")])
        self.assertNotIn("Notas privadas", str(items))

    def test_duplicate_titles_and_incomplete_files_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_content("Texto sem blocos")
        with self.assertRaises(ValueError):
            parse_content("## 1. IDENTIDADE\nA\n## 2. INSTRUÇÕES LIVRES\nB\n## 3. BASE DE CONHECIMENTO\n### Título: A\nX\n### Título: A\nY")
