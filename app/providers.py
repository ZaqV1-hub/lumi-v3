import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from .usage import record
from .tenant_ai import configuration
DEFAULT_MODEL = "gpt-6.1-terra"


# Perfil de atendimento: os contratos de negócio continuam no prompt/schema da Lumi.
CODEX_CONFIG = {
    "model_instructions_file": Path(__file__).with_name("provider-instructions.txt").as_posix(),
    "skills.max_context_tokens": 1,
    "features.shell_tool": False,
    "features.apps": False,
    "features.multi_agent": False,
    "features.browser_use": False,
    "features.computer_use": False,
    "features.view_image": False,
    "web_search": "disabled",
}


def reply(prompt: str, tools=None, images=None, *, tenant_id=None):
    config = configuration(tenant_id)
    provider, model = config.provider, config.model
    if provider == "demo":
        return "Estou no modo de demonstração. Configure o provider Codex ou OpenAI para receber uma resposta gerada por IA."
    if provider not in {"codex", "codex_gateway", "openai"}:
        raise RuntimeError("O provider do tenant deve ser codex, codex_gateway, openai ou demo.")
    schema = {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "action": {"type": "string", "enum": ["none", "handover", "send_image", "call_tool"]},
            "tool_call": {"anyOf": [{"type": "null"}] + [
                {"type": "object", "properties": {
                    "name": {"type": "string", "enum": [tool["name"]]},
                    "arguments": tool["parameters"]},
                 "required": ["name", "arguments"], "additionalProperties": False}
                for tool in (tools or [])]},
            "image_id": {"type": ["string", "null"]},
            "asked_objective_id": {"type": ["string", "null"]},
            "profile_updates": {"type": "array", "items": {
                "type": "object", "properties": {
                    "objective_id": {"type": "string"}, "value": {"type": "string"},
                    "evidence": {"type": "string"}},
                "required": ["objective_id", "value", "evidence"], "additionalProperties": False}},
        },
        "required": ["reply", "action", "image_id", "profile_updates", "asked_objective_id", "tool_call"],
        "additionalProperties": False,
    }
    if provider == "openai":
        from .openai_provider import reply as openai_reply
        return openai_reply(prompt, schema, images, model=model, api_key=config.api_key)
    if provider == "codex_gateway":
        from .codex_gateway_provider import reply as gateway_reply
        return gateway_reply(prompt, schema, images, model=model)
    with tempfile.TemporaryDirectory(prefix="lumi-codex-") as folder:
        path = Path(folder) / "reply.schema.json"
        path.write_text(json.dumps(schema), encoding="utf-8")
        command = [
                "codex",
                "exec",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--json",
                "--model", model,
                "-c",
                'model_reasoning_effort="low"',
                "-C",
                folder,
            ]
        for key, value in CODEX_CONFIG.items():
            command += ["-c", f"{key}={json.dumps(value)}"]
        for index, binary in enumerate(images or []):
            image_path = Path(folder) / f"image-{index}.jpg"
            image_path.write_bytes(binary)
            command += ["--image", str(image_path)]
        command += ["--output-schema", str(path), "-"]
        started = time.monotonic()
        status, usage = "failed", None
        try:
            result = subprocess.run(command,
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
            final = None
            for line in result.stdout.splitlines():
                try: event = json.loads(line)
                except ValueError: continue
                if event.get("type") == "turn.completed": usage = event.get("usage")
                if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message":
                    final = event["item"].get("text")
            if result.returncode or final is None:
                raise RuntimeError("O Codex local não respondeu. Confira se ele está instalado e autenticado.")
            answer = json.loads(final)
            parsed = {"reply": answer["reply"].strip(), "action": answer["action"], "image_id": answer.get('image_id'), "profile_updates": answer.get('profile_updates', []), "asked_objective_id": answer.get('asked_objective_id'), "tool_call": answer.get('tool_call')}
            status = "completed"
            return parsed
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError(
                "O Codex devolveu uma resposta fora do formato esperado."
            ) from exc
        finally:
            record("codex", model, status, round((time.monotonic()-started)*1000), usage=usage)
