import os
from pathlib import Path
from dotenv import load_dotenv


def load_config():
    path = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "whatsapp.env"
    load_dotenv(path, override=False)


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Configure {name} no ambiente local.")
    return value
