"""Conformance tests for Agent Plugin and Agent Skill definitions."""
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(HERE)


class TestPluginAndSkillConformance(unittest.TestCase):
    def test_plugin_json_conformance(self):
        plugin_path = os.path.join(PKG_ROOT, "plugin.json")
        self.assertTrue(os.path.exists(plugin_path), "plugin.json must exist")

        with open(plugin_path) as f:
            data = json.load(f)

        self.assertEqual(data.get("$schema"), "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertEqual(data.get("name"), "agent-seer")
        self.assertIn("version", data)
        self.assertIn("description", data)
        self.assertIn("author", data)
        self.assertIn("repository", data)
        self.assertEqual(data.get("license"), "Apache-2.0")
        self.assertIsInstance(data.get("keywords"), list)
        self.assertGreaterEqual(len(data["keywords"]), 3)

    def test_skill_md_conformance(self):
        skill_path = os.path.join(PKG_ROOT, "skills", "agent-seer", "SKILL.md")
        self.assertTrue(os.path.exists(skill_path), "skills/agent-seer/SKILL.md must exist")

        with open(skill_path) as f:
            content = f.read()

        # Check frontmatter
        self.assertTrue(content.startswith("---\n"), "SKILL.md must start with YAML frontmatter")
        frontmatter = content.split("---", 2)[1]
        self.assertIn("name: agent-seer", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertIn("license: Apache-2.0", frontmatter)
        self.assertIn("compatibility:", frontmatter)
        self.assertIn("metadata:", frontmatter)

        # Extract description length and verify <= 1024 characters
        lines = frontmatter.strip().split("\n")
        desc_lines = []
        in_desc = False
        for line in lines:
            if line.startswith("description:"):
                in_desc = True
                desc_lines.append(line.split("description:", 1)[1].strip())
            elif in_desc:
                if line.startswith("  ") or line.startswith("    "):
                    desc_lines.append(line.strip())
                else:
                    break
        desc_text = " ".join(desc_lines)
        self.assertLessEqual(len(desc_text), 1024, f"Frontmatter description exceeds 1024 chars ({len(desc_text)} chars)")

    def test_progressive_disclosure_references(self):
        rubric_ref = os.path.join(PKG_ROOT, "skills", "agent-seer", "references", "rubric-guide.md")
        caps_ref = os.path.join(PKG_ROOT, "skills", "agent-seer", "references", "capability-schemas.md")

        self.assertTrue(os.path.exists(rubric_ref), "references/rubric-guide.md must exist")
        self.assertTrue(os.path.exists(caps_ref), "references/capability-schemas.md must exist")


if __name__ == "__main__":
    unittest.main()
