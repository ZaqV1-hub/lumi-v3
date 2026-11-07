"""O benchmark manual nunca herda provider/chave do tenant ativo."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app import providers


class BenchmarkProviderTest(unittest.TestCase):
    def test_benchmark_explicitly_selects_each_codex_model_without_active_tenant_configuration(self):
        source = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-provider.py"
        spec = importlib.util.spec_from_file_location("benchmark_provider_test", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        models = []

        def codex(command, **kwargs):
            models.append(command[command.index("--model") + 1])
            self.assertEqual(command[:2], ["codex", "exec"])
            events = [
                {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({
                    "reply": "Resposta fictícia.", "action": "none"})}},
                {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 3}},
            ]
            return subprocess.CompletedProcess(command, 0, "\n".join(map(json.dumps, events)), "")

        with tempfile.TemporaryDirectory(prefix="lumi-benchmark-test-") as folder, \
                patch.object(module, "default_dir", Path(folder)), \
                patch.object(module, "fixtures", return_value=[("case", "prompt", {"tenant_id": "fixture-tenant"})]), \
                patch.object(providers, "configuration", side_effect=AssertionError("Active tenant lookup")), \
                patch.object(providers.subprocess, "run", side_effect=codex), \
                patch("app.openai_provider.reply", side_effect=AssertionError("Paid API")) as api, \
                patch.dict(os.environ, {"LUMI_PROVIDER": "openai", "LUMI_CODEX_MODEL": "wrong-model"}), \
                patch("sys.argv", [str(source), "--models", "test-model-a", "test-model-b"]), \
                contextlib.redirect_stdout(io.StringIO()):
            module.main_benchmark()
            output = json.loads((Path(folder) / "model-comparison-qa.json").read_text())
            self.assertEqual([row["model"] for row in output], ["test-model-a", "test-model-b"])
            api.assert_not_called()
        self.assertEqual(models, ["test-model-a", "test-model-b"])
