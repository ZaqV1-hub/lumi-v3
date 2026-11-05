import os
from pathlib import Path
from dotenv import dotenv_values


def config_path():
    return Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "instagram.env"


def value(name):
    return (dotenv_values(config_path()).get(name) or os.getenv(name, "")).strip()
