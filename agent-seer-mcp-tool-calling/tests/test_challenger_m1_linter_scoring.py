"""Empirical Challenger Test & Stress Suite for Milestone 1.

Author: Challenger 1 (Milestone 1)
Project: Agent Seer Production Uplift
Modules under test:
- `src/agent_seer/linter.py` (DeterministicLinter)
- `src/agent_seer/scoring.py` (Mathematical Scoring Engine)
"""
import copy
import math
import os
import sys
import time
import unittest
from typing import Any, Dict, List

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from agent_seer.linter import DeterministicLinter
from agent_seer.models import (
    CapabilityMatrix,
    CoherenceScores,
    LintResult,
    LintViolation,
    Severity,
    ToolCall,
    ToolCallingScores,
    ToolDefinition,
    ToolParameter,
)
from agent_seer.scoring import (
    aggregate_coherence,
    aggregate_tc,
    apply_cascading_penalty_collapse,
    compute_coherence_score,
    compute_tool_calling_score,
    norm3,
    norm10,
)


class TestEmpiricalChallengerFindings(unittest.TestCase):
    """Demonstrates and empirically confirms specific bugs and edge cases."""

    def setUp(self):
        self.spike_servers_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "spike", "servers")
        )
        self.tools = [
            {
                "name": "generate_image",
                "description": "Image generator",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "aspect_ratio": {"type": "string", "enum": ["1:1", "16:9", "9:16"]},
                        "seed": {"type": "number"},
                        "hd": {"type": "boolean"},
                        "tags": {"type": "array"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["prompt"],
                },
            }
        ]
        self.linter = DeterministicLinter(
            tools=self.tools,
            servers_dir=self.spike_servers_dir if os.path.exists(self.spike_servers_dir) else None,
        )

    def test_bug1_enum_unhashable_type_crash(self):
        """BUG 1: Passing unhashable type (list, dict, set) for enum parameter is safely flagged as illegal_enum."""
        bad_call = {
            "function_name": "generate_image",
            "parameters": {
                "prompt": "test prompt",
                "aspect_ratio": ["16:9"],  # List is unhashable
            },
        }
        violations = self.linter.lint_call(bad_call)
        self.assertTrue(any(v.rule_id == "illegal_enum" and v.parameter_name == "aspect_ratio" for v in violations))

    def test_bug2_unhashable_tool_name_crash(self):
        """BUG 2: Passing unhashable function_name (e.g. list, dict) is safely flagged as malformed_call."""
        bad_call = {
            "function_name": ["generate_image"],  # List is unhashable
            "parameters": {"prompt": "test"},
        }
        violations = self.linter.lint_call(bad_call)
        self.assertTrue(any(v.rule_id == "malformed_call" for v in violations))

    def test_bug3_linter_init_none_in_tools_list_crash(self):
        """BUG 3: Non-dict / None entry in tools list is safely ignored during linter init."""
        linter = DeterministicLinter(tools=[None, {"name": "valid_tool"}])
        self.assertIn("valid_tool", linter._tool_cache)

    def test_bug4_cascading_penalty_collapse_none_arguments_crash(self):
        """BUG 4: apply_cascading_penalty_collapse safely initializes dict when 'arguments': None."""
        raw_scores = {
            "usage": {"necessity": 10},
            "selection": {"correctness": 10},
            "arguments": None,  # Present but None
        }
        violations = [
            LintViolation("tool", "param", "missing_required", "missing", "ERROR")
        ]
        collapsed = apply_cascading_penalty_collapse(raw_scores, violations)
        self.assertIsInstance(collapsed["arguments"], dict)
        self.assertEqual(collapsed["arguments"]["name_accuracy"], 0)

    def test_bug5_compute_tool_calling_score_none_subdimension_crash(self):
        """BUG 5: compute_tool_calling_score safely handles 'usage': None or 'arguments': None."""
        raw_scores = {
            "usage": None,
            "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
            "arguments": {"completeness": 10, "name_accuracy": 10, "value_accuracy": 10, "type_compliance": 10, "format_compliance": 10, "relevancy": 10},
            "ordering": {"not_applicable": True},
        }
        tc_scores = compute_tool_calling_score(raw_scores)
        self.assertIsInstance(tc_scores, ToolCallingScores)
        self.assertAlmostEqual(tc_scores.necessity, 1.0)

    def test_bug6_nan_scores_rewarded_with_perfect_score(self):
        """BUG 6: float('nan') passed to norm10/norm3 is clamped to 0.0."""
        nan_score_norm10 = norm10(float("nan"))
        nan_score_norm3 = norm3(float("nan"))
        self.assertEqual(nan_score_norm10, 0.0)
        self.assertEqual(nan_score_norm3, 0.0)


class TestLinterPerformanceUnderStress(unittest.TestCase):
    """Stress tests latency performance across 20,000 calls."""

    def setUp(self):
        self.spike_servers_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "spike", "servers")
        )
        self.linter = DeterministicLinter(servers_dir=self.spike_servers_dir)

    def test_latency_stress_benchmark(self):
        """Confirm average call latency is strictly < 0.010 ms (10 microseconds)."""
        valid_call = {
            "function_name": "veo_t2v",
            "parameters": {
                "prompt": "Ocean waves",
                "model": "veo-3.1-generate-001",
                "aspect_ratio": "16:9",
                "generate_audio": True,
            },
        }
        # Warmup
        for _ in range(500):
            self.linter.lint_call(valid_call)

        N = 20000
        start = time.perf_counter()
        for _ in range(N):
            self.linter.lint_call(valid_call)
        total_time = time.perf_counter() - start
        avg_ms = (total_time / N) * 1000.0
        avg_us = avg_ms * 1000.0

        print(f"\n[BENCHMARK] {N} calls in {total_time:.4f}s -> {avg_ms:.5f} ms/call ({avg_us:.2f} µs)")
        self.assertLess(avg_ms, 0.010)


if __name__ == "__main__":
    unittest.main()
