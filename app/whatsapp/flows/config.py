import json
import os
from pathlib import Path
from uuid import UUID


def channel_config(phone):
    path = os.getenv("LUMI_WHATSAPP_FLOWS_FILE")
    if not path:
        return None
    try:
        row = json.loads(Path(path).read_text(encoding="utf-8")).get(phone)
        if not isinstance(row, dict) or row.get("enabled") is not True:
            return None
        UUID(row["tenant_id"])
        if not phone.isdigit() or not str(row["flow_id"]).isdigit():
            raise ValueError()
        if not Path(row["private_key_path"]).is_absolute():
            raise ValueError()
        return row
    except (OSError, KeyError, TypeError, ValueError):
        raise RuntimeError("Invalid private Flows configuration") from None
