import re
import httpx
from urllib.parse import urlsplit
from .config import required, access_token


def download_media(media_id, token_env):
    if not re.fullmatch(r"\d{5,80}", media_id):
        raise RuntimeError("Mídia inválida")
    version=required("WHATSAPP_GRAPH_VERSION")
    if not re.fullmatch(r"v\d+\.\d+",version):raise RuntimeError("Versão da Meta inválida")
    with httpx.Client(timeout=20,follow_redirects=False,headers={"Authorization":"Bearer "+access_token(token_env)}) as client:
        metadata=check(client.get(f"https://graph.facebook.com/{version}/{media_id}"))
        url=metadata.get("url","");parsed=urlsplit(url);host=parsed.hostname or ""
        if parsed.scheme!='https' or parsed.username or parsed.password or not (host=='lookaside.fbsbx.com' or host.endswith('.fbcdn.net')):
            raise RuntimeError("Origem de mídia não permitida")
        with client.stream('GET',url) as response:
            if response.status_code!=200:raise RuntimeError("Mídia indisponível")
            data=bytearray()
            for part in response.iter_bytes():
                data.extend(part)
                if len(data)>12*1024*1024:raise RuntimeError("Mídia grande demais")
        return bytes(data),metadata.get('mime_type','')


def send(phone_id, token_env, recipient, text, image_data=None, *, document=None):
    version = required("WHATSAPP_GRAPH_VERSION")
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise RuntimeError("Versão Graph API inválida.")
    token = access_token(token_env)
    url = f"https://graph.facebook.com/{version}/{phone_id}"
    headers = {"Authorization": "Bearer " + token}
    with httpx.Client(timeout=25, headers=headers) as client:
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": text[:4096]},
        }
        if image_data or document:
            kind = "document" if document else "image"
            filename, data, mime = (*document, "application/pdf") if document else ("image.jpg", image_data, "image/jpeg")
            media = client.post(
                url + "/media",
                data={"messaging_product": "whatsapp"},
                files={"file": (filename, data, mime)},
            )
            media_id = check(media)["id"]
            if len(text) > 1024:
                check(client.post(url + "/messages", json=payload))
            payload["type"] = kind
            payload[kind] = {"id": media_id, "caption": text if len(text) <= 1024 else ""}
            if document:
                payload[kind]["filename"] = filename
                if not payload[kind]["caption"]:
                    payload[kind].pop("caption")
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
