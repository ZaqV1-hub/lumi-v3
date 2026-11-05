"""Medição sem armazenar prompt, áudio, imagem ou saída bruta do provider."""
from contextvars import ContextVar
from contextlib import contextmanager
from .db import Session
from .usage_models import ModelCall

scope = ContextVar("lumi_usage_scope", default=None)
PRICES = {"gpt-6.1-sol": (2.0, 0.10, 10.0), "gpt-6.1-terra": (1.0, 0.05, 5.0),
          "gpt-6-luna": (0.10, 0.01, 0.50)}
PRICE_REFERENCE = "OpenAI API Standard short context, USD/1M tokens, 2026-10-30; https://developers.openai.com/api/docs/pricing"


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


def api_cost(row):
    # O equivalente de planejamento permanece registrado, mas não é uma cobrança do CLI.
    return 0.0 if row.provider in {"codex","faster-whisper-local"} else row.estimated_usd


def record(provider, model, status, duration_ms, usage=None, audio_seconds=None):
    current = scope.get()
    if not current: return
    usage = usage or {}
    def number(key):
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    price = 0.0 if provider == "faster-whisper-local" else estimate(model, usage)
    reference = "Transcrição local: sem tarifa de API; infraestrutura não incluída." if provider == "faster-whisper-local" else PRICE_REFERENCE
    with Session.begin() as db:
        db.add(ModelCall(tenant_id=current[0], conversation_id=current[1], message_id=current[2],
            provider=provider, model=model, status=status, input_tokens=number("input_tokens"),
            cached_tokens=number("cached_input_tokens"), output_tokens=number("output_tokens"),
            reasoning_tokens=number("reasoning_output_tokens"), duration_ms=duration_ms,
            audio_seconds=audio_seconds, estimated_usd=price, price_reference=reference))
