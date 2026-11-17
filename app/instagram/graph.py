"""Mensagens iniciadas pelo cliente; endereço da API definido pelo operador."""
import ipaddress
import re
import socket
from urllib.parse import urlsplit, urljoin
import httpx
from .config import value


def send(profile_id, token_env, recipient, text, image_url=None, *, media_kind="image"):
    version=value("INSTAGRAM_GRAPH_VERSION") or "v25.0"
    if not re.fullmatch(r"v\d+\.\d+",version) or not profile_id.isdigit() or not recipient.isdigit():
        raise RuntimeError("Canal Instagram inválido")
    token=value(token_env)
    if not token:raise RuntimeError("Configure o token do Instagram")
    host=value(token_env+"_GRAPH_HOST") or "graph.instagram.com"
    if host not in ("graph.instagram.com", "graph.facebook.com"):
        raise RuntimeError("Endereço da API Instagram inválido")
    messages=[{"text":text[i:i+1000]} for i in range(0,len(text),1000)]
    if image_url:messages.append({"attachment":{"type":media_kind,"payload":{"url":image_url}}})
    last=""
    with httpx.Client(timeout=25) as client:
        for message in messages:
            result=client.post(f"https://{host}/{version}/{profile_id}/messages",
                headers={"Authorization":"Bearer "+token},json={"recipient":{"id":recipient},"message":message})
            if result.is_error:
                code=result.json().get("error",{}).get("code")
                raise RuntimeError(f"Meta recusou a mensagem Instagram (código {code}). Confira a entrega antes de reenviar.")
            last=str(result.json().get("message_id", ""))
            if not last:raise RuntimeError("A Meta não confirmou a mensagem Instagram")
    return last


def media_url(url):
    parsed=urlsplit(url)
    host=(parsed.hostname or "").lower()
    if parsed.scheme!="https" or parsed.port not in (None,443) or parsed.username or not any(
        host==domain or host.endswith("."+domain) for domain in ("fbcdn.net","cdninstagram.com","fbsbx.com")):
        raise ValueError("Origem de mídia não permitida")
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Origem de mídia não permitida")
    return url


def download_media(url, kind=None):
    # A Meta pode entregar voz M4A como video/mp4 ou application/octet-stream.
    # O tipo do evento orienta a leitura, mas o conteúdo real continua validado.
    with httpx.Client(timeout=20,follow_redirects=False) as client:
        for attempt in range(4):
            media_url(url)
            with client.stream("GET",url) as response:
                if response.is_redirect:
                    if attempt == 3 or not response.headers.get("location"):
                        raise ValueError("Redirecionamento de mídia inválido")
                    url=urljoin(url,response.headers["location"])
                    continue
                response.raise_for_status()
                raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>12*1024*1024:raise ValueError("Mídia muito grande")
                mime=response.headers.get("content-type","").split(";")[0].lower()
                binary=bytes(raw)
                if kind == "audio":
                    from ..audio import audio_format
                    format=audio_format(binary)
                    mime={"wav":"audio/wav","ogg":"audio/ogg","matroska":"audio/webm","mov":"audio/mp4","mp3":"audio/mpeg"}[format]
                return binary,mime
