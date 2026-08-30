"""Unit tests for agent_seer.scoring."""
import unittest

from agent_seer.scoring import aggregate_coherence, aggregate_tc, norm3, norm10


class TestScoring(unittest.TestCase):
    def test_normalization_bounds(self):
        self.assertEqual(norm10(0), 0.0)
        self.assertEqual(norm10(10), 1.0)
        self.assertEqual(norm10(5), 0.5)
        self.assertEqual(norm10(15), 1.0)
        self.assertEqual(norm10(-5), 0.0)

        self.assertEqual(norm3(1), 0.0)
        self.assertEqual(norm3(2), 0.5)
        self.assertEqual(norm3(3), 1.0)

    def test_aggregate_tc_perfect_single_call(self):
        raw = {
            "usage": {"necessity": 10},
            "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
            "arguments": {
                "completeness": 10,
                "name_accuracy": 10,
                "value_accuracy": 10,
                "type_compliance": 10,
                "format_compliance": 10,
                "relevancy": 10,
            },
            "ordering": {"not_applicable": True},
            "failures": [],
            "rationale": "Perfect call",
        }
        res = aggregate_tc(raw)
        self.assertEqual(res["tc_overall"], 1.0)
        self.assertNotIn("ordering", res["dimensions"])

    def test_aggregate_tc_with_ordering(self):
        raw = {
            "usage": {"necessity": 10},
            "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
            "arguments": {
                "completeness": 10,
                "name_accuracy": 10,
                "value_accuracy": 10,
                "type_compliance": 10,
                "format_compliance": 10,
                "relevancy": 10,
            },
            "ordering": {
                "not_applicable": False,
                "sequence_logic": 10,
                "dependency_handling": 10,
                "execution_efficiency": 10,
            },
            "failures": [],
            "rationale": "Perfect multi-call chain",
        }
        res = aggregate_tc(raw)
        self.assertEqual(res["tc_overall"], 1.0)
        self.assertIn("ordering", res["dimensions"])
        self.assertEqual(res["dimensions"]["ordering"], 1.0)

    def test_aggregate_coherence(self):
        raw = {
            "logical_flow": 3,
            "completeness": 3,
            "conciseness": 3,
            "topic_relevance": 3,
            "context_retention": {"not_applicable": True},
            "rationale": "High quality conversation",
        }
        res = aggregate_coherence(raw)
        self.assertEqual(res["coherence_overall"], 1.0)


if __name__ == "__main__":
    unittest.main()
