"""Aviso público liberado somente depois da aprovação do responsável."""
import os
from pathlib import Path
from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent


def config_path():
    return Path(os.getenv("LUMI_DATA_DIR", Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi")) / "privacy.env"


@router.get("/privacy")
def public_notice():
    if dotenv_values(config_path()).get("LUMI_PRIVACY_PUBLISHED") != "true":
        raise HTTPException(404)
    return FileResponse(ROOT / "docs" / "privacy-policy.html", headers={"Cache-Control":"no-cache"})
