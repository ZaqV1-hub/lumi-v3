"""Somente leitura da publicação e resposta pública, sem executar tools da Lumi."""
import re
import httpx
from .config import value


def connection(channel):
    host = value(channel.token_env + "_GRAPH_HOST") or "graph.instagram.com"
    version = value("INSTAGRAM_GRAPH_VERSION") or "v26.0"
    if host not in ("graph.facebook.com", "graph.instagram.com") or not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("Configuração Instagram inválida")
    return f"https://{host}/{version}", {"Authorization": "Bearer " + value(channel.token_env)}


def publication(channel, media_id):
    base, headers = connection(channel)
    with httpx.Client(timeout=15) as http:
        result = http.get(base + "/" + media_id, params={"fields": "id,caption,owner"}, headers=headers)
        result.raise_for_status()
        data = result.json()
    if str(data.get("owner", {}).get("id")) != channel.profile_id:
        raise ValueError("Publicação não pertence ao perfil")
    return str(data.get("caption", ""))[:3000]


def respond(channel, comment_id, text):
    base, headers = connection(channel)
    with httpx.Client(timeout=20) as http:
        result = http.post(base + "/" + comment_id + "/replies", data={"message": text}, headers=headers)
        result.raise_for_status()
        reply_id = str(result.json().get("id", ""))
        if not reply_id.isdigit():
            raise ValueError("Resposta não confirmada pela Meta")
        return reply_id
