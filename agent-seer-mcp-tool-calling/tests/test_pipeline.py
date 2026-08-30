"""Unit and integration tests for Agent Seer 4-Stage Synthetic Eval Pipeline (arXiv:2608.26133)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from agent_seer.clients import MockClient
from agent_seer.judge import JudgeEngine
from agent_seer.linter import DeterministicLinter
from agent_seer.models import ServerSpec, ToolCall, ToolDefinition, ToolParameter
from agent_seer.pipeline import (
    AgentWorkflowStep,
    ConversationTurn,
    GroundedMockCall,
    GroundedMockScenario,
    MultiTurnTranscript,
    Scenario,
    ScenarioCollection,
    SyntheticEvalPipeline,
    SyntheticHarness,
    ToolInterpretation,
)
from agent_seer.prompts import (
    build_stage1_prompt,
    build_stage2_prompt,
    build_stage3_prompt,
    build_stage4_prompt,
    build_tool_summary,
)


class TestStage1Interpretation(unittest.TestCase):
    def setUp(self):
        self.sample_tool = ToolDefinition(
            name="veo_generate_video",
            description="Generates videos from text prompts.",
            parameters={
                "prompt": ToolParameter(name="prompt", type="string", description="Text description", required=True),
                "model": ToolParameter(name="model", type="string", description="Model ID", required=False),
                "duration_seconds": ToolParameter(name="duration_seconds", type="integer", description="Duration", required=False),
            },
            capabilities={"supports_audio": False},
        )

    def test_stage1_prompt_formatting(self):
        prompt = build_stage1_prompt(self.sample_tool)
        self.assertIn("veo_generate_video", prompt)
        self.assertIn("what_it_does", prompt)
        self.assertIn("what_it_needs", prompt)
        self.assertIn("enterprise_context", prompt)

    def test_stage1_execution_with_mock_client(self):
        mock_data = {
            "tool_name": "veo_generate_video",
            "what_it_does": "Generates videos from text prompt",
            "what_it_needs": "Required prompt string, optional model and duration",
            "why_its_used": "Automated video asset generation",
            "enterprise_context": ["Marketing", "Media Production"],
        }
        client = MockClient(canned_responses=mock_data)
        pipeline = SyntheticEvalPipeline(client=client)

        interps = pipeline.interpret_spec([self.sample_tool])
        self.assertEqual(len(interps), 1)
        self.assertEqual(interps[0].tool_name, "veo_generate_video")
        self.assertEqual(interps[0]["tool_name"], "veo_generate_video")
        self.assertIn("Marketing", interps[0].enterprise_context)
        self.assertEqual(client.call_count, 1)

    def test_stage1_offline_deterministic_fallback(self):
        pipeline = SyntheticEvalPipeline(offline=True)
        interps = pipeline.interpret_spec([self.sample_tool])
        self.assertEqual(len(interps), 1)
        interp = interps[0]
        self.assertEqual(interp.tool_name, "veo_generate_video")
        self.assertIn("prompt", interp.what_it_needs)
        self.assertIn("Media Production", interp.enterprise_context)


class TestStage2ScenarioGeneration(unittest.TestCase):
    def setUp(self):
        self.tools = [
            ToolDefinition(
                name="nanobanana_image_generation",
                description="Generates concept images.",
                parameters={"prompt": ToolParameter(name="prompt", type="string", required=True)},
            ),
            ToolDefinition(
                name="veo_i2v",
                description="Animates an image into video.",
                parameters={
                    "image_uri": ToolParameter(name="image_uri", type="string", required=True),
                    "prompt": ToolParameter(name="prompt", type="string", required=True),
                },
            ),
        ]
        self.interpretations = [
            ToolInterpretation(
                tool_name="nanobanana_image_generation",
                what_it_does="Generates concept images",
                what_it_needs="prompt string",
                why_its_used="Visual asset creation",
                enterprise_context=["Creative"],
            ),
            ToolInterpretation(
                tool_name="veo_i2v",
                what_it_does="Animates image to video",
                what_it_needs="image_uri and prompt",
                why_its_used="Video animation",
                enterprise_context=["Video Production"],
            ),
        ]

    def test_stage2_prompt_formatting(self):
        prompt_simple = build_stage2_prompt(self.interpretations, n_tools=2, tier="simple")
        self.assertIn("straightforward, and commonplace", prompt_simple)
        self.assertIn("2 tools total", prompt_simple)

        prompt_complex = build_stage2_prompt(self.interpretations, n_tools=2, tier="complex")
        self.assertIn("novel, and complex", prompt_complex)

        prompt_boundary = build_stage2_prompt(self.interpretations, n_tools=2, tier="boundary")
        self.assertIn("fault-testing scenarios", prompt_boundary)

    def test_stage2_execution_with_mock_client(self):
        mock_cats = {
            "categories": [
                {
                    "category": "Marketing Campaign",
                    "scenarios": [
                        {
                            "title": "Solar Car Concept Campaign",
                            "prompt": "Create concept image and animate into video",
                            "agent_workflow": [
                                {
                                    "function_name": "nanobanana_image_generation",
                                    "parameters": {"prompt": "solar car at sunset"},
                                    "quick_explanation": "Generate car concept",
                                },
                                {
                                    "function_name": "veo_i2v",
                                    "parameters": {"image_uri": "gs://bucket/car.png", "prompt": "accelerates smoothly"},
                                    "quick_explanation": "Animate car video",
                                },
                            ],
                            "novelty_reason": "Exercises 2-stage image-to-video workflow",
                            "agent_followup": "Would you like me to render in 4K?",
                        }
                    ],
                }
            ]
        }
        client = MockClient(canned_responses=mock_cats)
        pipeline = SyntheticEvalPipeline(client=client)

        scenarios = pipeline.generate_scenarios(
            self.interpretations,
            tools=self.tools,
            tiers=["simple"],
        )
        self.assertIsInstance(scenarios, ScenarioCollection)
        self.assertEqual(len(scenarios), 1)
        self.assertEqual(scenarios[0].title, "Solar Car Concept Campaign")
        self.assertEqual(len(scenarios[0].agent_workflow), 2)
        # Verify dual dict access
        self.assertIn("categories", scenarios)
        self.assertEqual(scenarios["categories"][0]["category"], "Marketing Campaign")

    def test_stage2_100_percent_tool_coverage(self):
        pipeline = SyntheticEvalPipeline(offline=True)
        scenarios = pipeline.generate_scenarios(
            self.interpretations,
            tools=self.tools,
            tiers=["simple", "complex"],
        )
        # Check that both tools appear across scenarios
        covered_tools = {step.function_name for sc in scenarios for step in sc.agent_workflow}
        for tool in self.tools:
            self.assertIn(tool.name, covered_tools)


class TestStage3MockOutputGeneration(unittest.TestCase):
    def setUp(self):
        self.scenario = Scenario(
            title="Generate Hero Clip",
            prompt="Create a video of our new product",
            agent_workflow=[
                AgentWorkflowStep(
                    function_name="veo_generate_video",
                    parameters={"prompt": "Product showcase"},
                    quick_explanation="Hero video",
                )
            ],
            novelty_reason="Baseline video test",
            agent_followup="Should I change duration?",
        )

    def test_stage3_prompt_formatting(self):
        prompt = build_stage3_prompt(self.scenario, example_outputs={"veo_generate_video": {"uri": "gs://bucket/1.mp4"}})
        self.assertIn("mock tool output", prompt.lower())
        self.assertIn("Product showcase", prompt)
        self.assertIn("gs://bucket/1.mp4", prompt)

    def test_stage3_execution_with_mock_client(self):
        mock_output_data = {
            "mock_workflow": [
                {
                    "function_name": "veo_generate_video",
                    "parameters": {"prompt": "Product showcase"},
                    "quick_explanation": "Hero video",
                    "mock_output": {
                        "content": [
                            {"type": "text", "text": "Video generated successfully."},
                            {"type": "resource_link", "uri": "gs://bucket/out.mp4", "mimeType": "video/mp4"},
                        ]
                    },
                    "confidence": "high",
                    "expected_response": {"video_uri": "gs://bucket/out.mp4"},
                }
            ]
        }
        client = MockClient(canned_responses=mock_output_data)
        pipeline = SyntheticEvalPipeline(client=client)

        grounded = pipeline.generate_mock_outputs([self.scenario])
        self.assertEqual(len(grounded), 1)
        self.assertEqual(grounded[0].scenario_title, "Generate Hero Clip")
        self.assertEqual(grounded[0].mock_workflow[0].confidence, "high")
        self.assertEqual(grounded[0]["mock_workflow"][0]["confidence"], "high")

    def test_stage3_offline_deterministic(self):
        pipeline = SyntheticEvalPipeline(offline=True)
        grounded = pipeline.generate_mock_outputs(
            [self.scenario],
            seed_outputs={"veo_generate_video": {"content": [{"type": "text", "text": "seeded output"}]}},
        )
        self.assertEqual(len(grounded), 1)
        self.assertEqual(grounded[0].mock_workflow[0].confidence, "high")
        self.assertIn("seeded output", str(grounded[0].mock_workflow[0].mock_output))


class TestStage4MultiTurnTranscriptExpansion(unittest.TestCase):
    def setUp(self):
        self.scenario = Scenario(
            title="Solar Car Clip",
            prompt="Generate a car video",
            agent_workflow=[
                AgentWorkflowStep(function_name="veo_generate_video", parameters={"prompt": "car"}),
            ],
            agent_followup="Extend video to 10 seconds",
        )
        self.mock_sc = GroundedMockScenario(
            scenario_title="Solar Car Clip",
            tier="simple",
            scenario=self.scenario,
            mock_workflow=[
                GroundedMockCall(
                    function_name="veo_generate_video",
                    parameters={"prompt": "car"},
                    quick_explanation="Generate clip",
                    mock_output={"uri": "gs://bucket/clip1.mp4"},
                    confidence="high",
                )
            ],
        )

    def test_stage4_prompt_formatting(self):
        prompt = build_stage4_prompt(self.scenario, [m.to_dict() for m in self.mock_sc.mock_workflow])
        self.assertIn("Multi-Turn Conversation Expander", prompt)
        self.assertIn("Solar Car Clip", prompt)
        self.assertIn("gs://bucket/clip1.mp4", prompt)

    def test_stage4_execution_with_mock_client(self):
        mock_transcript_data = {
            "scenario_title": "Solar Car Clip",
            "turns": [
                {
                    "turn_index": 1,
                    "user_message": "Generate a car video",
                    "agent_tool_calls": [{"name": "veo_generate_video", "arguments": {"prompt": "car"}}],
                    "tool_responses": [{"tool_name": "veo_generate_video", "output": {"uri": "gs://bucket/clip1.mp4"}}],
                    "agent_response": "I created your video at gs://bucket/clip1.mp4.",
                },
                {
                    "turn_index": 2,
                    "user_message": "Extend video to 10 seconds",
                    "agent_tool_calls": [{"name": "veo_extend_video", "arguments": {"input_uri": "gs://bucket/clip1.mp4"}}],
                    "tool_responses": [{"tool_name": "veo_extend_video", "output": {"uri": "gs://bucket/clip2.mp4"}}],
                    "agent_response": "Extended video is ready at gs://bucket/clip2.mp4.",
                },
            ],
        }
        client = MockClient(canned_responses=mock_transcript_data)
        pipeline = SyntheticEvalPipeline(client=client)

        transcripts = pipeline.expand_multi_turn([self.mock_sc])
        self.assertEqual(len(transcripts), 1)
        t = transcripts[0]
        self.assertEqual(t.scenario_title, "Solar Car Clip")
        self.assertEqual(len(t.turns), 2)
        self.assertEqual(t.turns[0].turn_index, 1)
        self.assertEqual(t.turns[1].turn_index, 2)
        self.assertIn("Turn 1:", t.to_text())
        self.assertIn("Turn 2:", t.to_text())

    def test_stage4_offline_deterministic(self):
        pipeline = SyntheticEvalPipeline(offline=True)
        transcripts = pipeline.expand_multi_turn([self.mock_sc])
        self.assertEqual(len(transcripts), 1)
        t = transcripts[0]
        self.assertGreaterEqual(len(t.turns), 1)
        self.assertEqual(t.turns[0].turn_index, 1)
        self.assertIn("USER:", t.to_text())


class TestEndToEndSyntheticPipeline(unittest.TestCase):
    def setUp(self):
        self.tools = [
            ToolDefinition(
                name="nanobanana_image_generation",
                description="Generates concept images.",
                parameters={"prompt": ToolParameter(name="prompt", type="string", required=True)},
            ),
            ToolDefinition(
                name="veo_i2v",
                description="Animates an image into video.",
                parameters={
                    "image_uri": ToolParameter(name="image_uri", type="string", required=True),
                    "prompt": ToolParameter(name="prompt", type="string", required=True),
                },
            ),
        ]
        self.server_spec = ServerSpec(
            server_name="genmedia-suite",
            tools=self.tools,
            capabilities={"veo_i2v": {"supports_audio": False}},
            seed_outputs={"nanobanana_image_generation": {"uri": "gs://bucket/concept.png"}},
        )

    def test_full_pipeline_offline_deterministic_mode(self):
        pipeline = SyntheticEvalPipeline(offline=True)
        harness = pipeline.generate_pipeline(self.server_spec, tiers=["simple", "complex"])

        self.assertIsInstance(harness, SyntheticHarness)
        self.assertEqual(harness.server_name, "genmedia-suite")
        self.assertEqual(len(harness.interpretations), 2)
        self.assertGreaterEqual(len(harness.scenarios), 2)
        self.assertGreaterEqual(len(harness.mock_scenarios), 2)
        self.assertGreaterEqual(len(harness.transcripts), 2)

    def test_pipeline_export_to_directory(self):
        temp_dir = tempfile.mkdtemp(prefix="seer_test_export_")
        try:
            pipeline = SyntheticEvalPipeline(offline=True)
            harness = pipeline.run(self.server_spec, output_dir=temp_dir)

            expected_files = [
                "stage1_interpretations.json",
                "stage2_scenarios.json",
                "stage3_mock_outputs.json",
                "stage4_transcripts.json",
                "synthetic_harness.json",
            ]
            for fname in expected_files:
                fpath = os.path.join(temp_dir, fname)
                self.assertTrue(os.path.exists(fpath), f"Missing exported file: {fpath}")
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.assertIsNotNone(data)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_pipeline_integration_with_linter_and_judge(self):
        pipeline = SyntheticEvalPipeline(offline=True)
        harness = pipeline.run(self.server_spec)

        # 1. Lint generated scenario tool calls
        linter = DeterministicLinter(tools=self.tools)
        for sc in harness.scenarios:
            tool_calls = [
                ToolCall(name=step.function_name, arguments=step.parameters)
                for step in sc.agent_workflow
            ]
            lint_res = linter.lint(tool_calls)
            self.assertTrue(lint_res.is_valid, f"Scenario '{sc.title}' failed linting: {lint_res.errors}")

        # 2. Evaluate with JudgeEngine and MockClient
        mock_client = MockClient.for_tc_judge(overall_score=0.92)
        judge_engine = JudgeEngine(client=mock_client, linter=linter)

        eval_res = judge_engine.evaluate_tool_calls(
            tool_specs=self.tools,
            user_prompt=harness.scenarios[0].prompt,
            agent_calls=[ToolCall(name=s.function_name, arguments=s.parameters) for s in harness.scenarios[0].agent_workflow],
        )
        self.assertTrue(eval_res.passed)
        self.assertGreaterEqual(eval_res.tool_calling.overall_tool_calling, 0.85)

        # 3. Evaluate multi-turn transcript coherence
        coh_client = MockClient.for_coherence_judge(score_3=3)
        coh_engine = JudgeEngine(client=coh_client)
        transcript_eval = coh_engine.evaluate_transcript(harness.transcripts[0].to_text())
        self.assertTrue(transcript_eval.passed)
        self.assertEqual(transcript_eval.coherence.overall_coherence, 1.0)


if __name__ == "__main__":
    unittest.main()
