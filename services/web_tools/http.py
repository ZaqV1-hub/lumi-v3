import httpx


def get(url, params=None, headers=None):
    # Os destinos são definidos pelos adaptadores; nunca são URLs escolhidas pelo modelo.
    with httpx.Client(timeout=httpx.Timeout(12, connect=5), follow_redirects=False,
                      headers={"User-Agent": "Lumi/0.1 (local search test)", **(headers or {})}) as client:
        with client.stream("GET", url, params=params) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("fonte_indisponivel")
            raw = bytearray()
            for part in response.iter_bytes():
                raw.extend(part)
                if len(raw) > 1_000_000:
                    raise ValueError("resposta_grande_demais")
            return bytes(raw).decode("utf-8", errors="replace")
