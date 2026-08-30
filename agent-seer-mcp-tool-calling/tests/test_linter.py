"""Unit tests for agent_seer.linter."""
import unittest

from agent_seer.linter import DeterministicLinter


class TestDeterministicLinter(unittest.TestCase):
    def setUp(self):
        self.sample_tools = [
            {
                "name": "generate_video",
                "description": "Generates a video clip",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "model": {"type": "string"},
                        "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16"]},
                        "generate_audio": {"type": "boolean"},
                    },
                    "required": ["prompt", "model"],
                },
            }
        ]
        self.sample_caps = {
            "veo-legacy": {
                "SupportedAspectRatios": ["16:9"],
                "SupportsGenerateAudio": False,
            },
            "veo-advanced": {
                "SupportedAspectRatios": ["16:9", "9:16"],
                "SupportsGenerateAudio": True,
            },
        }
        self.linter = DeterministicLinter(
            tools=self.sample_tools, capabilities=self.sample_caps
        )

    def test_valid_call(self):
        calls = [
            {
                "function_name": "generate_video",
                "parameters": {
                    "prompt": "A scenic mountain highway at sunset",
                    "model": "veo-advanced",
                    "aspect_ratio": "16:9",
                    "generate_audio": True,
                },
            }
        ]
        res = self.linter.lint(calls)
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.errors), 0)
        self.assertLess(res.latency_ms, 5.0)

    def test_missing_required_parameter(self):
        calls = [
            {
                "function_name": "generate_video",
                "parameters": {"model": "veo-advanced"},
            }
        ]
        res = self.linter.lint(calls)
        self.assertFalse(res.is_valid)
        self.assertTrue(any(e.category == "missing_required" and e.parameter == "prompt" for e in res.errors))

    def test_unknown_parameter(self):
        calls = [
            {
                "function_name": "generate_video",
                "parameters": {
                    "prompt": "sunset",
                    "model": "veo-advanced",
                    "ratio": "16:9",  # Misnamed parameter
                },
            }
        ]
        res = self.linter.lint(calls)
        self.assertFalse(res.is_valid)
        self.assertTrue(any(e.category == "unknown_param" and e.parameter == "ratio" for e in res.errors))

    def test_illegal_enum(self):
        calls = [
            {
                "function_name": "generate_video",
                "parameters": {
                    "prompt": "sunset",
                    "model": "veo-advanced",
                    "aspect_ratio": "21:9",  # Illegal enum in schema
                },
            }
        ]
        res = self.linter.lint(calls)
        self.assertFalse(res.is_valid)
        self.assertTrue(any(e.category == "illegal_enum" for e in res.errors))


if __name__ == "__main__":
    unittest.main()
