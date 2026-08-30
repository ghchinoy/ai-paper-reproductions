import os
import subprocess
import sys
import unittest

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = f"{SRC_DIR}:{self.env.get('PYTHONPATH', '')}"

    def test_cli_help(self):
        cmd = [sys.executable, "-m", "agent_seer.cli", "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True, env=self.env)
        self.assertEqual(res.returncode, 0)
        self.assertIn("inspect", res.stdout)
        self.assertIn("lint", res.stdout)
        self.assertIn("eval", res.stdout)

    def test_cli_inspect_veo(self):
        cmd = [
            sys.executable,
            "-m",
            "agent_seer.cli",
            "inspect",
            "spike/servers/veo/tools_list.json",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, env=self.env)
        self.assertEqual(res.returncode, 0)
        self.assertIn("veo_t2v", res.stdout)
        self.assertIn("veo_i2v", res.stdout)

    def test_cli_lint_nanobanana(self):
        cmd = [
            sys.executable,
            "-m",
            "agent_seer.cli",
            "lint",
            "spike/servers/nanobanana/transcripts.py",
            "--server",
            "spike/servers/nanobanana",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, env=self.env)
        self.assertEqual(res.returncode, 0)
        self.assertIn("NB0-correct", res.stdout)
        self.assertIn("VALID", res.stdout)


if __name__ == "__main__":
    unittest.main()
