"""Medição sem armazenar prompt, áudio, imagem ou saída bruta do provider."""
from contextvars import ContextVar
from contextlib import contextmanager
from .db import Session
from .usage_models import ModelCall

scope = ContextVar("lumi_usage_scope", default=None)
PRICES = {"gpt-6.1-sol": (2.0, 0.10, 10.0), "gpt-6.1-terra": (1.0, 0.05, 5.0),
          "gpt-6-luna": (0.10, 0.01, 0.50)}
PRICE_REFERENCE = ("Estimativa OpenAI API Standard (default), USD/1M tokens, tarifa verificada em 2026-11-07; "
                   "https://developers.openai.com/api/docs/pricing; "
                   "https://developers.openai.com/api/docs/guides/prompt-caching#monitor-cache-performance; "
                   "não é fatura reconciliada; sem descontos ou impostos")


@contextmanager
def usage_scope(tenant_id, conversation_id, message_id):
    token = scope.set((tenant_id, conversation_id, message_id))
    try: yield
    finally: scope.reset(token)


def estimate(model, usage):
    rates = PRICES.get(model)
    if not rates or not usage or usage.get("input_tokens") is None or usage.get("output_tokens") is None:
        return None
    incoming = max(0, usage["input_tokens"])
    cached = min(incoming, max(0, usage.get("cached_input_tokens", 0)))
    return ((incoming-cached)*rates[0]+cached*rates[1]+max(0,usage["output_tokens"])*rates[2])/1_000_000


def estimate_openai(model, usage):
    rates = PRICES.get(model)
    if not rates or not isinstance(usage, dict) or usage.get("service_tier") != "default":
        return None
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "cache_write_tokens",
            "cache_write_30m_tokens", "cache_write_12h_tokens")
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in keys):
        return None
    incoming, cached, outgoing, written, short_write, long_write = (usage[key] for key in keys)
    if written != short_write + long_write or cached + written > incoming:
        return None
    long_context = incoming > 272000
    input_rate, cached_rate, output_rate = rates
    if long_context:
        input_rate *= 2
        cached_rate *= 2
        output_rate *= 1.5
    # Escritas substituem entrada comum; reasoning já integra output_tokens.
    return ((incoming-cached-written)*input_rate + cached*cached_rate +
            short_write*input_rate*1.25 + long_write*input_rate*2.5 + outgoing*output_rate) / 1_000_000


def api_cost(row):
    # O equivalente de planejamento permanece registrado, mas não é uma cobrança do CLI.
    return 0.0 if row.provider in {"codex","codex_gateway","faster-whisper-local"} else row.estimated_usd


def record(provider, model, status, duration_ms, usage=None, audio_seconds=None):
    current = scope.get()
    if not current: return
    usage = usage or {}
    def number(key):
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    price = 0.0 if provider == "faster-whisper-local" else estimate_openai(model, usage) if provider == "openai" else estimate(model, usage)
    reference = "Transcrição local: sem tarifa de API; infraestrutura não incluída." if provider == "faster-whisper-local" else PRICE_REFERENCE
    if provider == "openai":
        if price is None:
            reference = "OpenAI API: custo desconhecido; modelo, tier ou metadados de consumo sem tarifa completa validada."
        else:
            reference += (f"; service_tier=default; context={'long' if usage['input_tokens'] > 272000 else 'short'}"
                          f"; cache_write_tokens={usage['cache_write_tokens']}"
                          f"; cache_write_30m_tokens={usage['cache_write_30m_tokens']}"
                          f"; cache_write_12h_tokens={usage['cache_write_12h_tokens']}")
    with Session.begin() as db:
        db.add(ModelCall(tenant_id=current[0], conversation_id=current[1], message_id=current[2],
            provider=provider, model=model, status=status, input_tokens=number("input_tokens"),
            cached_tokens=number("cached_input_tokens"), output_tokens=number("output_tokens"),
            reasoning_tokens=number("reasoning_output_tokens"), duration_ms=duration_ms,
            audio_seconds=audio_seconds, estimated_usd=price, price_reference=reference))
