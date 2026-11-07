"""Gateway autenticado para o Codex CLI; nunca alterna para uma API paga."""
import base64
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .openai_provider import restore_optional, strict_schema
from .usage import record


def reply(prompt, schema, images=None, *, model):
    base = os.getenv("LUMI_CODEX_GATEWAY_URL", "").strip().rstrip("/")
    token = os.getenv("LUMI_CODEX_GATEWAY_TOKEN", "").strip()
    try:
        url = urlsplit(base)
        loopback = url.hostname in {"localhost", "127.0.0.1", "::1"}
        valid = (bool(url.hostname) and url.port != 0 and not url.username and not url.password
                 and not url.query and not url.fragment and not url.path
                 and (url.scheme == "https" or (url.scheme == "http" and loopback)))
    except ValueError:
        valid = False
    if not valid or not model or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise RuntimeError("Configure a URL segura, o token e o modelo do gateway Codex.")
    images = images or []
    if len(images) > 2 or any(not isinstance(image, bytes) or len(image) > 5 * 1024 * 1024
                              or not image.startswith(b"\xff\xd8\xff") or not image.endswith(b"\xff\xd9")
                              for image in images):
        raise RuntimeError("O gateway Codex aceita até duas imagens JPEG de até 5 MB cada.")
    request_id = uuid.uuid4().hex
    wire_schema = strict_schema(schema)
    payload = {"request_id": request_id, "model": model,
               "instructions": Path(__file__).with_name("provider-instructions.txt").read_text(encoding="utf-8"),
               "input": prompt, "reasoning": {"effort": "low"},
               "text": {"format": {"type": "json_schema", "name": "lumi_reply",
                                    "strict": True, "schema": wire_schema}}}
    if images:
        payload["images"] = [{"mime_type": "image/jpeg", "data_base64": base64.b64encode(image).decode("ascii")}
                             for image in images]
    started, status, usage = time.monotonic(), "failed", None
    try:
        with httpx.Client(timeout=125, follow_redirects=False, trust_env=False) as client:
            result = client.post(base + "/v1/plan-next/responses", json=payload,
                                 headers={"Authorization": "Bearer " + token, "Idempotency-Key": request_id})
        if result.status_code != 200:
            raise RuntimeError(f"O gateway Codex recusou a requisição (HTTP {result.status_code}). Confira o serviço e a autenticação.")
        data = result.json()
        if data.get("status") != "completed" or data.get("effective_model") != model:
            raise ValueError("incomplete or unexpected model")
        raw_usage = data.get("usage")
        if raw_usage is not None:
            keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
            if not isinstance(raw_usage, dict) or any(type(raw_usage.get(key)) is not int or raw_usage[key] < 0 for key in keys):
                raise ValueError("usage")
            usage = {key: raw_usage[key] for key in keys}
        answer = json.loads(data["output_text"])
        Draft202012Validator(wire_schema, format_checker=FormatChecker()).validate(answer)
        answer = restore_optional(answer, schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(answer)
        answer["reply"] = answer["reply"].strip()
        if ((answer["action"] != "call_tool" and not answer["reply"])
                or (answer["action"] == "call_tool" and answer["tool_call"] is None)):
            raise ValueError("reply/action")
        status = "completed"
        return answer
    except httpx.HTTPError:
        raise RuntimeError("Não foi possível obter resposta do gateway Codex. Confira a conexão e o serviço.") from None
    except (ValueError, KeyError, TypeError, AttributeError, ValidationError):
        raise RuntimeError("O gateway Codex devolveu uma resposta fora do formato esperado.") from None
    finally:
        record("codex_gateway", model, status, round((time.monotonic() - started) * 1000), usage=usage)
