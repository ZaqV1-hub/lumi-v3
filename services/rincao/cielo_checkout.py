"""Configuração e URL da página própria integrada à API E-commerce Cielo."""
import os
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv


def settings():
    load_dotenv(Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "cielo.env")


def is_enabled():
    settings()
    base = os.getenv("RINCAO_CHECKOUT_PUBLIC_URL", "")
    return (urlsplit(base).scheme == "https" and bool(os.getenv("INGRESSO_CIELO_MERCHANT_ID"))
            and bool(os.getenv("INGRESSO_CIELO_MERCHANT_KEY")))


def cents(value):
    amount = Decimal(str(value)) * 100
    if not amount.is_finite() or amount != amount.to_integral_value() or amount < 0:
        raise ValueError("valor_invalido")
    return int(amount)


def create_page(reference, packet, token):
    settings()
    if not is_enabled():
        raise ValueError("checkout_nao_configurado")
    base = os.environ["RINCAO_CHECKOUT_PUBLIC_URL"]
    if packet.get("metadata", {}).get("channel") == "simulator":
        simulator = os.getenv("RINCAO_CHECKOUT_SIMULATOR_URL", "")
        parsed = urlsplit(simulator)
        if simulator:
            if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
                raise ValueError("endereco_simulador_invalido")
            base = simulator
    return base.rstrip("/") + "/checkout/" + token
