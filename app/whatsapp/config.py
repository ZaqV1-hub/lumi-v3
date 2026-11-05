import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values


def config_path():
    return Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "whatsapp.env"


def load_config():
    load_dotenv(config_path(), override=False)


def access_token(name):
    # Renovações do admin passam a valer sem reiniciar o receptor.
    value = (dotenv_values(config_path()).get(name) or os.getenv(name, "")).strip()
    if not value:
        raise RuntimeError("Configure o token do canal no admin local.")
    return value


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Configure {name} no ambiente local.")
    return value
