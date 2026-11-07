"""Responses API: apenas texto/imagens e saída estruturada; ferramentas executam no núcleo."""
import base64
import copy
import json
import time

import httpx
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .usage import record


def strict_schema(schema):
    """O wire exige todas as propriedades; null representa opcionais omitidos."""
    result = copy.deepcopy(schema)
    for keyword in ("anyOf", "oneOf", "allOf"):
        if keyword in result:
            result[keyword] = [strict_schema(item) for item in result[keyword]]
    if isinstance(result.get("items"), dict):
        result["items"] = strict_schema(result["items"])
    if "$defs" in result:
        result["$defs"] = {name: strict_schema(item) for name, item in result["$defs"].items()}
    if result.get("type") == "object" or "properties" in result:
        required = result.get("required", [])
        properties = {}
        for name, item in result.get("properties", {}).items():
            value = strict_schema(item)
            if name not in required and not Draft202012Validator(item).is_valid(None):
                value = {"anyOf": [value, {"type": "null"}]}
            properties[name] = value
        result.update(properties=properties, required=list(properties), additionalProperties=False)
    return result


def restore_optional(value, schema):
    """Não encaminha null adicionado pelo wire a contratos que exigem omissão."""
    for option in schema.get("anyOf", []):
        if Draft202012Validator(strict_schema(option)).is_valid(value):
            return restore_optional(value, option)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        return {name: restore_optional(item, properties.get(name, {}))
                for name, item in value.items()
                if not (name in properties and name not in schema.get("required", [])
                        and item is None and not Draft202012Validator(properties[name]).is_valid(None))}
    if isinstance(value, list) and "items" in schema:
        return [restore_optional(item, schema["items"]) for item in value]
    return value


def reply(prompt, schema, images=None, *, model, api_key):
    key = api_key
    if not model or not key:
        raise RuntimeError("Configure o modelo e a chave OpenAI deste tenant.")
    content = [{"type": "input_text", "text": prompt}]
    content.extend({"type": "input_image", "image_url": "data:image/jpeg;base64," +
                    base64.b64encode(binary).decode("ascii")} for binary in (images or []))
    wire_schema = strict_schema(schema)
    payload = {"model": model, "service_tier": "default", "store": False, "input": [{"role": "user", "content": content}],
               "text": {"format": {"type": "json_schema", "name": "lumi_reply",
                                    "strict": True, "schema": wire_schema}}}
    # Mantém o perfil low dos modelos de atendimento já usados pela Lumi.
    if model in {"gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-terra"}:
        payload["reasoning"] = {"effort": "low"}
    started, status, usage = time.monotonic(), "failed", None
    try:
        with httpx.Client(timeout=120, follow_redirects=False, trust_env=False) as client:
            result = client.post("https://api.openai.com/v1/responses", json=payload,
                                 headers={"Authorization": "Bearer " + key})
        if result.status_code != 200:
            raise RuntimeError(f"OpenAI recusou a requisição (HTTP {result.status_code}). Confira acesso, modelo e limite da API.")
        data = result.json()
        raw_usage = data.get("usage")
        if isinstance(raw_usage, dict):
            details = raw_usage.get("input_tokens_details") or {}
            writes = details.get("cache_write_tokens_details") or {}
            # A API pode omitir os TTLs quando informa explicitamente zero escritas.
            no_writes = 0 if type(details.get("cache_write_tokens")) is int and details["cache_write_tokens"] == 0 else None
            usage = {"input_tokens": raw_usage.get("input_tokens"),
                     "cached_input_tokens": (raw_usage.get("input_tokens_details") or {}).get("cached_tokens"),
                     "output_tokens": raw_usage.get("output_tokens"),
                     "reasoning_output_tokens": (raw_usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
                     "cache_write_tokens": (raw_usage.get("input_tokens_details") or {}).get("cache_write_tokens"),
                     "cache_write_30m_tokens": writes.get("ttl_30m_tokens", no_writes),
                     "cache_write_12h_tokens": writes.get("ttl_12h_tokens", no_writes),
                     "service_tier": data.get("service_tier")}
        if data.get("status") != "completed":
            raise RuntimeError("OpenAI não concluiu a resposta. Tente novamente após verificar o serviço.")
        parts = [part for item in data["output"] if item.get("type") == "message"
                 for part in item["content"]]
        if any(part.get("type") == "refusal" for part in parts):
            raise RuntimeError("OpenAI recusou a geração desta resposta.")
        texts = [part["text"] for part in parts if part.get("type") == "output_text"]
        if len(texts) != 1:
            raise ValueError("output_text")
        answer = json.loads(texts[0])
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
        raise RuntimeError("Não foi possível obter resposta da OpenAI. Confira a conexão e tente novamente.") from None
    except (ValueError, KeyError, TypeError, AttributeError, ValidationError):
        raise RuntimeError("OpenAI devolveu uma resposta fora do formato esperado.") from None
    finally:
        record("openai", model, status, round((time.monotonic() - started) * 1000), usage=usage)
