import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient


class FlowTest(unittest.TestCase):
    def test_isolation_handover_and_intervention(self):
        with tempfile.TemporaryDirectory() as folder:
            os.environ["LUMI_DATA_DIR"] = folder
            from app import main, client
            from app.models import Conversation, FeatureCall

            try:
                with TestClient(main.app) as admin, TestClient(main.app) as other:
                    self.assertEqual(
                        admin.get("/api/admin/conversations").status_code, 401
                    )
                    self.assertEqual(
                        admin.post(
                            "/api/login",
                            json={"email": "isaque@rincao.local", "password": "wrong"},
                        ).status_code,
                        401,
                    )
                    admin.post(
                        "/api/login",
                        json={"email": "isaque@rincao.local", "password": "demo1234"},
                    )
                    other.post(
                        "/api/login",
                        json={"email": "ana@breve.local", "password": "demo1234"},
                    )
                    token = admin.post(
                        "/api/public/rincao/start", json={"name": "Cliente teste"}
                    ).json()["token"]
                    cid = admin.get("/api/admin/conversations").json()[0]["id"]
                    self.assertEqual(
                        other.get("/api/admin/conversations/" + cid).status_code, 404
                    )
                    self.assertEqual(
                        other.post(
                            "/api/admin/conversations/" + cid + "/claim"
                        ).status_code,
                        404,
                    )
                    self.assertEqual(other.get("/api/admin/conversations").json(), [])
                    with patch.object(client, "reply", return_value="Olá!") as provider:
                        self.assertEqual(
                            admin.post(
                                "/api/client/" + token + "/messages",
                                json={"content": "Quais serviços vocês oferecem?"},
                            ).status_code,
                            200,
                        )
                        self.assertNotIn(
                            "assistente da Breve", provider.call_args.args[0]
                        )
                    with patch.object(client, "request_handover") as feature, patch.object(
                        client, "reply", return_value={"reply": "Resposta gerada pelo modelo", "action": "handover"}
                    ):
                        admin.post(
                            "/api/client/" + token + "/messages",
                            json={"content": "Quero falar com um humano"},
                        )
                        feature.assert_called_once()
                    with patch.object(client, "reply") as provider:
                        admin.post(
                            "/api/client/" + token + "/messages",
                            json={"content": "Ainda estou aqui"},
                        )
                        provider.assert_not_called()
                    admin.post("/api/admin/conversations/" + cid + "/claim")
                    admin.post(
                        "/api/admin/conversations/" + cid + "/messages",
                        json={"content": "Como posso ajudar?"},
                    )
                    last = admin.get("/api/client/" + token).json()["messages"][-1]
                    self.assertEqual(last["name"], "Isaque")
                    self.assertEqual(last["sender"], "humano")
                    # Intervenção durante a inferência descarta a resposta da Lumi.
                    token2 = admin.post(
                        "/api/public/rincao/start", json={"name": "Outro cliente"}
                    ).json()["token"]
                    cid2 = admin.get("/api/admin/conversations").json()[0]["id"]

                    def intervene(_):
                        admin.post("/api/admin/conversations/" + cid2 + "/claim")
                        return "Esta resposta deve ser descartada"

                    with patch.object(client, "reply", side_effect=intervene):
                        admin.post(
                            "/api/client/" + token2 + "/messages",
                            json={"content": "Qual o horário?"},
                        )
                    self.assertFalse(
                        any(
                            m["sender"] == "lumi"
                            for m in admin.get("/api/client/" + token2).json()[
                                "messages"
                            ]
                        )
                    )
                    admin.post("/api/admin/conversations/" + cid2 + "/release")
                    released = admin.get("/api/client/" + token2).json()
                    self.assertEqual(released["status"], "lumi")
                    self.assertIn(
                        "saiu da conversa", released["messages"][-1]["content"]
                    )

                    import io, base64
                    from PIL import Image

                    binary = io.BytesIO()
                    Image.new("RGB", (20, 20), "blue").save(binary, format="PNG")
                    image_input = {
                        "name": "Mapa teste",
                        "description": "Mapa de teste",
                        "when_to_use": "Enviar quando pedirem um mapa",
                        "src": "data:image/png;base64,"
                        + base64.b64encode(binary.getvalue()).decode(),
                    }
                    self.assertEqual(
                        admin.post("/api/admin/images", json=image_input).status_code,
                        200,
                    )
                    image_id = admin.get("/api/admin/images").json()[0]["id"]
                    self.assertEqual(
                        other.get(
                            "/api/admin/images/" + image_id + "/file"
                        ).status_code,
                        404,
                    )
                    self.assertEqual(
                        admin.get(
                            "/api/client/" + token2 + "/images/" + image_id
                        ).status_code,
                        404,
                    )
                    with patch.object(
                        client,
                        "reply",
                        return_value={
                            "reply": "Aqui está o mapa",
                            "action": "send_image",
                            "image_id": image_id,
                        },
                    ):
                        admin.post(
                            "/api/client/" + token2 + "/messages",
                            json={"content": "Envie o mapa"},
                        )
                    sent = admin.get("/api/client/" + token2).json()["messages"][-1]
                    self.assertEqual(sent["image_id"], image_id)
                    self.assertEqual(admin.get(sent["image_url"]).status_code, 200)
                    foreign_token = other.post(
                        "/api/public/breve/start", json={"name": "Outro tenant"}
                    ).json()["token"]
                    with patch.object(
                        client,
                        "reply",
                        return_value={
                            "reply": "Imagem",
                            "action": "send_image",
                            "image_id": image_id,
                        },
                    ):
                        other.post(
                            "/api/client/" + foreign_token + "/messages",
                            json={"content": "Envie imagem"},
                        )
                    self.assertIsNone(
                        other.get("/api/client/" + foreign_token).json()["messages"][
                            -1
                        ]["image_id"]
                    )

                    import threading, time
                    from concurrent.futures import ThreadPoolExecutor
                    from app.db import Session
                    from app.media_models import ContactGate

                    spam_token = admin.post(
                        "/api/public/rincao/start", json={"name": "Teste spam"}
                    ).json()["token"]
                    spam_cid = admin.get("/api/admin/conversations").json()[0]["id"]
                    ready, unblock = threading.Event(), threading.Event()

                    def slow_reply(_):
                        ready.set()
                        unblock.wait(10)
                        return "Respondida"

                    with (
                        patch.object(
                            client, "reply", side_effect=slow_reply
                        ) as provider,
                        ThreadPoolExecutor(max_workers=3) as pool,
                    ):
                        futures = [
                            pool.submit(
                                admin.post,
                                "/api/client/" + spam_token + "/messages",
                                json={"content": str(i)},
                            )
                            for i in range(3)
                        ]
                        try:
                            self.assertTrue(ready.wait(5))
                            deadline = time.monotonic() + 5
                            while True:
                                with Session() as db:
                                    contact_id = db.get(
                                        Conversation, spam_cid
                                    ).contact_id
                                    pending = db.get(ContactGate, contact_id).pending
                                if pending == 3 or time.monotonic() > deadline:
                                    break
                                time.sleep(0.02)
                            self.assertEqual(pending, 3)
                            for _ in range(3):
                                admin.post(
                                    "/api/client/" + spam_token + "/messages",
                                    json={"content": "Mais uma"},
                                )
                            state = admin.get("/api/client/" + spam_token).json()
                            self.assertTrue(state["blocked"])
                            self.assertEqual(
                                len(
                                    [
                                        m
                                        for m in state["messages"]
                                        if m["sender"] == "sistema"
                                    ]
                                ),
                                3,
                            )
                            count = len(state["messages"])
                            admin.post(
                                "/api/client/" + spam_token + "/messages",
                                json={"content": "Bloqueado"},
                            )
                            self.assertEqual(
                                len(
                                    admin.get("/api/client/" + spam_token).json()[
                                        "messages"
                                    ]
                                ),
                                count,
                            )
                        finally:
                            unblock.set()
                        for future in futures:
                            self.assertEqual(future.result().status_code, 200)
                        self.assertEqual(provider.call_count, 3)
                    admin.post("/api/admin/conversations/" + spam_cid + "/unblock")
                    self.assertFalse(
                        admin.get("/api/client/" + spam_token).json()["blocked"]
                    )
                    with patch.object(
                        client, "reply", return_value="Saudação gerada pela IA"
                    ) as provider:
                        response = admin.post(
                            "/api/client/" + spam_token + "/messages",
                            json={"content": "Oi"},
                        )
                        self.assertEqual(response.status_code, 200)
                        provider.assert_called_once()
                    self.assertEqual(
                        admin.get("/api/client/" + spam_token).json()["messages"][-1][
                            "content"
                        ],
                        "Saudação gerada pela IA",
                    )
            finally:
                main.engine.dispose()


if __name__ == "__main__":
    unittest.main()
