import json
import os
import re
import time
import unicodedata
import urllib.request
from sqlalchemy import select
from .db import Session
from .models import Feature, FeatureCall


def asks_for_human(text):
    text = "".join(
        c
        for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )
    if re.search(r"\b(nao quero|nao preciso|sem)\b", text):
        return False
    return bool(
        re.search(
            r"\b(quero|preciso|posso|gostaria|chame|chama|falar|conversar|atendimento)\b.*\b(humano|humana|atendente|pessoa)\b",
            text,
        )
    )


def request_handover(tenant_id, conversation_id, role, reason):
    with Session() as db:
        feature = db.scalar(
            select(Feature).where(
                Feature.tenant_id == tenant_id,
                Feature.name == "handover",
                Feature.enabled == True,
            )
        )
        if not feature or role not in feature.roles.split(","):
            raise RuntimeError(
                "Atendimento humano não está disponível para este contato."
            )
        endpoint = feature.endpoint
    parameters = {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "reason": reason,
    }
    started = time.monotonic()
    result = {}
    try:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(parameters).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer "
                + os.getenv("HANDOVER_SECRET", "local-demo-handover"),
            },
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            result = json.load(response)
        if result.get("accepted") is not True:
            raise RuntimeError("O serviço não aceitou o atendimento.")
    except Exception as exc:
        result = {"error": str(exc)}
        raise RuntimeError(
            "O serviço de handover está indisponível. Tente novamente."
        ) from exc
    finally:
        with Session.begin() as db:
            db.add(
                FeatureCall(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    feature="handover",
                    parameters=json.dumps(parameters),
                    result=json.dumps(result),
                    duration_ms=str(round((time.monotonic() - started) * 1000)),
                )
            )
