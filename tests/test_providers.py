import base64
import copy
import json
import unittest
from unittest.mock import patch

import httpx

from app import providers
from app.tenant_ai import AIConfig

HTTP_CLIENT = httpx.Client

def answer(**changes):
    return {"reply": "Resposta de teste.", "action": "none", "image_id": None,
            "profile_updates": [], "asked_objective_id": None, "tool_call": None, **changes}


def response(value=None, **changes):
    return {"status": "completed", "output": [{"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps(value or answer())}]}],
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 30},
                      "output_tokens": 20, "output_tokens_details": {"reasoning_tokens": 4}},
            **changes}


class OpenAIProviderTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.configuration = patch.object(providers, "configuration", return_value=
            AIConfig("openai", "test-model", "test-key")).start()
        self.codex = patch.object(providers.subprocess, "run", side_effect=AssertionError("Codex fallback")).start()
        self.record = patch.object(providers, "record").start()
        patch("app.openai_provider.record", self.record).start()
        self.requests = []

    def transport(self, body=None, status=200, error=None):
        def handle(request):
            self.requests.append(request)
            if error:
                raise error
            return httpx.Response(status, json=body if body is not None else response())
        client = HTTP_CLIENT(transport=httpx.MockTransport(handle))
        self.addCleanup(client.close)
        patch("httpx.Client", return_value=client).start()

    def test_text_image_schema_and_usage_keep_the_existing_reply_contract(self):
        self.transport()
        result = providers.reply("private test prompt", images=[b"test-image"], tenant_id="tenant-a")
        self.configuration.assert_called_once_with("tenant-a")
        self.assertEqual(result, answer())
        request = self.requests[0]
        self.assertEqual(str(request.url), "https://api.openai.com/v1/responses")
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")
        body = json.loads(request.content)
        self.assertEqual(body["model"], "test-model")
        self.assertIs(body["store"], False)
        self.assertEqual(body["service_tier"], "default")
        self.assertNotIn("tools", body)
        self.assertNotIn("previous_response_id", body)
        self.assertEqual(body["input"][0]["content"][0], {"type": "input_text", "text": "private test prompt"})
        self.assertEqual(body["input"][0]["content"][1]["image_url"],
                         "data:image/jpeg;base64," + base64.b64encode(b"test-image").decode())
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertEqual(self.record.call_args.args[:3], ("openai", "test-model", "completed"))
        self.assertEqual(self.record.call_args.kwargs["usage"], {
            "input_tokens": 100, "cached_input_tokens": 30, "output_tokens": 20, "reasoning_output_tokens": 4, "cache_write_tokens": None, "cache_write_30m_tokens": None,
            "cache_write_12h_tokens": None, "service_tier": None})
        self.assertNotIn("private test prompt", str(self.record.call_args))
        self.codex.assert_not_called()

    def test_existing_attendance_models_preserve_low_reasoning_without_forcing_other_models(self):
        self.transport()
        providers.reply("Teste", tenant_id="test-tenant")
        self.assertNotIn("reasoning", json.loads(self.requests[-1].content))
        self.configuration.return_value = AIConfig("openai", "gpt-6-luna", "test-key")
        self.transport()
        providers.reply("Teste", tenant_id="test-tenant")
        self.assertEqual(json.loads(self.requests[-1].content)["reasoning"], {"effort": "low"})

    def test_optional_tool_fields_are_nullable_on_wire_and_omitted_only_when_synthetic(self):
        tool = {"name": "lookup", "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1},
            "nullable": {"type": ["string", "null"]},
            "options": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "extra": {"type": "string"}}, "required": ["label"]}}},
            "required": ["query"]}}
        original = copy.deepcopy(tool)
        self.transport(response(answer(action="call_tool", tool_call={"name": "lookup", "arguments": {
            "query": "teste", "limit": None, "nullable": None,
            "options": [{"label": "ok", "extra": None}]}})))
        result = providers.reply("teste", tools=[tool])
        self.assertEqual(result["tool_call"]["arguments"], {
            "query": "teste", "nullable": None, "options": [{"label": "ok"}]})
        self.assertEqual(tool, original)
        schema = json.loads(self.requests[0].content)["text"]["format"]["schema"]
        args = schema["properties"]["tool_call"]["anyOf"][1]["properties"]["arguments"]
        self.assertEqual(set(args["required"]), set(tool["parameters"]["properties"]))
        self.assertFalse(args["additionalProperties"])

    def test_invalid_arguments_and_unknown_tool_are_rejected(self):
        tool = {"name": "lookup", "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "minimum": 1}}, "required": ["limit"], "additionalProperties": False}}
        for call in [{"name": "lookup", "arguments": {"limit": 0}},
                     {"name": "other", "arguments": {"limit": 1}}]:
            with self.subTest(call=call):
                self.transport(response(answer(action="call_tool", tool_call=call)))
                with self.assertRaises(RuntimeError):
                    providers.reply("teste", tools=[tool])
                self.assertEqual(self.record.call_args.args[2], "failed")

    def test_tool_selection_accepts_empty_reply_before_result_is_available(self):
        tool = {"name": "lookup", "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}}
        selected = answer(reply="", action="call_tool", tool_call={"name": "lookup", "arguments": {"query": "teste"}})
        self.transport(response(selected))
        self.assertEqual(providers.reply("teste", tools=[tool]), selected)
        self.assertEqual(self.record.call_args.args[2], "completed")

    def test_refusal_incomplete_invalid_json_and_invalid_shape_never_become_answers(self):
        bodies = [response(status="incomplete"), response(output=[]),
                  response(output=[{"type": "message", "content": [{"type": "refusal", "refusal": "private"}]}]),
                  response(output=[{"type": "message", "content": [{"type": "output_text", "text": "private not json"}]}]),
                  response({"reply": 4}), response(answer(action="call_tool")),
                  response(answer(reply="  ")), {"status": "completed", "output": None}]
        for body in bodies:
            with self.subTest(body=body):
                self.transport(body)
                with self.assertRaises(RuntimeError) as error:
                    providers.reply("private prompt")
                self.assertNotIn("private", str(error.exception))
                self.assertEqual(self.record.call_args.args[2], "failed")

    def test_http_error_and_timeout_do_not_leak_details_or_retry(self):
        for error in [None, httpx.ReadTimeout("private upstream body")]:
            with self.subTest(error=error):
                self.requests.clear()
                self.transport({"error": {"message": "private upstream body"}}, status=401, error=error)
                with self.assertRaises(RuntimeError) as caught:
                    providers.reply("private prompt")
                self.assertNotIn("private", str(caught.exception))
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(self.record.call_args.args[2], "failed")
                self.codex.assert_not_called()

    def test_missing_configuration_fails_before_request_and_no_default_model_is_chosen(self):
        self.transport()
        for config in [AIConfig("openai", "test-model"), AIConfig("openai", "", "test-key")]:
            with self.subTest(model=config.model, has_key=bool(config.api_key)):
                self.configuration.return_value = config
                with self.assertRaises(RuntimeError):
                    providers.reply("teste")
        self.assertEqual(self.requests, [])
        self.codex.assert_not_called()

    def test_missing_usage_stays_unknown(self):
        self.transport(response(usage=None))
        providers.reply("teste")
        self.assertIsNone(self.record.call_args.kwargs["usage"])

    def test_actual_zero_cache_writes_can_omit_ttls_but_positive_writes_cannot(self):
        from app.usage import estimate_openai
        for written in (0, 40):
            with self.subTest(written=written):
                body = response(service_tier="default")
                body["usage"]["input_tokens_details"]["cache_write_tokens"] = written
                self.transport(body)
                providers.reply("teste")
                usage = self.record.call_args.kwargs["usage"]
                if written == 0:
                    self.assertEqual(usage["cache_write_30m_tokens"], 0)
                    self.assertEqual(usage["cache_write_12h_tokens"], 0)
                    self.assertAlmostEqual(estimate_openai("gpt-6-luna", usage), .0000173)
                else:
                    self.assertIsNone(estimate_openai("gpt-6-luna", usage))

    def test_unknown_provider_and_demo_do_not_call_any_model(self):
        self.transport()
        self.configuration.return_value = AIConfig("typo", "test-model")
        with self.assertRaises(RuntimeError):
            providers.reply("teste")
        self.configuration.return_value = AIConfig("demo", "")
        self.assertIn("demonstração", providers.reply("teste"))
        self.assertEqual(self.requests, [])
        self.codex.assert_not_called()
