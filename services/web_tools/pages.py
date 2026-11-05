"""Leitura pública limitada: HTTPS, DNS validado e conexão fixada no IP público."""
import ipaddress
import socket
import time
from urllib.parse import urlsplit, urljoin, urlunsplit
import httpx
from .page_text import PageText


def destination(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").encode("idna").decode("ascii")
    if (parsed.scheme != "https" or parsed.port not in (None, 443) or not host
            or parsed.username or parsed.password or "." not in host
            or host.endswith((".local", ".internal", ".localhost"))):
        raise ValueError("endereco_nao_permitido")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal and (not literal.is_global or literal.is_multicast):
        raise ValueError("endereco_nao_permitido")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in ips):
        raise ValueError("endereco_nao_permitido")
    ip = next((ip for ip in ips if ipaddress.ip_address(ip).version == 4), ips[0])
    authority = "[" + ip + "]" if ":" in ip else ip
    return host, urlunsplit(("https", authority, parsed.path or "/", parsed.query, ""))


def read_page(url):
    deadline = time.monotonic() + 8
    with httpx.Client(timeout=httpx.Timeout(5, connect=3), follow_redirects=False, trust_env=False) as client:
        for attempt in range(4):
            if time.monotonic() >= deadline:
                raise ValueError("leitura_expirada")
            host, address = destination(url)
            with client.stream("GET", address, headers={"Host":host, "User-Agent":"Lumi/0.1 (public page reader)", "Connection":"close"},
                               extensions={"sni_hostname":host}) as response:
                if response.is_redirect:
                    if attempt == 3 or not response.headers.get("location"):
                        raise ValueError("redirecionamento_invalido")
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                mime = response.headers.get("content-type", "").split(";")[0].lower()
                if mime not in ("text/html", "application/xhtml+xml", "text/plain"):
                    raise ValueError("tipo_de_pagina_nao_suportado")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 1_000_000 or time.monotonic() >= deadline:
                        raise ValueError("limite_da_leitura")
                text = bytes(raw).decode(response.encoding or "utf-8", errors="replace")
                if any(marker in text for marker in ("anomaly-modal", "cf-chl-", "challenge-platform")):
                    raise ValueError("pagina_protegida")
                if mime == "text/plain":
                    return {"url":url, "text":text[:6000], "truncated":len(text)>6000, "metadata":{}, "structured_data":[]}
                parser = PageText()
                parser.feed(text)
                return {"url":url, **parser.result()}
