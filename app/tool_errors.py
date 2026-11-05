"""Erros de validação públicos, sem repassar respostas técnicas do serviço."""
import json
import re


def validation_error(response):
    try:
        data = json.loads(response.read(8193))
        fields = data.get("invalid_fields")
        if data.get("error") != "dados_invalidos" or not isinstance(fields, list) or not 1 <= len(fields) <= 20:
            return None
        clean = []
        for item in fields:
            field = item.get("field", "")
            reason = item.get("reason")
            if not isinstance(field, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", field):
                return None
            if reason not in ("invalid", "required"):
                return None
            clean.append({"field": field, "reason": reason})
        return {"data": {"ok": False, "error": "dados_invalidos", "invalid_fields": clean}}
    except (ValueError, AttributeError, TypeError):
        return None
