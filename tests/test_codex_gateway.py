import base64
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from app import providers
from app.tenant_ai import AIConfig
from app.usage import api_cost

HTTP_CLIENT = httpx.Client
JPEG = b"\xff\xd8\xfftest-image\xff\xd9"


def answer(**changes):
    return {"reply": "Resposta.", "action": "none", "image_id": None,
            "profile_updates": [], "asked_objective_id": None, "tool_call": None, **changes}


def response(value=None, **changes):
    return {"status": "completed", "model": "gpt-6.1-terra", "effective_model": "gpt-6.1-terra",
            "output_text": json.dumps(answer() if value is None else value),
            "usage": {"input_tokens": 100, "cached_input_tokens": 30,
                      "output_tokens": 20, "reasoning_output_tokens": 4}, **changes}


class CodexGatewayTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.configuration = patch.object(providers, "configuration", return_value=
            AIConfig("codex_gateway", "gpt-6.1-terra")).start()
        patch.dict(os.environ, {"LUMI_CODEX_GATEWAY_URL": "https://gateway.example",
            "LUMI_CODEX_GATEWAY_TOKEN": "synthetic-token-at-least-32-characters"}).start()
        patch.object(providers.subprocess, "run", side_effect=AssertionError("CLI fallback")).start()
        patch("app.openai_provider.reply", side_effect=AssertionError("Paid fallback")).start()
        self.requests = []

    def transport(self, body=None, status=200, error=None):
        def handle(request):
            self.requests.append(request)
            if error:
                raise error
            return httpx.Response(status, json=response() if body is None else body)
        client = HTTP_CLIENT(transport=httpx.MockTransport(handle))
        self.addCleanup(client.close)
        self.client_factory = patch("httpx.Client", return_value=client).start()

    def test_text_images_schema_and_usage_use_authenticated_gateway(self):
        self.transport()
        result = providers.reply("private prompt", images=[JPEG], tenant_id="tenant-b")
        self.configuration.assert_called_once_with("tenant-b")
        self.assertEqual(result, answer())
        request = self.requests[0]
        body = json.loads(request.content)
        self.assertEqual(str(request.url), "https://gateway.example/v1/plan-next/responses")
        self.assertEqual(request.headers["Authorization"], "Bearer synthetic-token-at-least-32-characters")
        self.assertEqual(request.headers["Idempotency-Key"], body["request_id"])
        self.assertEqual(body["input"], "private prompt")
        self.assertEqual(body["model"], "gpt-6.1-terra")
        self.assertEqual(body["images"], [{"mime_type": "image/jpeg", "data_base64": base64.b64encode(JPEG).decode()}])
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertNotIn("tools", body)
        self.assertFalse(self.client_factory.call_args.kwargs["trust_env"])
        self.assertFalse(self.client_factory.call_args.kwargs["follow_redirects"])

    def test_optional_tool_arguments_are_restored_and_unknown_tool_is_rejected(self):
        tool = {"name": "lookup", "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}},
            "required": ["query"], "additionalProperties": False}}
        self.transport(response(answer(reply="", action="call_tool", tool_call={
            "name": "lookup", "arguments": {"query": "teste", "limit": None}})))
        self.assertEqual(providers.reply("test", tools=[tool])["tool_call"]["arguments"], {"query": "teste"})
        self.transport(response(answer(action="call_tool", tool_call={"name": "other", "arguments": {}})))
        with self.assertRaises(RuntimeError):
            providers.reply("test", tools=[tool])

    def test_invalid_output_and_usage_fail_without_leaking_details(self):
        for body in [response(status="incomplete"), response(output_text="private malformed"),
                     response(answer(reply="  ")), response(answer(action="call_tool")),
                     response({"reply": 4}), response(effective_model="other"),
                     response(usage={"input_tokens": "private", "output_tokens": 2})]:
            with self.subTest(body=body):
                self.transport(body)
                with self.assertRaises(RuntimeError) as error:
                    providers.reply("private prompt")
                self.assertNotIn("private", str(error.exception))

    def test_http_errors_and_timeouts_are_not_retried(self):
        for status, error in [(401, None), (302, None), (429, None),
                              (200, httpx.ReadTimeout("private token"))]:
            self.requests.clear()
            self.transport({"error": "private token"}, status, error)
            with self.assertRaises(RuntimeError) as caught:
                providers.reply("private prompt")
            self.assertNotIn("private", str(caught.exception))
            self.assertEqual(len(self.requests), 1)

    def test_unsafe_configuration_and_images_fail_before_request(self):
        self.transport()
        for url in ["", "http://remote.example", "https://user:secret@gateway.example",
                    "https://gateway.example?secret=value", "https://gateway.example/path"]:
            with self.subTest(url=url), patch.dict(os.environ, {"LUMI_CODEX_GATEWAY_URL": url}):
                with self.assertRaises(RuntimeError):
                    providers.reply("test")
        with patch.dict(os.environ, {"LUMI_CODEX_GATEWAY_TOKEN": ""}):
            with self.assertRaises(RuntimeError):
                providers.reply("test")
        for images in [[b"invalid"], [JPEG] * 3, [b"\xff\xd8\xff" + b"x" * (5 * 1024 * 1024)]]:
            with self.assertRaises(RuntimeError):
                providers.reply("test", images=images)
        self.assertEqual(self.requests, [])

    def test_codex_gateway_has_no_api_charge(self):
        self.assertEqual(api_cost(SimpleNamespace(provider="codex_gateway", estimated_usd=.5)), 0)

    def test_usage_and_failure_status_are_recorded_without_prompt(self):
        for body, expected in [(response(), "completed"), (response(usage=None), "completed"),
                               (response(output_text="private invalid"), "failed")]:
            self.transport(body)
            with patch("app.codex_gateway_provider.record") as record:
                if expected == "failed":
                    with self.assertRaises(RuntimeError):
                        providers.reply("private prompt")
                else:
                    providers.reply("private prompt")
            self.assertEqual(record.call_args.args[:3], ("codex_gateway", "gpt-6.1-terra", expected))
            self.assertEqual(record.call_args.kwargs["usage"], body["usage"])
            self.assertNotIn("private", str(record.call_args))

    def test_loopback_http_and_text_only_remain_supported(self):
        self.transport()
        with patch.dict(os.environ, {"LUMI_CODEX_GATEWAY_URL": "http://127.0.0.1:4317/"}):
            self.assertEqual(providers.reply("test"), answer())
        self.assertNotIn("images", json.loads(self.requests[0].content))
