import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("export_integrations", Path(__file__).resolve().parent.parent / "scripts/export-integrations.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class IntegrationExportTest(unittest.TestCase):
    def test_delivery_excludes_core_private_config_and_coupled_management(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = exporter.export(folder)
            self.assertIn("services/rincao/api.py", manifest)
            self.assertIn("services/web_tools/api.py", manifest)
            self.assertIn(".env.example", manifest)
            self.assertFalse(any(name.startswith(("app/", "web/", "services/brevia/", ".git/")) for name in manifest))
            self.assertFalse(any(name.endswith((".env", ".db", ".log")) for name in manifest))
            self.assertEqual(json.loads((Path(folder) / "manifest.json").read_text())["files"], manifest)

    def test_delivery_never_overwrites_a_developers_existing_work(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel = Path(folder) / "existing.txt"
            sentinel.write_text("developer's changes")
            with self.assertRaises(ValueError):
                exporter.export(folder)
            self.assertEqual(sentinel.read_text(), "developer's changes")
