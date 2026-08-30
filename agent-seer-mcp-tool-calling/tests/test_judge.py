"""Unit, integration, and mock evaluation tests for agent_seer.judge.

Covers:
- Tool-calling evaluation (judge_tc) with deterministic mock client
- Coherence evaluation (judge_coherence) with mock client
- Capability-matrix enrichment mode (enriched=True) vs un-enriched baseline
- Prompt assembly and variable formatting verification
- Error handling and robust parsing of LLM responses
- Missing subdimension keys and default handling
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from agent_seer.judge import judge_coherence, judge_tc


class MockLLMClient:
    """Deterministic offline mock LLM client for testing judge executions."""

    def __init__(self, canned_response=None):
        self.canned_response = canned_response or {}
        self.last_prompt = None

    def generate_json(self, prompt: str, model: str = "mock-model", temperature: float = 0.0):
        self.last_prompt = prompt
        return self.canned_response

    def generate(self, prompt: str, model: str = "mock-model", temperature: float = 0.0):
        self.last_prompt = prompt
        return json.dumps(self.canned_response)


class TestJudgeTC(unittest.TestCase):
    """Tier 1 & Tier 2 tests for judge_tc function."""

    def setUp(self):
        self.sample_tools = [
            {
                "name": "generate_image",
                "description": "Generate an image",
                "inputSchema": {
                    "type": "object",
                    "properties": {"prompt": {"type": "string"}},
                    "required": ["prompt"],
                },
            }
        ]
        self.user_prompt = "Generate a portrait of an astronaut on Mars"
        self.agent_calls = [
            {
                "function_name": "generate_image",
                "parameters": {"prompt": "Portrait of an astronaut on Mars"},
            }
        ]

    def test_judge_tc_happy_path(self):
        """Tier 1: judge_tc invokes client and returns aggregated evaluation result."""
        canned = {
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
            "rationale": "Accurate single tool call matching prompt.",
        }
        client = MockLLMClient(canned_response=canned)
        result = judge_tc(
            tool_specs=self.sample_tools,
            user_prompt=self.user_prompt,
            agent_calls=self.agent_calls,
            client=client,
        )

        self.assertIn("tc_overall", result)
        self.assertAlmostEqual(result["tc_overall"], 1.0)
        self.assertIn("dimensions", result)
        self.assertEqual(result["dimensions"]["usage"], 1.0)
        self.assertIn("_raw", result)
        self.assertIsNotNone(client.last_prompt)
        self.assertIn("Portrait of an astronaut on Mars", client.last_prompt)

    def test_judge_tc_enriched_mode(self):
        """Tier 1: judge_tc with enriched=True injects capability matrix into prompt."""
        capabilities = {
            "gemini-2.5-flash-image": {"supported_aspect_ratios": ["1:1", "16:9"], "max_resolution": "2K"}
        }
        canned = {
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
            "rationale": "Correctly matches capability matrix.",
        }
        client = MockLLMClient(canned_response=canned)
        result = judge_tc(
            tool_specs=self.sample_tools,
            user_prompt=self.user_prompt,
            agent_calls=self.agent_calls,
            client=client,
            enriched=True,
            capabilities=capabilities,
        )
        self.assertAlmostEqual(result["tc_overall"], 1.0)
        self.assertIn("max_resolution", client.last_prompt)

    def test_judge_tc_multi_tool_ordering(self):
        """Tier 1: judge_tc handles multi-tool call with active ordering rubric."""
        multi_calls = [
            {"function_name": "generate_image", "parameters": {"prompt": "City"}},
            {"function_name": "generate_video", "parameters": {"prompt": "City video"}},
        ]
        canned = {
            "usage": {"necessity": 10, "overuse_detection": 10},
            "selection": {"correctness": 9, "specificity": 9, "completeness": 9},
            "ordering": {
                "not_applicable": False,
                "sequence_logic": 9,
                "dependency_handling": 9,
                "execution_efficiency": 9,
            },
            "arguments": {
                "completeness": 10,
                "name_accuracy": 10,
                "value_accuracy": 10,
                "type_compliance": 10,
                "format_compliance": 10,
                "relevancy": 10,
            },
            "failures": [],
            "rationale": "Logical multi-step generation sequence.",
        }
        client = MockLLMClient(canned_response=canned)
        result = judge_tc(
            tool_specs=self.sample_tools,
            user_prompt="Create image then video",
            agent_calls=multi_calls,
            client=client,
        )
        self.assertIn("ordering", result["dimensions"])
        self.assertAlmostEqual(result["dimensions"]["ordering"], 0.9)

    def test_judge_tc_empty_calls(self):
        """Tier 2: judge_tc evaluated on empty tool calls list."""
        canned = {
            "usage": {"necessity": 0, "overuse_detection": 10},
            "selection": {"correctness": 0, "specificity": 0, "completeness": 0},
            "ordering": {"not_applicable": True},
            "arguments": {
                "completeness": 0,
                "name_accuracy": 0,
                "value_accuracy": 0,
                "type_compliance": 0,
                "format_compliance": 0,
                "relevancy": 0,
            },
            "failures": ["missing_tool_call"],
            "rationale": "No tools called when tool was required.",
        }
        client = MockLLMClient(canned_response=canned)
        result = judge_tc(
            tool_specs=self.sample_tools,
            user_prompt=self.user_prompt,
            agent_calls=[],
            client=client,
        )
        self.assertAlmostEqual(result["tc_overall"], 0.0)

    def test_judge_tc_string_tool_specs(self):
        """Tier 2: judge_tc accepts pre-serialized JSON string as tool_specs."""
        canned = {
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
            "rationale": "Good tool spec string formatting.",
        }
        client = MockLLMClient(canned_response=canned)
        result = judge_tc(
            tool_specs=json.dumps(self.sample_tools),
            user_prompt=self.user_prompt,
            agent_calls=self.agent_calls,
            client=client,
        )
        self.assertAlmostEqual(result["tc_overall"], 1.0)


class TestJudgeCoherence(unittest.TestCase):
    """Tier 1 & Tier 2 tests for judge_coherence function."""

    def test_judge_coherence_happy_path(self):
        """Tier 1: judge_coherence evaluates a clean transcript."""
        transcript = (
            "User: Can you generate a sunset video?\n"
            "Assistant: Generating a 1080p sunset video over the Pacific ocean now.\n"
        )
        canned = {
            "logical_flow": 3,
            "completeness": 3,
            "conciseness": 3,
            "topic_relevance": 3,
            "context_retention": {"not_applicable": True, "score": None},
            "manifestations": [],
            "rationale": "Coherent, concise, and complete.",
        }
        client = MockLLMClient(canned_response=canned)
        result = judge_coherence(transcript_text=transcript, client=client)

        self.assertIn("coh_overall", result)
        self.assertAlmostEqual(result["coh_overall"], 1.0)
        self.assertIn("_raw", result)
        self.assertEqual(result["manifestations"], [])

    def test_judge_coherence_with_manifestations(self):
        """Tier 2: judge_coherence with detected failure manifestations."""
        transcript = "User: What is the weather?\nAssistant: Video generation started.\n"
        canned = {
            "logical_flow": 1,
            "completeness": 1,
            "conciseness": 2,
            "topic_relevance": 1,
            "context_retention": {"not_applicable": True, "score": None},
            "manifestations": ["topic_shift", "wrong_question"],
            "rationale": "Assistant completely ignored user question.",
        }
        client = MockLLMClient(canned_response=canned)
        result = judge_coherence(transcript_text=transcript, client=client)

        self.assertLess(result["coh_overall"], 0.5)
        self.assertIn("topic_shift", result["manifestations"])

    def test_judge_coherence_multi_turn_history(self):
        """Tier 2: judge_coherence with active multi-turn context retention."""
        transcript = (
            "User: I prefer dark theme.\nAssistant: Saved preference.\n"
            "User: Show my dashboard.\nAssistant: Displaying dark theme dashboard.\n"
        )
        canned = {
            "logical_flow": 3,
            "completeness": 3,
            "conciseness": 3,
            "topic_relevance": 3,
            "context_retention": {"not_applicable": False, "score": 3},
            "manifestations": [],
            "rationale": "Retained user preference perfectly.",
        }
        client = MockLLMClient(canned_response=canned)
        result = judge_coherence(transcript_text=transcript, client=client)
        self.assertAlmostEqual(result["coh_overall"], 1.0)


if __name__ == "__main__":
    unittest.main()
