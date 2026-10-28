import re
import httpx
from .config import required


def send(phone_id, token_env, recipient, text, image_data=None):
    version = required("WHATSAPP_GRAPH_VERSION")
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise RuntimeError("Versão Graph API inválida.")
    token = required(token_env)
    url = f"https://graph.facebook.com/{version}/{phone_id}"
    headers = {"Authorization": "Bearer " + token}
    with httpx.Client(timeout=25, headers=headers) as client:
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": text[:4096]},
        }
        if image_data:
            media = client.post(
                url + "/media",
                data={"messaging_product": "whatsapp"},
                files={"file": ("image.jpg", image_data, "image/jpeg")},
            )
            media_id = check(media)["id"]
            if len(text) > 1024:
                check(client.post(url + "/messages", json=payload))
            payload.update(
                type="image",
                image={
                    "id": media_id,
                    "caption": text[:1024] if len(text) <= 1024 else "",
                },
            )
            payload.pop("text")
        result = check(client.post(url + "/messages", json=payload))
        return result["messages"][0]["id"]


def check(response):
    if response.is_error:
        try:
            code = response.json().get("error", {}).get("code", "unknown")
        except ValueError:
            code = "unknown"
        raise RuntimeError(
            f"Meta recusou o envio: HTTP {response.status_code}, código {code}."
        )
    return response.json()
