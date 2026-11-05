import os
from pathlib import Path
from dotenv import load_dotenv


def load_config():
    # A configuração do checkout tem prioridade sobre cópias antigas no arquivo de consultas.
    load_dotenv(Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "cielo.env", override=False)
    path = Path(os.getenv("RINCAO_TOOLS_ENV", str(Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "rincao-tools.env")))
    load_dotenv(path, override=False)


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError("Serviço sem configuração")
    return value
