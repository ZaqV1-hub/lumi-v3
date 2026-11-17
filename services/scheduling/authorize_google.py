"""Autorização OAuth local, feita pelo operador; não cria eventos nem imprime tokens."""
import argparse
import os
from pathlib import Path
from .google import SCOPES


def main():
    from google_auth_oauthlib.flow import InstalledAppFlow
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--token", type=Path, required=True)
    args = parser.parse_args()
    destination = args.token.resolve()
    if destination.exists():
        raise SystemExit("Arquivo já existe. Preserve a autorização anterior antes de reconectar.")
    # Refuse placing either credential in this source tree.
    root = Path(__file__).resolve().parents[2]
    if destination.is_relative_to(root) or args.client.resolve().is_relative_to(root):
        raise SystemExit("Credenciais devem ficar fora da pasta do projeto.")
    flow = InstalledAppFlow.from_client_secrets_file(str(args.client), SCOPES, autogenerate_code_verifier=True)
    credentials = flow.run_local_server(host="127.0.0.1", port=0, open_browser=False, timeout_seconds=180,
        authorization_prompt_message="Abra este endereço para autorizar a conta Google:\n{url}",
        success_message="Autorização concluída. Pode fechar esta aba.", access_type="offline", prompt="consent")
    if not credentials.refresh_token:
        raise SystemExit("O Google não concedeu autorização offline.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        target.write(credentials.to_json())
    print("Autorização guardada no arquivo privado. Nenhum evento foi criado.")


if __name__ == "__main__":
    main()
