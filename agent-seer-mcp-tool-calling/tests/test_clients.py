"""Unit tests for Agent Seer LLM Client Abstraction Layer (arXiv:2608.26133)."""
from __future__ import annotations

import io
import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from agent_seer.clients import (
    BaseLLMClient,
    LLMAuthError,
    LLMClientError,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMRateLimitError,
    LLMResponse,
    LLMResponseFormatError,
    LLMTimeoutError,
    MockClient,
    ModelGardenGemmaClient,
    TokenUsage,
    VertexGeminiClient,
    create_client,
    extract_json_payload,
    get_client,
)
from agent_seer.judge import JudgeEngine, judge_coherence, judge_tc
from agent_seer.linter import DeterministicLinter
from agent_seer.models import ToolCall, ToolDefinition


class TestTokenUsageAndResponse(unittest.TestCase):
    def test_token_usage_serialization(self):
        usage = TokenUsage(prompt_tokens=15, completion_tokens=25, total_tokens=40, cached_tokens=5)
        d = usage.to_dict()
        self.assertEqual(d["prompt_tokens"], 15)
        self.assertEqual(d["completion_tokens"], 25)
        self.assertEqual(d["total_tokens"], 40)
        self.assertEqual(d["cached_tokens"], 5)

        restored = TokenUsage.from_dict(d)
        self.assertEqual(restored.prompt_tokens, 15)
        self.assertEqual(restored.completion_tokens, 25)
        self.assertEqual(restored.total_tokens, 40)
        self.assertEqual(restored.cached_tokens, 5)

    def test_token_usage_from_vertex_dict(self):
        vertex_usage = {
            "promptTokenCount": 120,
            "candidatesTokenCount": 80,
            "totalTokenCount": 200,
            "cachedContentTokenCount": 30,
        }
        usage = TokenUsage.from_dict(vertex_usage)
        self.assertEqual(usage.prompt_tokens, 120)
        self.assertEqual(usage.completion_tokens, 80)
        self.assertEqual(usage.total_tokens, 200)
        self.assertEqual(usage.cached_tokens, 30)

    def test_llm_response_properties_and_json(self):
        payload = {"status": "ok", "count": 42}
        resp_text = f"```json\n{json.dumps(payload)}\n```"
        resp = LLMResponse(
            text=resp_text,
            model="gemini-2.5-flash",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            latency_ms=125.5,
            finish_reason="STOP",
            metadata={"test": True},
        )
        self.assertEqual(resp.content, resp_text)
        self.assertEqual(str(resp), resp_text)
        self.assertEqual(resp.json(), payload)
        d = resp.to_dict()
        self.assertEqual(d["model"], "gemini-2.5-flash")
        self.assertEqual(d["latency_ms"], 125.5)

    def test_extract_json_payload_variations(self):
        # Plain json
        self.assertEqual(extract_json_payload('{"a": 1}'), {"a": 1})
        # Fenced with json
        self.assertEqual(extract_json_payload('```json\n{"b": 2}\n```'), {"b": 2})
        # Fenced without json tag
        self.assertEqual(extract_json_payload('```\n{"c": 3}\n```'), {"c": 3})
        # Conversational text wrapping
        self.assertEqual(extract_json_payload('Here is the output:\n{"d": 4}\nHope this helps!'), {"d": 4})
        # Trailing comma repair
        self.assertEqual(extract_json_payload('{"e": [1, 2, ], "f": "val",}'), {"e": [1, 2], "f": "val"})
        # List payload
        self.assertEqual(extract_json_payload('[{"step": 1}]'), {"items": [{"step": 1}]})
        # Already parsed object
        self.assertEqual(extract_json_payload({"x": 10}), {"x": 10})
        # Invalid JSON error
        with self.assertRaises(LLMResponseFormatError):
            extract_json_payload("not valid json at all")


class TestMockClient(unittest.TestCase):
    def test_canned_dict_response(self):
        canned = {"tool_name": "veo_i2v", "confidence": "high"}
        client = MockClient(canned_responses=canned)
        resp = client.generate("test prompt")
        self.assertEqual(resp.json(), canned)
        self.assertEqual(client.call_count, 1)
        self.assertEqual(client.last_prompt, "test prompt")
        self.assertIsNotNone(client.last_call)

    def test_canned_string_response(self):
        client = MockClient(canned_responses="Simple text output")
        resp = client.generate("hello")
        self.assertEqual(resp.text, "Simple text output")

    def test_response_sequence(self):
        seq = [{"step": 1}, {"step": 2}, {"step": 3}]
        client = MockClient(response_sequence=seq)
        self.assertEqual(client.generate_json("q1"), {"step": 1})
        self.assertEqual(client.generate_json("q2"), {"step": 2})
        self.assertEqual(client.generate_json("q3"), {"step": 3})
        # When exhausted, falls back to auto generator
        resp = client.generate_json("q4")
        self.assertIsInstance(resp, dict)

    def test_pattern_matching_responses(self):
        client = MockClient(pattern_responses={
            "STAGE1": {"stage": 1, "done": True},
            r"stage\s*2": {"stage": 2, "done": True},
        })
        self.assertEqual(client.generate_json("Run STAGE1 task"), {"stage": 1, "done": True})
        self.assertEqual(client.generate_json("Execute stage 2 now"), {"stage": 2, "done": True})

    def test_response_generator_callback(self):
        def dynamic_gen(prompt, **kwargs):
            return {"echo": prompt.upper(), "custom": True}

        client = MockClient(response_generator=dynamic_gen)
        self.assertEqual(client.generate_json("sample query"), {"echo": "SAMPLE QUERY", "custom": True})

    def test_injected_errors(self):
        # Single exception
        client_single = MockClient(injected_errors=LLMTimeoutError("Simulated timeout"))
        with self.assertRaises(LLMTimeoutError):
            client_single.generate("test")

        # List of errors
        client_list = MockClient(injected_errors=[LLMRateLimitError("429"), None, LLMAuthError("401")])
        with self.assertRaises(LLMRateLimitError):
            client_list.generate("call 0")
        resp1 = client_list.generate("call 1")
        self.assertIsNotNone(resp1)
        with self.assertRaises(LLMAuthError):
            client_list.generate("call 2")

        # Dict of errors by call index
        client_dict = MockClient(injected_errors={1: LLMClientError("Error on call 1")})
        client_dict.generate("call 0")
        with self.assertRaises(LLMClientError):
            client_dict.generate("call 1")
        client_dict.generate("call 2")

    def test_simulated_latency(self):
        client = MockClient(canned_responses={"status": "ok"}, simulated_latency_ms=50.0)
        t0 = time.time()
        client.generate("timed call")
        elapsed = (time.time() - t0) * 1000.0
        self.assertGreaterEqual(elapsed, 40.0)

    def test_mock_client_presets(self):
        tc_client = MockClient.for_tc_judge(overall_score=0.95, rationale="Superb call")
        tc_res = tc_client.generate_json("Evaluate TC")
        self.assertIn("arguments", tc_res)
        self.assertEqual(tc_res["rationale"], "Superb call")

        coh_client = MockClient.for_coherence_judge(score_3=3)
        coh_res = coh_client.generate_json("Evaluate coherence")
        self.assertEqual(coh_res["logical_flow"], 3)

        s1_client = MockClient.for_pipeline_stage1("veo_extend")
        s1_res = s1_client.generate_json("Stage 1")
        self.assertEqual(s1_res["tool_name"], "veo_extend")

        s2_client = MockClient.for_pipeline_stage2("veo_extend")
        s2_res = s2_client.generate_json("Stage 2")
        self.assertIn("categories", s2_res)

        s3_client = MockClient.for_pipeline_stage3("veo_extend")
        s3_res = s3_client.generate_json("Stage 3")
        self.assertIn("mock_workflow", s3_res)

        s4_client = MockClient.for_pipeline_stage4()
        s4_res = s4_client.generate_json("Stage 4")
        self.assertIn("turns", s4_res)

    def test_auto_generate_mock_rubrics(self):
        client = MockClient()
        tc_res = client.generate_json("Evaluate usage, selection, and arguments for tool calling")
        self.assertIn("usage", tc_res)
        self.assertIn("selection", tc_res)
        self.assertIn("arguments", tc_res)

        coh_res = client.generate_json("Evaluate logical_flow and topic_relevance")
        self.assertIn("logical_flow", coh_res)
        self.assertIn("topic_relevance", coh_res)

        s1_res = client.generate_json('Describe what_it_does and enterprise_context for "name": "veo_i2v"')
        self.assertEqual(s1_res["tool_name"], "veo_i2v")

        s2_res = client.generate_json("Generate novel, and complex scenarios")
        self.assertIn("categories", s2_res)

        s3_res = client.generate_json("Generate mock_workflow with confidence level guidelines")
        self.assertIn("mock_workflow", s3_res)

        s4_res = client.generate_json("Generate multi-turn conversation with state chaining")
        self.assertIn("turns", s4_res)

    def test_assertion_helpers(self):
        client = MockClient(canned_responses={"status": "ok"})
        client.generate("first prompt with specific keyword")
        client.generate("second prompt")

        client.assert_called(2)
        client.assert_called_with_prompt_containing("specific keyword")

        with self.assertRaises(AssertionError):
            client.assert_called(5)

        with self.assertRaises(AssertionError):
            client.assert_called_with_prompt_containing("nonexistent phrase")

        client.reset()
        self.assertEqual(client.call_count, 0)
        with self.assertRaises(AssertionError):
            client.assert_called()


class TestVertexGeminiClient(unittest.TestCase):
    @patch("subprocess.check_output", return_value="mock-token-abc\n")
    @patch("urllib.request.urlopen")
    def test_gemini_generate_happy_path(self, mock_urlopen, mock_subp):
        payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Gemini response text"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 45,
                "candidatesTokenCount": 25,
                "totalTokenCount": 70,
            },
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = VertexGeminiClient(project_id="test-proj", location="us-central1")
        resp = client.generate("Test query", model="gemini-2.5-flash")

        self.assertEqual(resp.text, "Gemini response text")
        self.assertEqual(resp.model, "gemini-2.5-flash")
        self.assertEqual(resp.usage.prompt_tokens, 45)
        self.assertEqual(resp.usage.completion_tokens, 25)
        self.assertEqual(resp.usage.total_tokens, 70)
        self.assertEqual(resp.finish_reason, "STOP")

    @patch("subprocess.check_output", return_value="mock-token-abc\n")
    @patch("urllib.request.urlopen")
    def test_gemini_generate_json_structured(self, mock_urlopen, mock_subp):
        data = {"result": "success", "items": [1, 2, 3]}
        payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": f"```json\n{json.dumps(data)}\n```"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = VertexGeminiClient(project_id="test-proj")
        res_json = client.generate_json("Extract data")
        self.assertEqual(res_json, data)

    def test_url_construction(self):
        with patch.dict(os.environ, {}, clear=True):
            client_global = VertexGeminiClient(project_id="proj-123", location="global")
            url_global = client_global._build_url("gemini-2.5-flash")
            self.assertIn("locations/global/publishers/google/models/gemini-2.5-flash:generateContent", url_global)

            client_regional = VertexGeminiClient(project_id="proj-123", location="us-central1")
            url_reg = client_regional._build_url("gemini-2.5-pro")
            self.assertIn("https://us-central1-aiplatform.googleapis.com", url_reg)

            client_api_key = VertexGeminiClient(api_key="AIzaSyTestKey")
            url_key = client_api_key._build_url("gemini-2.5-flash")
            self.assertIn("key=AIzaSyTestKey", url_key)
            self.assertIn("generativelanguage.googleapis.com", url_key)

    @patch("subprocess.check_output", return_value="refreshed-token\n")
    def test_token_caching(self, mock_subp):
        client = VertexGeminiClient(access_token="initial-token")
        # Reuse initial token within TTL
        tok1 = client._get_bearer_token()
        self.assertEqual(tok1, "initial-token")
        self.assertEqual(mock_subp.call_count, 0)

        # Expire token cache
        client._token_cache["timestamp"] = time.time() - 2000
        tok2 = client._get_bearer_token()
        self.assertEqual(tok2, "refreshed-token")
        self.assertEqual(mock_subp.call_count, 1)

    @patch("time.sleep")
    @patch("subprocess.check_output", return_value="mock-token-abc\n")
    @patch("urllib.request.urlopen")
    def test_gemini_retry_on_429(self, mock_urlopen, mock_subp, mock_sleep):
        err_429 = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, io.BytesIO(b"Quota exceeded"))
        ok_payload = {
            "candidates": [{"content": {"parts": [{"text": "{\"recovered\": true}"}]}}]
        }
        ok_resp = MagicMock()
        ok_resp.read.return_value = json.dumps(ok_payload).encode("utf-8")
        ok_resp.status = 200
        ok_resp.__enter__.return_value = ok_resp

        mock_urlopen.side_effect = [err_429, ok_resp]

        client = VertexGeminiClient(project_id="test-proj", max_retries=3)
        res = client.generate_json("Prompt")
        self.assertEqual(res, {"recovered": True})
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("subprocess.check_output", return_value="mock-token-abc\n")
    @patch("urllib.request.urlopen")
    def test_gemini_auth_error_on_401(self, mock_urlopen, mock_subp):
        err_401 = urllib.error.HTTPError("url", 401, "Unauthorized", {}, io.BytesIO(b"Invalid Bearer Token"))
        mock_urlopen.side_effect = err_401

        client = VertexGeminiClient(project_id="test-proj")
        with self.assertRaises(LLMAuthError):
            client.generate("Test")

    @patch("subprocess.check_output", return_value="mock-token-abc\n")
    @patch("urllib.request.urlopen")
    def test_gemini_model_not_found_on_404(self, mock_urlopen, mock_subp):
        err_404 = urllib.error.HTTPError("url", 404, "Not Found", {}, io.BytesIO(b"Model does not exist"))
        mock_urlopen.side_effect = err_404

        client = VertexGeminiClient(project_id="test-proj")
        with self.assertRaises(LLMModelNotFoundError):
            client.generate("Test")

    @patch("subprocess.check_output", return_value="mock-token-abc\n")
    @patch("urllib.request.urlopen")
    def test_gemini_empty_candidate_error(self, mock_urlopen, mock_subp):
        payload = {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = VertexGeminiClient(project_id="test-proj")
        with self.assertRaises(LLMResponseFormatError):
            client.generate("Unsafe query")


class TestModelGardenGemmaClient(unittest.TestCase):
    @patch("subprocess.check_output", return_value="mock-token-abc\n")
    @patch("urllib.request.urlopen")
    def test_gemma_vertex_predict_happy_path(self, mock_urlopen, mock_subp):
        payload = {
            "predictions": [
                {"content": '{"analysis": "Gemma evaluation passed"}'}
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = ModelGardenGemmaClient(project_id="test-proj", location="us-central1")
        resp = client.generate_json("Evaluate tool call")
        self.assertEqual(resp, {"analysis": "Gemma evaluation passed"})

    @patch("urllib.request.urlopen")
    def test_gemma_openai_endpoint_happy_path(self, mock_urlopen):
        payload = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": '{"score": 9.5}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = ModelGardenGemmaClient(
            endpoint_url="https://vllm-endpoint.internal/v1/chat/completions",
            api_key="sk-test-key",
        )
        resp = client.generate("Evaluate")
        self.assertEqual(resp.json(), {"score": 9.5})
        self.assertEqual(resp.usage.total_tokens, 60)

    @patch("urllib.request.urlopen")
    def test_gemma_string_prediction(self, mock_urlopen):
        payload = {"predictions": ["Raw text prediction from model"]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = ModelGardenGemmaClient(project_id="test-proj")
        resp = client.generate("Query")
        self.assertEqual(resp.text, "Raw text prediction from model")


class TestClientFactory(unittest.TestCase):
    def test_create_client_explicit_types(self):
        mock_c = create_client(client_type="mock")
        self.assertIsInstance(mock_c, MockClient)

        vertex_c = create_client(client_type="vertex")
        self.assertIsInstance(vertex_c, VertexGeminiClient)

        gemini_c = create_client(client_type="gemini")
        self.assertIsInstance(gemini_c, VertexGeminiClient)

        gemma_c = create_client(client_type="gemma")
        self.assertIsInstance(gemma_c, ModelGardenGemmaClient)

        openai_c = create_client(client_type="openai")
        self.assertIsInstance(openai_c, ModelGardenGemmaClient)

    def test_create_client_auto_detection(self):
        with patch.dict(os.environ, {"MOCK_LLM": "1"}):
            c = create_client(client_type="auto")
            self.assertIsInstance(c, MockClient)

        with patch.dict(os.environ, {"GEMMA_ENDPOINT_URL": "http://localhost:8000/v1/chat/completions"}, clear=True):
            c = create_client(client_type="auto")
            self.assertIsInstance(c, ModelGardenGemmaClient)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaFakeKey"}, clear=True):
            c = create_client(client_type="auto")
            self.assertIsInstance(c, VertexGeminiClient)

        with patch.dict(os.environ, {}, clear=True):
            c = create_client(client_type="auto")
            self.assertIsInstance(c, MockClient)

    def test_create_client_invalid_type(self):
        with self.assertRaises(ValueError):
            create_client(client_type="unknown_unsupported")


class TestClientJudgeIntegration(unittest.TestCase):
    def test_mock_client_with_judge_tc(self):
        client = MockClient.for_tc_judge(overall_score=0.9)
        tool = ToolDefinition(name="sample_tool", description="A test tool")
        call = ToolCall(name="sample_tool", arguments={"param": "val"})

        res = judge_tc(
            tool_specs=[tool],
            user_prompt="Run sample tool",
            agent_calls=[call],
            client=client,
        )
        self.assertIn("scores", res)
        self.assertGreaterEqual(res["scores"].overall_tool_calling, 0.85)

    def test_mock_client_with_judge_coherence(self):
        client = MockClient.for_coherence_judge(score_3=3)
        res = judge_coherence(
            transcript_text="USER: Hi\nASSISTANT: Hello! How can I help?",
            client=client,
        )
        self.assertIn("scores", res)
        self.assertEqual(res["scores"].overall_coherence, 1.0)

    def test_judge_engine_with_polymorphic_clients(self):
        mock_c = MockClient.for_tc_judge(overall_score=0.95)
        tool = ToolDefinition(name="sample_tool")
        call = ToolCall(name="sample_tool", arguments={})

        linter = DeterministicLinter(tools=[tool])
        engine = JudgeEngine(client=mock_c, linter=linter)

        eval_res = engine.evaluate_tool_calls(
            tool_specs=[tool],
            user_prompt="Run",
            agent_calls=[call],
        )
        self.assertTrue(eval_res.passed)
        self.assertIsNotNone(eval_res.tool_calling)


if __name__ == "__main__":
    unittest.main()
