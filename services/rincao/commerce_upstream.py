"""Executa os contratos existentes na VM por SSH verificado, sem abrir portas."""
import base64
import json
import os
import subprocess
from pathlib import Path
from .config import required


def request(operation, payload):
    if operation not in ("quote", "pending", "approved"):
        raise ValueError("Operação inválida")
    packet = {"operation": operation, "payload": payload,
              "root": required("RINCAO_COMMERCE_REMOTE_ROOT"),
              "dependencies": required("RINCAO_COMMERCE_REMOTE_DEPENDENCIES"),
              "build": required("RINCAO_COMMERCE_REMOTE_BUILD")}
    raw = base64.b64encode(json.dumps(packet).encode()).decode()
    source = Path(__file__).with_name("commerce_rpc.cjs").read_text(encoding="utf-8")
    source = "const packet=JSON.parse(Buffer.from('" + raw + "','base64').toString());\n" + source
    encoded = base64.b64encode(source.encode()).decode()
    script = f"""[Console]::OutputEncoding=[Text.Encoding]::UTF8
$code=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'))
node -e $code
exit $LASTEXITCODE"""
    transport = os.getenv("RINCAO_COMMERCE_TRANSPORT", "ssh")
    if transport == "local":
        command = [os.getenv("RINCAO_COMMERCE_NODE", "node"), "-e", source]
    elif transport == "ssh":
        command = ["ssh", "-T", "-i", required("RINCAO_SSH_KEY_PATH"), "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
            required("RINCAO_SSH_HOST"), "powershell", "-NoProfile", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16le")).decode()]
    else:
        raise RuntimeError("commerce_transport_invalid")
    result = subprocess.run(command, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("commerce_remote_unavailable")
    data = json.loads(result.stdout.decode("utf-8-sig").strip())
    if data.get("rpc_error"):
        diagnostic = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "commerce-rpc-error.json"
        diagnostic.write_text(json.dumps(data), encoding="utf-8")
        raise RuntimeError(data["rpc_error"])
    return data
