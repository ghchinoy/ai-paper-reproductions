"""Unit tests for agent_seer.discovery."""
import json
import os
import tempfile
import unittest

from agent_seer.discovery import load_tools_and_capabilities


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tools_path = os.path.join(self.temp_dir.name, "tools_list.json")
        self.caps_path = os.path.join(self.temp_dir.name, "capabilities.json")

        self.sample_tools = {
            "tools": [
                {
                    "name": "sample_tool",
                    "description": "A sample tool",
                    "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
                }
            ]
        }
        self.sample_caps = {"sample_model": {"SupportsFeature": True}}

        with open(self.tools_path, "w") as f:
            json.dump(self.sample_tools, f)
        with open(self.caps_path, "w") as f:
            json.dump(self.sample_caps, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_from_directory(self):
        tools, caps = load_tools_and_capabilities(self.temp_dir.name)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "sample_tool")
        self.assertIn("sample_model", caps)

    def test_load_from_json_file(self):
        tools, caps = load_tools_and_capabilities(self.tools_path, self.caps_path)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "sample_tool")
        self.assertTrue(caps["sample_model"]["SupportsFeature"])


if __name__ == "__main__":
    unittest.main()
