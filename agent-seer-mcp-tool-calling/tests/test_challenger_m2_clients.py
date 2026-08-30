"""Adversarial stress and fuzz testing suite for Agent Seer LLM Client Abstraction Layer (arXiv:2608.26133).

Author: Challenger 1 (Milestone 2)
Modules under test:
- `src/agent_seer/clients.py`:
  - MockClient (regex edge cases, unhandled routes, queue exhaustion, multithreaded concurrency)
  - VertexGeminiClient (malformed payloads, 401/403/404/429/500 status codes, network errors, large/empty prompts)
  - ModelGardenGemmaClient (OpenAI & Vertex schemas, error transitions, retry backoff)
  - extract_json_payload (JSON fuzzing, trailing commas, markdown fences, conversational text)
  - create_client / get_client Factory (case-insensitivity, invalid types, env var precedence)
"""
from __future__ import annotations

import concurrent.futures
import io
import json
import os
import re
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

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


class TestChallengerMockClientAdversarial(unittest.TestCase):
    """Adversarial testing of MockClient routing, concurrency, queues, and assertions."""

    def test_mock_client_regex_and_pattern_edge_cases(self):
        """Test MockClient with complex regex, special characters, and first-match precedence."""
        patterns = {
            r"^STAGE-(\d+)\[(.*?)\]$": {"matched": "anchored_stage_regex"},
            r"(?i)tool_name:\s*\"([a-z_]+)\"": {"matched": "case_insensitive_tool"},
            r"a\+b\*c\?": {"matched": "literal_metachars"},
            "": {"matched": "empty_pattern_fallback"},
        }
        client = MockClient(pattern_responses=patterns)

        # 1. Matches anchored regex with group capture
        r1 = client.generate_json("STAGE-1[param_x]")
        self.assertEqual(r1.get("matched"), "anchored_stage_regex")

        # 2. Matches case-insensitive tool pattern
        r2 = client.generate_json('TOOL_NAME: "sample_tool"')
        self.assertEqual(r2.get("matched"), "case_insensitive_tool")

        # 3. Matches literal metachars
        r3 = client.generate_json("Test with a+b*c? in prompt")
        self.assertEqual(r3.get("matched"), "literal_metachars")

        # 4. Empty pattern matches any remaining prompt
        r4 = client.generate_json("Completely random prompt with no other keywords")
        self.assertEqual(r4.get("matched"), "empty_pattern_fallback")

    def test_mock_client_routing_precedence_hierarchy(self):
        """Verify strict priority: response_generator > pattern_responses > _queue > _canned > auto_generate."""
        # 1. Response generator takes precedence when configured
        gen_fn = lambda prompt, **kwargs: {"source": "generator", "echo": prompt}
        c_gen = MockClient(response_generator=gen_fn, canned_responses={"source": "canned"})
        self.assertEqual(c_gen.generate_json("Any prompt")["source"], "generator")

        # 2. Pattern responses take precedence over canned response
        c_pat = MockClient(
            pattern_responses={"MATCH_KEY": {"source": "pattern"}},
            canned_responses={"source": "canned"},
        )
        self.assertEqual(c_pat.generate_json("Contains MATCH_KEY here")["source"], "pattern")
        self.assertEqual(c_pat.generate_json("No pattern match")["source"], "canned")

        # 3. Response sequence yields in FIFO order, then falls back to auto generator
        c_seq = MockClient(response_sequence=[{"source": "queue_1"}, {"source": "queue_2"}])
        self.assertEqual(c_seq.generate_json("call 1")["source"], "queue_1")
        self.assertEqual(c_seq.generate_json("call 2")["source"], "queue_2")
        self.assertEqual(c_seq.generate_json("call 3")["status"], "success")

    def test_mock_client_auto_generator_all_rubric_branches(self):
        """Verify auto-generation heuristics for all pipeline stages and judge rubrics."""
        client = MockClient()

        # TC Judge branch
        res_tc = client.generate_json("Evaluate usage, selection, and arguments for tool calling")
        self.assertIn("usage", res_tc)
        self.assertIn("selection", res_tc)
        self.assertIn("ordering", res_tc)
        self.assertIn("arguments", res_tc)
        self.assertEqual(res_tc["usage"]["necessity"], 10)

        # Coherence Judge branch
        res_coh = client.generate_json("Assess logical_flow and topic_relevance across conversation")
        self.assertIn("logical_flow", res_coh)
        self.assertIn("topic_relevance", res_coh)
        self.assertEqual(res_coh["logical_flow"], 3)

        # Stage 1 Interpretation with extracted name
        res_s1 = client.generate_json('Analyze what_it_does and enterprise_context for "name": "custom_image_gen"')
        self.assertEqual(res_s1["tool_name"], "custom_image_gen")
        self.assertIn("Media Production", res_s1["enterprise_context"])

        # Stage 1 without tool_name in prompt
        res_s1_default = client.generate_json("Analyze what_it_does and enterprise_context")
        self.assertEqual(res_s1_default["tool_name"], "mock_tool")

        # Stage 2 Scenario: complex
        res_s2_complex = client.generate_json("Generate novel, and complex scenarios")
        self.assertIn("categories", res_s2_complex)
        self.assertIn("complex", res_s2_complex["categories"][0]["scenarios"][0]["novelty_reason"])

        # Stage 2 Scenario: boundary
        res_s2_boundary = client.generate_json("Generate boundary scenarios")
        self.assertIn("boundary", res_s2_boundary["categories"][0]["scenarios"][0]["novelty_reason"])

        # Stage 2 Scenario: simple
        res_s2_simple = client.generate_json("Generate straightforward, and commonplace scenarios")
        self.assertIn("simple", res_s2_simple["categories"][0]["scenarios"][0]["novelty_reason"])

        # Stage 3 Mock Workflow
        res_s3 = client.generate_json("Generate mock_workflow with confidence level guidelines")
        self.assertIn("mock_workflow", res_s3)
        self.assertEqual(res_s3["mock_workflow"][0]["confidence"], "high")

        # Stage 4 Multi-turn transcript
        res_s4 = client.generate_json("Generate multi-turn conversation with state chaining")
        self.assertIn("turns", res_s4)
        self.assertEqual(len(res_s4["turns"]), 2)

        # Default unmatched fallback
        res_default = client.generate_json("A prompt with none of the domain keywords whatsoever")
        self.assertEqual(res_default, {"status": "success", "content": "Mock response"})

    def test_mock_client_queue_exhaustion_behavior(self):
        """Test FIFO consumption of response_sequence and clean transition upon exhaustion."""
        items = [{"item": 1}, {"item": 2}]
        client = MockClient(response_sequence=items)

        # Consuming items
        self.assertEqual(client.generate_json("p1"), {"item": 1})
        self.assertEqual(client.generate_json("p2"), {"item": 2})

        # Queue is now empty, next call falls back to auto-generator without raising IndexError
        fallback = client.generate_json("p3 with no keywords")
        self.assertEqual(fallback, {"status": "success", "content": "Mock response"})
        self.assertEqual(client.call_count, 3)

    def test_mock_client_multithreaded_concurrency_stress(self):
        """Stress test MockClient under heavy concurrent multi-threaded load (50 concurrent threads)."""
        client = MockClient(simulated_latency_ms=1.0)
        num_threads = 50
        errors = []

        def worker(thread_id: int):
            try:
                prompt = f"Concurrent worker thread {thread_id} prompt"
                resp = client.generate(prompt)
                if resp.model != "mock-seer-model":
                    errors.append(f"Unexpected model: {resp.model}")
                if prompt not in resp.text and "content" not in resp.text:
                    errors.append(f"Unexpected response text: {resp.text}")
            except Exception as e:
                errors.append(str(e))

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        self.assertEqual(len(errors), 0, f"Thread errors encountered: {errors}")
        self.assertEqual(client.call_count, num_threads)
        self.assertEqual(len(client.call_history), num_threads)

    def test_mock_client_injected_error_variations(self):
        """Test injected errors: single exception, sparse dict mapping, and list with None values."""
        # 1. Sparse dict mapping
        client_dict = MockClient(injected_errors={
            0: LLMRateLimitError("Call 0 rate limited"),
            2: LLMAuthError("Call 2 unauthorized"),
        })
        with self.assertRaises(LLMRateLimitError):
            client_dict.generate("c0")

        # Call 1 succeeds
        res1 = client_dict.generate("c1")
        self.assertIsNotNone(res1)

        with self.assertRaises(LLMAuthError):
            client_dict.generate("c2")

        # Call 3 succeeds
        res3 = client_dict.generate("c3")
        self.assertIsNotNone(res3)

        # 2. List with None entries
        client_list = MockClient(injected_errors=[None, LLMTimeoutError("Call 1 timed out"), None])
        client_list.generate("c0")
        with self.assertRaises(LLMTimeoutError):
            client_list.generate("c1")
        client_list.generate("c2")
        client_list.generate("c3 - past list length")

        # 3. Single Exception instance
        client_single = MockClient(injected_errors=RuntimeError("Generic runtime failure"))
        with self.assertRaises(RuntimeError):
            client_single.generate("any")

    def test_mock_client_assertion_and_reset_edges(self):
        """Test edge cases for MockClient assertion methods and state reset."""
        client = MockClient(canned_responses={"status": "ok"})

        # assert_called on fresh client raises AssertionError
        with self.assertRaises(AssertionError):
            client.assert_called()

        client.generate("first alpha prompt")
        client.generate("second beta prompt")

        # Exact count matching
        client.assert_called(2)
        with self.assertRaises(AssertionError):
            client.assert_called(1)
        with self.assertRaises(AssertionError):
            client.assert_called(3)

        # Substring search
        client.assert_called_with_prompt_containing("alpha")
        client.assert_called_with_prompt_containing("beta")
        with self.assertRaises(AssertionError):
            client.assert_called_with_prompt_containing("gamma")

        # Reset clears history and invocation count
        client.reset()
        self.assertEqual(client.call_count, 0)
        self.assertIsNone(client.last_prompt)
        self.assertIsNone(client.last_call)


class TestChallengerVertexGeminiAdversarial(unittest.TestCase):
    """Adversarial testing of VertexGeminiClient HTTP edge cases, retry dynamics, and boundary payloads."""

    @patch("subprocess.check_output", return_value="test-token\n")
    @patch("urllib.request.urlopen")
    def test_gemini_malformed_non_json_http_response(self, mock_urlopen, mock_subp):
        """Malformed non-JSON HTTP response (e.g. 502 HTML) triggers retry loop."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html><head><title>502 Bad Gateway</title></head><body>502 Server Error</body></html>"
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = VertexGeminiClient(project_id="test-proj", max_retries=2, backoff_factor=1.0)
        with patch("time.sleep"):
            with self.assertRaises((LLMClientError, json.JSONDecodeError)):
                client.generate("Prompt")
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("subprocess.check_output", return_value="test-token\n")
    @patch("urllib.request.urlopen")
    def test_gemini_empty_parts_and_null_candidates(self, mock_urlopen, mock_subp):
        """Response with candidates having empty parts list returns empty string without crashing."""
        payload = {
            "candidates": [
                {
                    "content": {"parts": []},
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {"promptTokenCount": 10},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = VertexGeminiClient(project_id="test-proj")
        resp = client.generate("Prompt")
        self.assertEqual(resp.text, "")
        self.assertEqual(resp.finish_reason, "MAX_TOKENS")
        self.assertEqual(resp.usage.prompt_tokens, 10)
        self.assertEqual(resp.usage.completion_tokens, 0)

    @patch("subprocess.check_output", return_value="test-token\n")
    @patch("urllib.request.urlopen")
    def test_gemini_safety_block_without_candidates(self, mock_urlopen, mock_subp):
        """Response with empty candidates list and promptFeedback blockReason raises LLMResponseFormatError."""
        payload = {
            "candidates": [],
            "promptFeedback": {"blockReason": "PROHIBITED_CONTENT"},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = VertexGeminiClient(project_id="test-proj")
        with self.assertRaises(LLMResponseFormatError) as ctx:
            client.generate("Unsafe query")
        self.assertIn("PROHIBITED_CONTENT", str(ctx.exception))

    @patch("subprocess.check_output", return_value="test-token\n")
    @patch("urllib.request.urlopen")
    def test_gemini_http_401_403_no_retries(self, mock_urlopen, mock_subp):
        """HTTP 401 Unauthorized and 403 Forbidden fail immediately with LLMAuthError (no retries)."""
        err_401 = urllib.error.HTTPError("url", 401, "Unauthorized", {}, io.BytesIO(b"Expired token"))
        mock_urlopen.side_effect = err_401

        client = VertexGeminiClient(project_id="test-proj", max_retries=3)
        with self.assertRaises(LLMAuthError) as ctx:
            client.generate("Test")
        self.assertEqual(mock_urlopen.call_count, 1)
        self.assertEqual(ctx.exception.status_code, 401)

        err_403 = urllib.error.HTTPError("url", 403, "Forbidden", {}, io.BytesIO(b"Permission denied"))
        mock_urlopen.side_effect = err_403
        with self.assertRaises(LLMAuthError) as ctx:
            client.generate("Test")
        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertEqual(ctx.exception.status_code, 403)

    @patch("subprocess.check_output", return_value="test-token\n")
    @patch("urllib.request.urlopen")
    def test_gemini_http_400_bad_request_no_retries(self, mock_urlopen, mock_subp):
        """HTTP 400 Bad Request raises LLMClientError immediately without retrying."""
        err_400 = urllib.error.HTTPError("url", 400, "Bad Request", {}, io.BytesIO(b"Invalid JSON schema"))
        mock_urlopen.side_effect = err_400

        client = VertexGeminiClient(project_id="test-proj", max_retries=3)
        with self.assertRaises(LLMClientError) as ctx:
            client.generate("Test")
        self.assertEqual(mock_urlopen.call_count, 1)
        self.assertEqual(ctx.exception.status_code, 400)

    @patch("subprocess.check_output", return_value="test-token\n")
    @patch("urllib.request.urlopen")
    def test_gemini_http_500_503_retries_and_exhaustion(self, mock_urlopen, mock_subp):
        """HTTP 500/503 errors are retried max_retries times before raising LLMClientError."""
        err_503 = urllib.error.HTTPError("url", 503, "Service Unavailable", {}, io.BytesIO(b"Backend overloaded"))
        mock_urlopen.side_effect = err_503

        client = VertexGeminiClient(project_id="test-proj", max_retries=3, backoff_factor=1.0)
        with patch("time.sleep") as mock_sleep:
            with self.assertRaises(LLMClientError) as ctx:
                client.generate("Test")
        self.assertEqual(mock_urlopen.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertEqual(ctx.exception.status_code, 503)

    @patch("subprocess.check_output", return_value="test-token\n")
    @patch("urllib.request.urlopen")
    def test_gemini_network_connection_error_retries(self, mock_urlopen, mock_subp):
        """Network URLError (e.g. DNS failure) is retried and raises LLMConnectionError."""
        url_err = urllib.error.URLError("Connection refused [Errno 61]")
        mock_urlopen.side_effect = url_err

        client = VertexGeminiClient(project_id="test-proj", max_retries=2, backoff_factor=1.0)
        with patch("time.sleep"):
            with self.assertRaises(LLMConnectionError):
                client.generate("Test")
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("subprocess.check_output", return_value="test-token\n")
    @patch("urllib.request.urlopen")
    def test_gemini_boundary_prompts_and_custom_endpoint(self, mock_urlopen, mock_subp):
        """Test empty prompt, large prompt (>100KB), and custom endpoint override."""
        payload = {
            "candidates": [{"content": {"parts": [{"text": "OK"}]}}],
            "usageMetadata": {"promptTokenCount": 5000, "candidatesTokenCount": 2},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # Custom endpoint test
        client = VertexGeminiClient(custom_endpoint="https://custom-proxy.internal/v1/generate")
        self.assertEqual(client._build_url("any-model"), "https://custom-proxy.internal/v1/generate")

        # Extremely large prompt payload (100,000 chars)
        large_prompt = "Alpha Beta Gamma " * 6000
        resp_large = client.generate(large_prompt)
        self.assertEqual(resp_large.text, "OK")

        # Empty string prompt
        resp_empty = client.generate("")
        self.assertEqual(resp_empty.text, "OK")

    @patch("subprocess.check_output", side_effect=Exception("gcloud not installed"))
    def test_gemini_auth_failure_when_no_credentials(self, mock_subp):
        """LLMAuthError is raised if gcloud fails and no explicit access_token or api_key is configured."""
        with patch.dict(os.environ, {}, clear=True):
            client = VertexGeminiClient(project_id="test-proj")
            with self.assertRaises(LLMAuthError) as ctx:
                client._get_bearer_token()
            self.assertIn("Failed to acquire GCP access token", str(ctx.exception))


class TestChallengerModelGardenGemmaAdversarial(unittest.TestCase):
    """Adversarial testing of ModelGardenGemmaClient schemas, errors, and URL routing."""

    @patch("urllib.request.urlopen")
    def test_gemma_openai_schema_empty_choices(self, mock_urlopen):
        """OpenAI-compatible payload with empty choices list falls back to string payload without crash."""
        payload = {"choices": [], "id": "chatcmpl-test", "created": 12345}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = ModelGardenGemmaClient(endpoint_url="https://internal-llm/v1/chat/completions", api_key="sk-test")
        resp = client.generate("Evaluate")
        self.assertIn("chatcmpl-test", resp.text)

    @patch("urllib.request.urlopen")
    def test_gemma_vertex_predict_various_prediction_formats(self, mock_urlopen):
        """Vertex Model Garden :predict response handles dicts, strings, and lists in predictions."""
        # 1. Dict prediction with 'content'
        payload1 = {"predictions": [{"content": '{"score": 10}'}]}
        mock_resp1 = MagicMock()
        mock_resp1.read.return_value = json.dumps(payload1).encode("utf-8")
        mock_resp1.status = 200
        mock_resp1.__enter__.return_value = mock_resp1
        mock_urlopen.return_value = mock_resp1

        client = ModelGardenGemmaClient(project_id="test-proj")
        r1 = client.generate_json("Prompt 1")
        self.assertEqual(r1, {"score": 10})

        # 2. Raw string prediction
        payload2 = {"predictions": ["Gemma raw text prediction"]}
        mock_resp2 = MagicMock()
        mock_resp2.read.return_value = json.dumps(payload2).encode("utf-8")
        mock_resp2.status = 200
        mock_resp2.__enter__.return_value = mock_resp2
        mock_urlopen.return_value = mock_resp2

        r2 = client.generate("Prompt 2")
        self.assertEqual(r2.text, "Gemma raw text prediction")

        # 3. Arbitrary object prediction
        payload3 = {"predictions": [{"custom_key": 999}]}
        mock_resp3 = MagicMock()
        mock_resp3.read.return_value = json.dumps(payload3).encode("utf-8")
        mock_resp3.status = 200
        mock_resp3.__enter__.return_value = mock_resp3
        mock_urlopen.return_value = mock_resp3

        r3 = client.generate("Prompt 3")
        self.assertIn('"custom_key": 999', r3.text)

    @patch("urllib.request.urlopen")
    def test_gemma_http_status_errors(self, mock_urlopen):
        """Verify Gemma client handles 401, 404, 429, 500 error transitions appropriately."""
        client = ModelGardenGemmaClient(endpoint_url="https://internal-llm/predict", max_retries=2, backoff_factor=1.0)

        # 401 -> LLMAuthError
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 401, "Unauthorized", {}, io.BytesIO(b"Bad API key"))
        with self.assertRaises(LLMAuthError):
            client.generate("Test")

        # 404 -> LLMModelNotFoundError
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 404, "Not Found", {}, io.BytesIO(b"Model not deployed"))
        with self.assertRaises(LLMModelNotFoundError):
            client.generate("Test")

        # 429 -> LLMRateLimitError (retried)
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 429, "Rate Limit", {}, io.BytesIO(b"Quota"))
        with patch("time.sleep"):
            with self.assertRaises(LLMRateLimitError):
                client.generate("Test")

        # 500 -> LLMClientError (retried)
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 500, "Internal Error", {}, io.BytesIO(b"OOM"))
        with patch("time.sleep"):
            with self.assertRaises(LLMClientError):
                client.generate("Test")


class TestChallengerJsonExtractorFuzzing(unittest.TestCase):
    """Fuzzing and adversarial stress testing for extract_json_payload."""

    def test_clean_and_wrapped_json(self):
        self.assertEqual(extract_json_payload('{"status": "ok"}'), {"status": "ok"})
        self.assertEqual(extract_json_payload('   {"val": 123}   \n'), {"val": 123})

    def test_markdown_code_fences_variations(self):
        # json tag
        self.assertEqual(extract_json_payload('```json\n{"score": 9.5}\n```'), {"score": 9.5})
        # no tag
        self.assertEqual(extract_json_payload('```\n{"score": 8.0}\n```'), {"score": 8.0})
        # multiple backticks / chatter before and after
        text = "Evaluation result:\n```json\n{\n  \"nested\": {\"field\": true}\n}\n```\nEnd of transcript."
        self.assertEqual(extract_json_payload(text), {"nested": {"field": True}})

    def test_conversational_text_wrapping(self):
        """Handles conversational chatter around valid JSON."""
        text = 'Here is the generated analysis payload:\n{"corrected": true, "code": 200}\nHope this helps!'
        res = extract_json_payload(text)
        self.assertEqual(res, {"corrected": True, "code": 200})

    def test_trailing_commas_in_objects_and_arrays(self):
        """Robustly repairs trailing commas in dicts and lists."""
        payload_trailing_comma = '{"items": [1, 2, 3, ], "config": {"timeout": 30, }, }'
        res = extract_json_payload(payload_trailing_comma)
        self.assertEqual(res["items"], [1, 2, 3])
        self.assertEqual(res["config"]["timeout"], 30)

    def test_list_payload_wrapping(self):
        """Top-level JSON arrays are automatically wrapped into {'items': [...]}."""
        res_list = extract_json_payload('[{"turn": 1}, {"turn": 2}]')
        self.assertEqual(res_list, {"items": [{"turn": 1}, {"turn": 2}]})

        # List with trailing comma
        res_list_trailing = extract_json_payload('["a", "b", "c", ]')
        self.assertEqual(res_list_trailing, {"items": ["a", "b", "c"]})

    def test_primitive_and_pre_parsed_inputs(self):
        """Handles already-parsed dicts, lists, and primitive JSON literals."""
        self.assertEqual(extract_json_payload({"already": "dict"}), {"already": "dict"})
        self.assertEqual(extract_json_payload([1, 2]), {"items": [1, 2]})
        self.assertEqual(extract_json_payload("true"), {"data": True})
        self.assertEqual(extract_json_payload("12345"), {"data": 12345})

    def test_invalid_json_raises_llm_response_format_error(self):
        """Completely invalid text or unclosed structures raise LLMResponseFormatError."""
        with self.assertRaises(LLMResponseFormatError):
            extract_json_payload("This is pure english text with no json whatsoever.")

        with self.assertRaises(LLMResponseFormatError):
            extract_json_payload('{"unclosed_key": "val')


class TestChallengerClientFactoryAdversarial(unittest.TestCase):
    """Adversarial testing of create_client / get_client factory logic and error handling."""

    def test_factory_case_insensitivity(self):
        """Factory is completely case-insensitive for all supported client types."""
        self.assertIsInstance(create_client(client_type="MOCK"), MockClient)
        self.assertIsInstance(create_client(client_type="mOcK"), MockClient)
        self.assertIsInstance(create_client(client_type="VERTEX"), VertexGeminiClient)
        self.assertIsInstance(create_client(client_type="VeRtEx"), VertexGeminiClient)
        self.assertIsInstance(create_client(client_type="GEMINI"), VertexGeminiClient)
        self.assertIsInstance(create_client(client_type="GeMiNi"), VertexGeminiClient)
        self.assertIsInstance(create_client(client_type="GEMMA"), ModelGardenGemmaClient)
        self.assertIsInstance(create_client(client_type="gEmMa"), ModelGardenGemmaClient)
        self.assertIsInstance(create_client(client_type="OPENAI"), ModelGardenGemmaClient)
        self.assertIsInstance(create_client(client_type="OpEnAi"), ModelGardenGemmaClient)

    def test_factory_invalid_client_type_raises_value_error(self):
        """Unknown or unsupported client types raise informative ValueError."""
        invalid_types = ["anthropic", "claude", "bedrock", "llama", "deepseek", "", "   ", "custom_unknown"]
        for bad_type in invalid_types:
            with self.assertRaises(ValueError) as ctx:
                create_client(client_type=bad_type)
            self.assertIn("Unknown client_type", str(ctx.exception))

    def test_factory_auto_detection_precedence_matrix(self):
        """Test complete auto-detection precedence matrix under various environment variable configurations."""
        # 1. MOCK_LLM=1 overrides all
        with patch.dict(os.environ, {"MOCK_LLM": "1", "GEMINI_API_KEY": "fake-key", "GEMMA_ENDPOINT_URL": "http://gemma"}):
            c = create_client(client_type="auto")
            self.assertIsInstance(c, MockClient)

        # 2. MOCK_LLM=true / yes
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            self.assertIsInstance(create_client(client_type="auto"), MockClient)
        with patch.dict(os.environ, {"MOCK_LLM": "yes"}):
            self.assertIsInstance(create_client(client_type="auto"), MockClient)

        # 3. GEMMA_ENDPOINT_URL takes precedence over Gemini in auto-detection
        with patch.dict(os.environ, {"GEMMA_ENDPOINT_URL": "http://vllm:8000/v1/chat/completions"}, clear=True):
            self.assertIsInstance(create_client(client_type="auto"), ModelGardenGemmaClient)

        # 4. OPENAI_BASE_URL triggers ModelGardenGemmaClient
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "http://ollama:11434/v1"}, clear=True):
            self.assertIsInstance(create_client(client_type="auto"), ModelGardenGemmaClient)

        # 5. Model name containing 'gemma' triggers ModelGardenGemmaClient
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(create_client(client_type="auto", model="gemma-2-9b-it"), ModelGardenGemmaClient)

        # 6. GEMINI_API_KEY triggers VertexGeminiClient
        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSyTestKey"}, clear=True):
            self.assertIsInstance(create_client(client_type="auto"), VertexGeminiClient)

        # 7. VERTEX_API_KEY triggers VertexGeminiClient
        with patch.dict(os.environ, {"VERTEX_API_KEY": "VertexSecretKey"}, clear=True):
            self.assertIsInstance(create_client(client_type="auto"), VertexGeminiClient)

        # 8. GOOGLE_CLOUD_PROJECT triggers VertexGeminiClient
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "my-gcp-project"}, clear=True):
            self.assertIsInstance(create_client(client_type="auto"), VertexGeminiClient)

        # 9. GCP_ACCESS_TOKEN triggers VertexGeminiClient
        with patch.dict(os.environ, {"GCP_ACCESS_TOKEN": "ya29.fake-token"}, clear=True):
            self.assertIsInstance(create_client(client_type="auto"), VertexGeminiClient)

        # 10. Clean environment falls back to MockClient
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(create_client(client_type="auto"), MockClient)

    def test_get_client_alias_equivalence(self):
        """Verify get_client is an exact alias for create_client."""
        self.assertIs(get_client, create_client)
        c = get_client(client_type="mock", model="custom-mock")
        self.assertIsInstance(c, MockClient)
        self.assertEqual(c.default_model, "custom-mock")


class TestChallengerModelPayloadAndFormatAdversarial(unittest.TestCase):
    """Adversarial testing of request payload assembly, headers, and TokenUsage parsing."""

    @patch("subprocess.check_output", return_value="test-token-xyz\n")
    @patch("urllib.request.urlopen")
    def test_gemini_request_headers_and_json_payload(self, mock_urlopen, mock_subp):
        """VertexGeminiClient properly sets Bearer Authorization and json_output MIME type."""
        captured_requests = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            resp = MagicMock()
            resp.read.return_value = json.dumps({
                "candidates": [{"content": {"parts": [{"text": '{"result": 100}'}]}}],
                "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10, "cachedContentTokenCount": 5},
            }).encode("utf-8")
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp

        mock_urlopen.side_effect = fake_urlopen

        with patch.dict(os.environ, {}, clear=True):
            client = VertexGeminiClient(project_id="my-proj", location="us-central1")
            res = client.generate_json("Generate structured payload", temperature=0.7, max_tokens=1024)

            self.assertEqual(res, {"result": 100})
            self.assertEqual(len(captured_requests), 1)
            req = captured_requests[0]
            self.assertEqual(req.get_header("Authorization"), "Bearer test-token-xyz")
            self.assertEqual(req.get_header("Content-type"), "application/json")

        req_body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(req_body["generationConfig"]["temperature"], 0.7)
        self.assertEqual(req_body["generationConfig"]["maxOutputTokens"], 1024)
        self.assertEqual(req_body["generationConfig"]["responseMimeType"], "application/json")

    @patch("urllib.request.urlopen")
    def test_gemma_openai_request_payload_and_json_format(self, mock_urlopen):
        """ModelGardenGemmaClient sends response_format={"type": "json_object"} when targeting /v1/ endpoints with json_output=True."""
        captured_requests = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            resp = MagicMock()
            resp.read.return_value = json.dumps({
                "choices": [{"message": {"content": '{"score": 8.5}'}}],
                "usage": {"prompt_tokens": "12", "completion_tokens": "6", "total_tokens": "18"},
            }).encode("utf-8")
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp

        mock_urlopen.side_effect = fake_urlopen

        client = ModelGardenGemmaClient(
            endpoint_url="https://vllm-service:8000/v1/chat/completions",
            api_key="secret-api-key",
        )
        res = client.generate("Evaluate with JSON", json_output=True)

        self.assertEqual(res.json(), {"score": 8.5})
        self.assertEqual(res.usage.prompt_tokens, 12)
        self.assertEqual(res.usage.completion_tokens, 6)
        self.assertEqual(res.usage.total_tokens, 18)

        req_body = json.loads(captured_requests[0].data.decode("utf-8"))
        self.assertEqual(req_body["response_format"], {"type": "json_object"})
        self.assertEqual(captured_requests[0].get_header("Authorization"), "Bearer secret-api-key")

    def test_token_usage_edge_cases(self):
        """TokenUsage handles empty dicts, string ints, and Vertex vs OpenAI field aliases."""
        # 1. Empty dict
        u_empty = TokenUsage.from_dict({})
        self.assertEqual(u_empty.prompt_tokens, 0)
        self.assertEqual(u_empty.completion_tokens, 0)
        self.assertEqual(u_empty.total_tokens, 0)
        self.assertIsNone(u_empty.cached_tokens)

        # 2. String integers
        u_str = TokenUsage.from_dict({
            "prompt_tokens": "50",
            "completion_tokens": "25",
            "total_tokens": "75",
            "cached_tokens": "10",
        })
        self.assertEqual(u_str.prompt_tokens, 50)
        self.assertEqual(u_str.completion_tokens, 25)
        self.assertEqual(u_str.total_tokens, 75)
        self.assertEqual(u_str.cached_tokens, 10)

        # 3. Vertex AI camelCase field names
        u_vertex = TokenUsage.from_dict({
            "promptTokenCount": 100,
            "candidatesTokenCount": 50,
            "totalTokenCount": 150,
            "cachedContentTokenCount": 20,
        })
        self.assertEqual(u_vertex.prompt_tokens, 100)
        self.assertEqual(u_vertex.completion_tokens, 50)
        self.assertEqual(u_vertex.total_tokens, 150)
        self.assertEqual(u_vertex.cached_tokens, 20)

    def test_llm_response_serialization_and_helpers(self):
        """LLMResponse properties, string formatting, and dict serialization."""
        resp = LLMResponse(
            text='{"status": "ok"}',
            model="gemini-2.5-pro",
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            latency_ms=150.25,
            finish_reason="stop",
            metadata={"source": "test"},
        )
        self.assertEqual(resp.content, '{"status": "ok"}')
        self.assertEqual(str(resp), '{"status": "ok"}')
        self.assertEqual(resp.json(), {"status": "ok"})

        d = resp.to_dict()
        self.assertEqual(d["model"], "gemini-2.5-pro")
        self.assertEqual(d["latency_ms"], 150.25)
        self.assertEqual(d["usage"]["total_tokens"], 10)


if __name__ == "__main__":
    unittest.main()
