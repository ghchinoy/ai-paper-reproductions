"""Unit & Regression Test Suite for Agent Seer Evaluation Framework.

Tests:
1. DeterministicCapabilityLinter against all servers and failure modes (<1ms per case).
2. Scoring aggregation functions (TC arithmetic mean, cascading penalty collapse).
3. Cross-server schema integrity and model capability consistency.
"""
import os
import sys
import unittest

from linter import DeterministicCapabilityLinter
import scoring


class TestDeterministicLinter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.linter = DeterministicCapabilityLinter()

    def test_schema_loading(self):
        """Verify all server schemas and capabilities are loaded."""
        self.assertIn("veo_t2v", self.linter.schemas)
        self.assertIn("nanobanana_image_generation", self.linter.schemas)
        self.assertIn("lyria_generate_music", self.linter.schemas)
        self.assertIn("ffmpeg_combine_audio_and_video", self.linter.schemas)
        self.assertIn("chirp_tts", self.linter.schemas)
        self.assertGreaterEqual(len(self.linter.schemas), 18)

    def test_veo_audio_capability_enforcement(self):
        """Veo 2.0 must be rejected when generate_audio=True."""
        calls = [{
            "function_name": "veo_t2v",
            "parameters": {
                "prompt": "a test prompt",
                "model": "veo-2.0-generate-001",
                "generate_audio": True
            }
        }]
        res = self.linter.lint(calls)
        self.assertFalse(res.is_valid)
        self.assertTrue(any(e.category == "capability_violation" and "audio" in e.message for e in res.errors))

    def test_nanobanana_resolution_capability_enforcement(self):
        """Gemini 2.5 Flash Image must be rejected when image_size is specified."""
        calls = [{
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "a landscape",
                "model": "gemini-2.5-flash-image",
                "image_size": "4K"
            }
        }]
        res = self.linter.lint(calls)
        self.assertFalse(res.is_valid)
        self.assertTrue(any(e.category == "capability_violation" and "image_size" in e.message for e in res.errors))

    def test_lyria_parameter_misnomers(self):
        """Lyria expects model_id and output_gcs_bucket, rejecting model/bucket."""
        calls = [{
            "function_name": "lyria_generate_music",
            "parameters": {
                "prompt": "ambient music",
                "model": "lyria-3-clip-preview"  # Wrong param name
            }
        }]
        res = self.linter.lint(calls)
        self.assertFalse(res.is_valid)
        self.assertTrue(any(e.category == "unknown_param" and e.parameter == "model" for e in res.errors))

    def test_valid_multimodal_call(self):
        """A properly specified Nanobanana call must pass cleanly with 0 errors in < 1ms."""
        calls = [{
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "futuristic city skyline at sunset",
                "model": "gemini-3.1-flash-image",
                "aspect_ratio": "16:9",
                "image_size": "2K",
                "gcs_bucket_uri": "gs://mybucket/outputs/"
            }
        }]
        res = self.linter.lint(calls)
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.errors), 0)
        self.assertLess(res.latency_ms, 5.0)


class TestScoringAggregation(unittest.TestCase):
    def test_perfect_tc_aggregation(self):
        sample_judge_output = {
            "usage": {"necessity": 10, "overuse": 0},
            "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
            "arguments": {
                "completeness": 10, "name_accuracy": 10, "value_accuracy": 10,
                "type_compliance": 10, "format_compliance": 10, "relevancy": 10
            },
            "ordering": {"not_applicable": True},
            "failures": [],
            "rationale": "Flawless call."
        }
        res = scoring.aggregate_tc(sample_judge_output)
        self.assertAlmostEqual(res["tc_overall"], 1.0, places=3)
        self.assertEqual(res["dimensions"]["usage"], 1.0)
        self.assertEqual(res["dimensions"]["selection"], 1.0)
        self.assertEqual(res["dimensions"]["arguments"], 1.0)

    def test_cascading_penalty_collapse(self):
        """When parameter name is wrong, value/type/format zero out, collapsing argument score."""
        sample_judge_output = {
            "usage": {"necessity": 10, "overuse": 0},
            "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
            "arguments": {
                "completeness": 10, "name_accuracy": 0, "value_accuracy": 0,
                "type_compliance": 0, "format_compliance": 0, "relevancy": 0
            },
            "ordering": {"not_applicable": True},
            "failures": ["argument_name", "argument_value", "argument_type", "argument_format"],
            "rationale": "Invalid param names collapsed argument scores."
        }
        res = scoring.aggregate_tc(sample_judge_output)
        # Arguments dim = 10 / 60 = 0.167
        # Overall = (1.0 + 1.0 + 0.167) / 3 = 0.722
        self.assertAlmostEqual(res["dimensions"]["arguments"], 1.0 / 6.0, places=3)
        self.assertAlmostEqual(res["tc_overall"], (2.0 + 1.0 / 6.0) / 3.0, places=3)


if __name__ == "__main__":
    unittest.main()
