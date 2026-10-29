import json
import os
import subprocess
import tempfile
from pathlib import Path


def reply(prompt: str) -> str:
    if os.getenv("LUMI_PROVIDER", "codex") == "demo":
        return "Estou no modo de demonstração. Configure o provider Codex para receber uma resposta gerada por IA."
    schema = {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "action": {"type": "string", "enum": ["none", "handover", "send_image"]},
            "image_id": {"type": ["string", "null"]},
            "asked_objective_id": {"type": ["string", "null"]},
            "profile_updates": {"type": "array", "items": {
                "type": "object", "properties": {
                    "objective_id": {"type": "string"}, "value": {"type": "string"},
                    "evidence": {"type": "string"}},
                "required": ["objective_id", "value", "evidence"], "additionalProperties": False}},
        },
        "required": ["reply", "action", "image_id", "profile_updates", "asked_objective_id"],
        "additionalProperties": False,
    }
    with tempfile.TemporaryDirectory(prefix="lumi-codex-") as folder:
        path = Path(folder) / "reply.schema.json"
        path.write_text(json.dumps(schema), encoding="utf-8")
        result = subprocess.run(
            [
                "codex",
                "exec",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "-c",
                'model_reasoning_effort="low"',
                "-C",
                folder,
                "--output-schema",
                str(path),
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
            env={
                key: value
                for key, value in os.environ.items()
                if key
                in {
                    "PATH",
                    "Path",
                    "PATHEXT",
                    "SYSTEMROOT",
                    "SystemRoot",
                    "WINDIR",
                    "USERPROFILE",
                    "APPDATA",
                    "LOCALAPPDATA",
                    "CODEX_HOME",
                    "HOME",
                    "TMP",
                    "TEMP",
                    "LANG",
                }
            },
        )
        if result.returncode:
            raise RuntimeError(
                "O Codex local não respondeu. Confira se ele está instalado e autenticado."
            )
        try:
            answer = json.loads(result.stdout)
            return {"reply": answer["reply"].strip(), "action": answer["action"], "image_id": answer.get('image_id'), "profile_updates": answer.get('profile_updates', []), "asked_objective_id": answer.get('asked_objective_id')}
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError(
                "O Codex devolveu uma resposta fora do formato esperado."
            ) from exc
