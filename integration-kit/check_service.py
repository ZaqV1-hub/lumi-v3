"""Simula o núcleo por HTTP. Não usa IA, não grava na Lumi nem habilita tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import httpx
from jsonschema import Draft202012Validator, FormatChecker


def read_contracts(client, base):
    response = client.get(base.rstrip("/") + "/contracts")
    response.raise_for_status()
    contracts = response.json()
    if not isinstance(contracts, list) or not contracts:
        raise ValueError("O serviço precisa publicar uma lista de contratos")
    names = set()
    for item in contracts:
        name = item["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("Nomes devem ser únicos")
        names.add(name)
        if not isinstance(item["description"], str) or not item["description"].strip():
            raise ValueError("Descreva quando usar a funcionalidade")
        if not isinstance(item["roles"], list) or not item["roles"] or any(not isinstance(role, str) or not role for role in item["roles"]):
            raise ValueError("Informe os papéis autorizados")
        if not isinstance(item["path"], str) or not item["path"].startswith("/"):
            raise ValueError("Informe um endpoint relativo")
        source, endpoint = urlsplit(base), urlsplit(urljoin(base, item["path"]))
        if (source.scheme, source.netloc) != (endpoint.scheme, endpoint.netloc):
            raise ValueError("Endpoint fora do serviço revisado")
        Draft202012Validator.check_schema(item["parameters"])
    return contracts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="http://127.0.0.1:8010")
    parser.add_argument("--tool")
    parser.add_argument("--input", help="JSON com tenant_id, conversation_id, role, arguments e context fictícios")
    parser.add_argument("--token-env", default="SERVICE_SECRET")
    args = parser.parse_args()
    with httpx.Client(timeout=45, follow_redirects=False) as client:
        contracts = read_contracts(client, args.service)
        digest = hashlib.sha256(json.dumps(contracts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        print(f"Contratos válidos: {len(contracts)}. SHA-256: {digest}")
        if not args.tool:
            return
        contract = next((item for item in contracts if item["name"] == args.tool), None)
        if not contract or not args.input:
            raise ValueError("Informe uma tool publicada e um arquivo de entrada")
        payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        Draft202012Validator(contract["parameters"], format_checker=FormatChecker()).validate(payload["arguments"])
        if payload["role"] not in contract["roles"]:
            raise ValueError("Papel não autorizado no contrato")
        secret = os.getenv(args.token_env)
        if not secret:
            raise ValueError("Configure a chave de teste na variável indicada")
        response = client.post(urljoin(args.service, contract["path"]), json=payload,
            headers={"Authorization": "Bearer " + secret})
        print("HTTP", response.status_code)
        # O arquivo e o resultado de teste devem conter somente dados fictícios.
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        response.raise_for_status()


if __name__ == "__main__":
    main()
