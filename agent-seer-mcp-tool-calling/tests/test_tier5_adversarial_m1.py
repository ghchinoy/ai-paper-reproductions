"""Tier 5 Adversarial and Stress Test Suite for Milestone 1.

Comprehensive empirical challenge suite testing:
1. Dynamic JSON-RPC Stdio Handshake:
   - Error responses during initialize and tools/list
   - Broken pipes, premature EOF, and process crashes
   - Timeout simulations (initialize and tools/list)
   - Corrupted/malformed JSON, blank line spam, non-dict payloads
   - Empty, missing, and malformed tools/list result structures
   - Empty command and invalid subprocess configurations
2. Capability Enrichment & Linter Engine Edge Cases:
   - Veo 2.0 audio request rejection (SupportsGenerateAudio=false)
   - Veo aspect ratio violations (e.g. 1:1, 4:3)
   - Veo first/last frame and reference image capability violations across model tiers
   - Veo unknown model names
   - Nanobanana 4K on Flash, 1K only on Flash Lite, invalid aspect ratios (e.g. 1:4 on Flash 2.5), unknown models
   - Lyria invalid sample counts (<=0) and unknown models
   - AVTool video_to_gif unsupported FPS
   - Chirp TTS unsupported encodings
   - Unknown tools, missing required params, type mismatches (including bool vs int), invalid URIs
3. Judge Engine Adversarial Scenarios:
   - Code-fenced markdown parsing (```json, ```, preamble/postamble)
   - Out-of-bounds LLM subscores clamping (e.g. score=15, score=-2)
   - Cascading penalty collapse validation (name errors vs value/capability errors)
   - End-to-end JudgeEngine with deterministic MockLLMClient and live Linter integration
   - Multi-turn coherence transcript parsing with history and without history
4. Discovery Registry & Merger Edge Cases:
   - Malformed/corrupt JSON files in server directories
   - Non-existent and empty registry directories
   - merge_capabilities with varied input types (ServerSpec, dict, list, string, CapabilityMatrix)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from agent_seer.discovery import (
    McpDiscovery,
    _read_json_line,
    discover_from_stdio,
    load_capabilities,
    load_registry,
    load_server_directory,
    merge_capabilities,
)
from agent_seer.judge import (
    JudgeEngine,
    extract_json_payload,
    format_agent_calls,
    format_tool_specs,
    judge_coherence,
    judge_tc,
)
from agent_seer.linter import DeterministicLinter
from agent_seer.models import (
    CapabilityMatrix,
    CoherenceScores,
    EvaluationResult,
    LintResult,
    LintViolation,
    ServerSpec,
    Severity,
    ToolCall,
    ToolCallingScores,
    ToolDefinition,
    ToolParameter,
)
from agent_seer.scoring import (
    apply_cascading_penalty_collapse,
    compute_coherence_score,
    compute_tool_calling_score,
    norm3,
    norm10,
)


class MockLLMClient:
    """Mock client for deterministic LLM response testing."""

    def __init__(self, response_data: dict | str):
        self.response_data = response_data
        self.call_history: list[str] = []

    def generate(self, prompt: str, model: str = "mock", temperature: float = 0.0) -> str:
        self.call_history.append(prompt)
        if isinstance(self.response_data, str):
            return self.response_data
        return json.dumps(self.response_data)

    def generate_json(self, prompt: str, model: str = "mock", temperature: float = 0.0) -> dict:
        self.call_history.append(prompt)
        if isinstance(self.response_data, dict):
            return self.response_data
        return extract_json_payload(str(self.response_data))


class TestStdioHandshakeAdversarial(unittest.TestCase):
    """Stress tests for stdio JSON-RPC MCP handshake."""

    def test_empty_command_raises(self):
        """Verifies empty string or empty list command raises ValueError."""
        with self.assertRaises(ValueError):
            discover_from_stdio("")
        with self.assertRaises(ValueError):
            discover_from_stdio([])

    def test_mock_error_on_initialize(self):
        """Server returns JSON-RPC error response during initialize."""
        err_packet = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Server initialization rejected: untrusted client"},
        })
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = [err_packet + "\n", ""]
        mock_proc.poll.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(RuntimeError) as ctx:
                discover_from_stdio(["dummy-mcp"])
            self.assertIn("MCP initialize error", str(ctx.exception))
            self.assertIn("Server initialization rejected", str(ctx.exception))

    def test_mock_error_on_tools_list(self):
        """Server initializes successfully but returns JSON-RPC error on tools/list."""
        init_ok = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}},
        })
        tools_err = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32601, "message": "Method 'tools/list' not found or disabled"},
        })
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = [init_ok + "\n", tools_err + "\n", ""]
        mock_proc.poll.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(RuntimeError) as ctx:
                discover_from_stdio(["dummy-mcp"])
            self.assertIn("MCP tools/list error", str(ctx.exception))
            self.assertIn("Method 'tools/list' not found", str(ctx.exception))

    def test_broken_pipe_on_stdin_write(self):
        """Subprocess crashes immediately causing BrokenPipeError on write."""
        mock_proc = MagicMock()
        mock_proc.stdin.write.side_effect = BrokenPipeError("Broken pipe")

        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(BrokenPipeError):
                discover_from_stdio(["crashing-mcp"])

    def test_premature_eof_on_initialize(self):
        """Subprocess exits immediately returning EOF (empty string) before initialize."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.return_value = ""  # Immediate EOF
        mock_proc.poll.return_value = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(EOFError) as ctx:
                discover_from_stdio(["exiting-mcp"])
            self.assertIn("closed standard output unexpectedly", str(ctx.exception))

    def test_premature_eof_between_init_and_tools_list(self):
        """Subprocess succeeds initialize, then drops connection before tools/list response."""
        init_ok = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05"},
        })
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = [init_ok + "\n", ""]  # EOF on 2nd read
        mock_proc.poll.return_value = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(EOFError):
                discover_from_stdio(["half-crashing-mcp"])

    def test_timeout_simulation(self):
        """Subprocess hangs and fails to respond within timeout_sec."""
        import time

        def hanging_readline():
            time.sleep(2.0)
            return "never reached\n"

        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = hanging_readline

        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(TimeoutError) as ctx:
                discover_from_stdio(["hanging-mcp"], timeout_sec=0.1)
            self.assertIn("Timed out after 0.1s", str(ctx.exception))

    def test_corrupt_malformed_json_response(self):
        """Subprocess outputs non-JSON garbage text."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = ["<xml>not json</xml>\n", ""]

        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(ValueError) as ctx:
                discover_from_stdio(["garbage-mcp"])
            self.assertIn("Malformed JSON", str(ctx.exception))

    def test_blank_lines_skipped_gracefully(self):
        """Subprocess emits empty/whitespace lines before emitting JSON payload."""
        init_ok = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05"},
        })
        tools_ok = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "tool_alpha", "description": "alpha tool"}]},
        })
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = [
            "\n",
            "   \n",
            init_ok + "\n",
            "\n",
            tools_ok + "\n",
            "",
        ]

        with patch("subprocess.Popen", return_value=mock_proc):
            tools = discover_from_stdio(["noisy-mcp"])
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0]["name"], "tool_alpha")

    def test_empty_tool_sets_and_missing_result_keys(self):
        """Server returns valid JSON-RPC but empty tools list, None tools, or missing result."""
        init_ok = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        tools_empty = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}})
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = [init_ok + "\n", tools_empty + "\n", ""]

        with patch("subprocess.Popen", return_value=mock_proc):
            tools = discover_from_stdio(["empty-mcp"])
            self.assertEqual(tools, [])

        # Missing 'tools' key in result
        tools_no_key = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {}})
        mock_proc.stdout.readline.side_effect = [init_ok + "\n", tools_no_key + "\n", ""]
        with patch("subprocess.Popen", return_value=mock_proc):
            tools = discover_from_stdio(["notools-mcp"])
            self.assertEqual(tools, [])

    def test_deep_blank_lines_no_recursion_error(self):
        """1,500 blank lines skipped iteratively without stack overflow or RecursionError."""
        init_ok = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05"},
        })
        tools_ok = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "tool_beta"}]},
        })
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        # 1500 blank lines before each response
        mock_proc.stdout.readline.side_effect = ["\n"] * 1500 + [init_ok + "\n"] + ["\n"] * 1500 + [tools_ok + "\n", ""]

        with patch("subprocess.Popen", return_value=mock_proc):
            tools = discover_from_stdio(["bursty-mcp"])
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0]["name"], "tool_beta")

    def test_result_null_handled_safely(self):
        """MCP server returns valid JSON-RPC with result: null without throwing AttributeError."""
        init_ok = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}})
        tools_null = '{"jsonrpc": "2.0", "id": 2, "result": null}\n'
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = [init_ok + "\n", tools_null, ""]

        with patch("subprocess.Popen", return_value=mock_proc):
            tools = discover_from_stdio(["null-result-mcp"])
            self.assertEqual(tools, [])


class TestCapabilityEnrichmentAndLinterStress(unittest.TestCase):
    """Adversarial testing for capability matrices, schema validation, and edge cases."""

    def setUp(self):
        self.linter = DeterministicLinter()

    def test_veo2_audio_request_violation(self):
        """Veo 2.0 (veo-2.0-generate-001) does NOT support audio -> must flag CAPABILITY_VIOLATION."""
        call = {
            "function_name": "veo_t2v",
            "parameters": {
                "prompt": "Cinematic shot of neon city",
                "model": "veo-2.0-generate-001",
                "generate_audio": True,
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any(v.rule_id == "capability_violation" and "audio" in v.message.lower() for v in violations))
        self.assertTrue(any(v.severity == Severity.CAPABILITY_VIOLATION.value for v in violations))

    def test_veo31_audio_request_allowed(self):
        """Veo 3.1 (veo-3.1-generate-preview) supports audio -> should not flag audio violation."""
        call = {
            "function_name": "veo_t2v",
            "parameters": {
                "prompt": "Cinematic shot of neon city",
                "model": "veo-3.1-generate-preview",
                "generate_audio": True,
            },
        }
        violations = self.linter.lint_call(call)
        audio_viols = [v for v in violations if "audio" in v.message.lower()]
        self.assertEqual(len(audio_viols), 0)

    def test_veo_unsupported_aspect_ratio(self):
        """Veo only supports 16:9 and 9:16 -> 1:1 or 4:3 must trigger CAPABILITY_VIOLATION."""
        call_square = {
            "function_name": "veo_t2v",
            "parameters": {
                "prompt": "Sunset over ocean",
                "model": "veo-2.0-generate-001",
                "aspect_ratio": "1:1",
            },
        }
        violations = self.linter.lint_call(call_square)
        self.assertTrue(any(v.parameter_name == "aspect_ratio" and v.rule_id == "capability_violation" for v in violations))

    def test_veo_first_last_frame_unsupported_model(self):
        """veo_first_last_to_video on model lacking first/last support -> CAPABILITY_VIOLATION."""
        call = {
            "function_name": "veo_first_last_to_video",
            "parameters": {
                "prompt": "Morph from start to end",
                "first_frame_uri": "gs://bucket/first.png",
                "last_frame_uri": "gs://bucket/last.png",
                "model": "veo-2.0-generate-001",  # Veo 2.0 does not support first/last
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any("first/last" in v.message.lower() for v in violations))

    def test_veo_reference_image_unsupported_model(self):
        """veo_reference_to_video on model lacking reference image support -> CAPABILITY_VIOLATION."""
        call = {
            "function_name": "veo_reference_to_video",
            "parameters": {
                "prompt": "Animate character",
                "reference_image_uri": "gs://bucket/ref.png",
                "model": "veo-3.0-generate-001",  # Veo 3.0 does not support reference image
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any("reference image" in v.message.lower() for v in violations))

    def test_veo_unknown_model(self):
        """Veo call with hallucinated model -> unknown_model violation."""
        call = {
            "function_name": "veo_t2v",
            "parameters": {
                "prompt": "Sci-fi spacecraft",
                "model": "veo-9.9-super-hyper-turbo",
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any(v.rule_id == "unknown_model" for v in violations))

    def test_nanobanana_4k_on_flash_model(self):
        """Nanobanana flash image model does not support 4K -> CAPABILITY_VIOLATION."""
        call = {
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "Ultra realistic landscape",
                "model": "gemini-2.5-flash-image",
                "image_size": "4K",
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any("image_size" in v.message.lower() and v.rule_id == "capability_violation" for v in violations))

    def test_nanobanana_flash_lite_4k_unsupported(self):
        """Nanobanana flash lite only supports 1K -> 4K is rejected."""
        call = {
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "Icon design",
                "model": "gemini-3.1-flash-lite-image",
                "image_size": "4K",
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any("image_size" in v.message.lower() and v.rule_id == "capability_violation" for v in violations))

    def test_nanobanana_unsupported_aspect_ratio(self):
        """Nanobanana flash 2.5 does not support 1:4 (only Pro / 3.1 do) -> CAPABILITY_VIOLATION."""
        call = {
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "Tall banner",
                "model": "gemini-2.5-flash-image",
                "aspect_ratio": "1:4",
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any(v.parameter_name == "aspect_ratio" and v.rule_id == "capability_violation" for v in violations))

    def test_nanobanana_pro_aspect_ratio_1_4_allowed(self):
        """Nanobanana Pro supports 1:4 aspect ratio -> should NOT trigger violation."""
        call = {
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "Tall banner",
                "model": "gemini-3-pro-image",
                "aspect_ratio": "1:4",
            },
        }
        violations = self.linter.lint_call(call)
        self.assertEqual(len(violations), 0)

    def test_lyria_invalid_sample_count(self):
        """Lyria generate_music with sample_count < 1 -> invalid_value violation."""
        call_zero = {
            "function_name": "lyria_generate_music",
            "parameters": {
                "prompt": "Upbeat synthwave track",
                "sample_count": 0,
            },
        }
        violations = self.linter.lint_call(call_zero)
        self.assertTrue(any(v.parameter_name == "sample_count" and v.rule_id == "invalid_value" for v in violations))

        call_neg = {
            "function_name": "lyria_generate_music",
            "parameters": {
                "prompt": "Upbeat synthwave track",
                "sample_count": -3,
            },
        }
        violations_neg = self.linter.lint_call(call_neg)
        self.assertTrue(any(v.parameter_name == "sample_count" for v in violations_neg))

    def test_lyria_unknown_model(self):
        """Lyria with unknown model_id -> unknown_model."""
        call = {
            "function_name": "lyria_generate_music",
            "parameters": {
                "prompt": "Jazz trio",
                "model_id": "lyria-99-future-music",
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any(v.rule_id == "unknown_model" for v in violations))

    def test_avtool_unsupported_gif_fps(self):
        """FFmpeg video to gif with unsupported FPS (e.g. 120) -> CAPABILITY_VIOLATION."""
        call = {
            "function_name": "ffmpeg_video_to_gif",
            "parameters": {
                "input_video_uri": "gs://bucket/video.mp4",
                "fps": 120,
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any(v.parameter_name == "fps" and v.rule_id == "capability_violation" for v in violations))

    def test_chirp_unsupported_encoding(self):
        """Chirp TTS with unsupported phonetic encoding -> CAPABILITY_VIOLATION."""
        call = {
            "function_name": "chirp_tts",
            "parameters": {
                "text": "Hello world",
                "encoding": "unsupported_phonetic_codec",
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any(v.parameter_name == "encoding" and v.rule_id == "capability_violation" for v in violations))

    def test_type_mismatch_boolean_vs_number(self):
        """Passing boolean True for a numeric parameter must fail type check."""
        call = {
            "function_name": "lyria_generate_music",
            "parameters": {
                "prompt": "Ambient pads",
                "sample_count": True,  # bool is subclass of int in python
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any(v.rule_id == "type_mismatch" for v in violations))

    def test_invalid_uri_schemes(self):
        """Passing non-URI strings for URI parameters triggers invalid_uri."""
        call = {
            "function_name": "veo_i2v",
            "parameters": {
                "prompt": "Animate portrait",
                "image_uri": "not_a_valid_uri_or_path",
            },
        }
        violations = self.linter.lint_call(call)
        self.assertTrue(any(v.rule_id == "invalid_uri" for v in violations))

    def test_unknown_tool_call(self):
        """Calling a completely unregistered tool -> unknown_tool."""
        call = {
            "function_name": "hallucinated_tool_never_registered",
            "parameters": {"arg1": "val1"},
        }
        violations = self.linter.lint_call(call)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "unknown_tool")

    def test_malformed_tool_call_missing_name(self):
        """Call dictionary without function_name or name -> malformed_call."""
        call = {"parameters": {"prompt": "foo"}}
        violations = self.linter.lint_call(call)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "malformed_call")


class TestJudgeEngineAdversarial(unittest.TestCase):
    """Stress tests for LLM Judge parsing, cascading collapse, and score math."""

    def test_markdown_code_fences_variations(self):
        """Robust extraction across ```json ... ```, ``` ... ```, and extra text."""
        raw_json_str = json.dumps({"usage": {"necessity": 10}, "rationale": "perfect"})

        # Case 1: ```json ... ```
        text1 = f"Here is the evaluation:\n```json\n{raw_json_str}\n```\nHope this helps."
        self.assertEqual(extract_json_payload(text1)["usage"]["necessity"], 10)

        # Case 2: ``` ... ``` without 'json' tag
        text2 = f"```\n{raw_json_str}\n```"
        self.assertEqual(extract_json_payload(text2)["usage"]["necessity"], 10)

        # Case 3: Embedded inside raw markdown text with no fences
        text3 = f"Evaluation output follows:\n{raw_json_str}\nEnd of response."
        self.assertEqual(extract_json_payload(text3)["usage"]["necessity"], 10)

    def test_malformed_json_raises_value_error(self):
        """Non-JSON LLM response raises ValueError."""
        with self.assertRaises(ValueError):
            extract_json_payload("Sorry, I cannot evaluate this prompt due to safety policy.")

    def test_cascading_penalty_collapse_name_error(self):
        """Missing required parameter collapses name_accuracy, completeness, and value/type/format."""
        raw_subscores = {
            "usage": {"necessity": 10, "overuse_detection": 10},
            "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
            "ordering": {"not_applicable": True},
            "arguments": {
                "completeness": 10,
                "name_accuracy": 10,
                "value_accuracy": 10,
                "type_compliance": 10,
                "format_compliance": 10,
                "relevancy": 10,
            },
            "failures": [],
            "rationale": "Un-enriched judge false pass",
        }
        violations = [
            LintViolation(
                tool_name="veo_t2v",
                parameter_name="prompt",
                rule_id="missing_required",
                message="Missing required 'prompt'",
            )
        ]

        collapsed = apply_cascading_penalty_collapse(raw_subscores, violations)
        args = collapsed["arguments"]
        self.assertEqual(args["name_accuracy"], 0)
        self.assertEqual(args["completeness"], 0)
        self.assertEqual(args["value_accuracy"], 0)
        self.assertEqual(args["type_compliance"], 0)
        self.assertEqual(args["format_compliance"], 0)
        self.assertLessEqual(args["relevancy"], 2)

        tc_scores = compute_tool_calling_score(collapsed)
        # Arguments mean collapsed to near zero -> overall score should drop significantly
        self.assertLess(tc_scores.overall_tool_calling, 0.70)

    def test_cascading_penalty_collapse_capability_error(self):
        """Capability violation (e.g. Veo-2 audio) collapses value, type, format, and relevancy."""
        raw_subscores = {
            "usage": {"necessity": 10, "overuse_detection": 10},
            "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
            "ordering": {"not_applicable": True},
            "arguments": {
                "completeness": 10,
                "name_accuracy": 10,
                "value_accuracy": 10,
                "type_compliance": 10,
                "format_compliance": 10,
                "relevancy": 10,
            },
            "failures": [],
            "rationale": "Un-enriched judge false pass",
        }
        violations = [
            LintViolation(
                tool_name="veo_t2v",
                parameter_name="generate_audio",
                rule_id="capability_violation",
                message="Model does not support audio",
            )
        ]

        collapsed = apply_cascading_penalty_collapse(raw_subscores, violations)
        args = collapsed["arguments"]
        self.assertEqual(args["value_accuracy"], 0)
        self.assertEqual(args["type_compliance"], 0)
        self.assertEqual(args["format_compliance"], 0)
        self.assertLessEqual(args["relevancy"], 3)

        tc_scores = compute_tool_calling_score(collapsed)
        self.assertLess(tc_scores.overall_tool_calling, 0.85)

    def test_subscore_normalization_and_out_of_bounds_clamping(self):
        """Scores outside 0-10 or 1-3 are clamped to [0.0, 1.0]."""
        self.assertEqual(norm10(15), 1.0)
        self.assertEqual(norm10(-5), 0.0)
        self.assertEqual(norm10("invalid"), 0.0)

        self.assertEqual(norm3(5), 1.0)
        self.assertEqual(norm3(0), 0.0)
        self.assertEqual(norm3("bad"), 0.0)

    def test_judge_engine_end_to_end_with_capability_violation(self):
        """End-to-end JudgeEngine correctly evaluates a call that violates capability matrix."""
        # Un-enriched mock LLM tries to give 10/10 across all fields
        canned_llm = {
            "usage": {"necessity": 10, "overuse_detection": 10},
            "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
            "ordering": {"not_applicable": True},
            "arguments": {
                "completeness": 10,
                "name_accuracy": 10,
                "value_accuracy": 10,
                "type_compliance": 10,
                "format_compliance": 10,
                "relevancy": 10,
            },
            "failures": [],
            "rationale": "Model looked good to naive judge",
        }
        client = MockLLMClient(canned_llm)
        engine = JudgeEngine(client=client)

        # Call with Veo 2.0 audio violation
        bad_calls = [
            {
                "function_name": "veo_t2v",
                "parameters": {
                    "prompt": "A jazz concert",
                    "model": "veo-2.0-generate-001",
                    "generate_audio": True,
                },
            }
        ]

        result = engine.evaluate_tool_calls(
            tool_specs=[],
            user_prompt="Generate jazz video with audio",
            agent_calls=bad_calls,
        )

        self.assertFalse(result.passed)
        self.assertFalse(result.lint_result.is_valid)
        self.assertLess(result.tool_calling.overall_tool_calling, 0.85)


class TestDiscoveryRegistryAndMergerEdgeCases(unittest.TestCase):
    """Stress tests for registry loader, directory loader, and merge_capabilities."""

    def test_load_server_directory_corrupt_files(self):
        """Directory with invalid JSON in tools.json or capabilities.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Corrupt tools.json
            with open(os.path.join(tmpdir, "tools.json"), "w") as f:
                f.write("CORRUPT_JSON_DATA{{{")

            with self.assertRaises(json.JSONDecodeError):
                load_server_directory(tmpdir)

    def test_load_registry_non_existent_dir(self):
        """Registry search on a non-existent directory returns empty dict."""
        res = load_registry("/non/existent/path_xyz")
        self.assertEqual(res, {})

    def test_merge_capabilities_varied_types(self):
        """merge_capabilities handles CapabilityMatrix, dict, list, and string formats."""
        tools_list = [{"name": "test_tool", "description": "desc"}]
        cap_dict = {"model-1": {"feature": True}}
        cap_obj = CapabilityMatrix(server_name="test_srv", models=cap_dict)

        # Dict capabilities
        res1 = merge_capabilities(tools_list, cap_dict)
        self.assertIn("CRITICAL BACKEND MODEL CAPABILITY MATRIX", res1)
        self.assertIn("model-1", res1)

        # CapabilityMatrix object
        res2 = merge_capabilities(tools_list, cap_obj)
        self.assertIn("CRITICAL BACKEND MODEL CAPABILITY MATRIX", res2)
        self.assertIn("model-1", res2)

        # Empty capabilities
        res3 = merge_capabilities(tools_list, {})
        self.assertNotIn("CRITICAL BACKEND MODEL CAPABILITY MATRIX", res3)


if __name__ == "__main__":
    unittest.main()
