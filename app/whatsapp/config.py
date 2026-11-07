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


def app_secret(token_env=None):
    values = dotenv_values(config_path())
    if token_env:
        name = token_env + "_APP_SECRET"
        # Um valor específico vazio desabilita o canal, sem herdar outro app.
        if name in values:
            return (values[name] or "").strip()
        if name in os.environ:
            return os.environ[name].strip()
    return (values.get("WHATSAPP_APP_SECRET", os.getenv("WHATSAPP_APP_SECRET", "")) or "").strip()


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Configure {name} no ambiente local.")
    return value
