"""Adversarial Fuzzing and Boundary Test Suite for Agent Seer Pipeline & Prompts (Milestone 2).

Challenger 2 adversarial test suite validating:
1. Malformed JSON strings, markdown code fences with trailing garbage, corrupted Unicode in tool interpretations and client outputs.
2. Pipeline behavior on empty tool lists, tools without parameters, and tools with deeply nested recursive parameter schemas.
3. Scenario, transcript, and harness serialization/deserialization fidelity (to_dict / from_dict, to_text, ScenarioCollection dual access).
4. Dataset export filesystem errors, missing parent directories, read-only paths, and invalid path collisions.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import unittest
from typing import Any, Dict, List

from agent_seer.clients import (
    LLMAuthError,
    LLMClientError,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMRateLimitError,
    LLMResponse,
    LLMResponseFormatError,
    LLMTimeoutError,
    MockClient,
    TokenUsage,
    extract_json_payload,
)
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
    STAGE1_TOOL_INTERPRETATION,
    STAGE2_BOUNDARY,
    STAGE2_COMPLEX,
    STAGE2_SIMPLE,
    STAGE3_MOCK_OUTPUT,
    STAGE4_MULTI_TURN,
    build_stage1_prompt,
    build_stage2_prompt,
    build_stage3_prompt,
    build_stage4_prompt,
    build_tool_summary,
)


class TestAdversarialJSONExtraction(unittest.TestCase):
    """Adversarial stress-testing of JSON extraction and recovery logic."""

    def test_severely_malformed_json_raises_format_error(self):
        malformed_inputs = [
            "",
            "   \n\t  ",
            "This is just plain text without any JSON.",
            "{unquoted_key: 'value'}",
            "{'single_quotes': True}",
            "{incomplete_json: ",
            "{\"key\": undefined}",
            "<xml><data>not json</data></xml>",
            "None",
        ]
        for bad_input in malformed_inputs:
            with self.subTest(input_text=bad_input):
                with self.assertRaises(LLMResponseFormatError):
                    extract_json_payload(bad_input)

    def test_markdown_code_fences_with_clean_fences(self):
        raw_text = (
            "```json\n"
            "{\n"
            '  "tool_name": "media_render",\n'
            '  "what_it_does": "Renders audio and video tracks.",\n'
            '  "what_it_needs": "audio_uri and video_uri",\n'
            '  "why_its_used": "Automated compositing",\n'
            '  "enterprise_context": ["Marketing", "Production"]\n'
            "}\n"
            "```\n\n"
            "Hope this helps!"
        )
        parsed = extract_json_payload(raw_text)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed.get("tool_name"), "media_render")
        self.assertEqual(len(parsed.get("enterprise_context", [])), 2)

    def test_markdown_code_fence_with_conversational_prefix(self):
        raw_text = (
            "Here is the generated JSON specification:\n"
            "```json\n"
            "{\n"
            '  "tool_name": "speech_synthesis",\n'
            '  "what_it_does": "Synthesizes expressive speech audio."\n'
            "}\n"
            "```\n"
            "Let me know if you need more details!"
        )
        parsed = extract_json_payload(raw_text)
        self.assertEqual(parsed.get("tool_name"), "speech_synthesis")
        self.assertEqual(parsed.get("what_it_does"), "Synthesizes expressive speech audio.")

    def test_code_fence_without_language_specifier(self):
        raw_text = (
            "```\n"
            "{\n"
            '  "tool_name": "generic_tool",\n'
            '  "what_it_does": "Performs operations"\n'
            "}\n"
            "```"
        )
        parsed = extract_json_payload(raw_text)
        self.assertEqual(parsed.get("tool_name"), "generic_tool")

    def test_trailing_commas_in_objects_and_arrays(self):
        raw_text = (
            "{\n"
            '  "tool_name": "test_tool",\n'
            '  "items": [1, 2, 3,],\n'
            '  "details": {"a": "b",},\n'
            "}"
        )
        parsed = extract_json_payload(raw_text)
        self.assertEqual(parsed.get("tool_name"), "test_tool")
        self.assertEqual(parsed.get("items"), [1, 2, 3])
        self.assertEqual(parsed.get("details"), {"a": "b"})

    def test_embedded_json_in_conversational_chatter(self):
        raw_text = (
            "Certainly! I analyzed the specifications.\n"
            "The result is:\n"
            '{"categories": [{"category": "Audio", "scenarios": []}]}\n'
            "Let me know if you need more scenarios!"
        )
        parsed = extract_json_payload(raw_text)
        self.assertIn("categories", parsed)
        self.assertEqual(parsed["categories"][0]["category"], "Audio")

    def test_corrupted_unicode_and_special_characters(self):
        unicode_text = (
            "```json\n"
            "{\n"
            '  "tool_name": "音频处理_tool_🎵_\\u0000",\n'
            '  "what_it_does": "Handles 4K/8K 🎥 & high-res audio 🎧 (مرحبا / שלום / Привет)",\n'
            '  "what_it_needs": "Input: \\"gs://bucket/asset_🚀.mp4\\"",\n'
            '  "why_its_used": "Multi-lingual translation & asset synthesis: 日本語/한국어",\n'
            '  "enterprise_context": ["グローバル", "Enterprise AI 🤖", "Accented: é, à, ü, ñ"]\n'
            "}\n"
            "```"
        )
        parsed = extract_json_payload(unicode_text)
        self.assertIn("音频处理_tool_🎵", parsed["tool_name"])
        self.assertIn("🎥", parsed["what_it_does"])
        self.assertIn("グローバル", parsed["enterprise_context"])
        self.assertIn("Enterprise AI 🤖", parsed["enterprise_context"])

    def test_array_payload_wrapped_in_items(self):
        raw_array = '[{"tool_name": "tool_a"}, {"tool_name": "tool_b"}]'
        parsed = extract_json_payload(raw_array)
        self.assertIn("items", parsed)
        self.assertEqual(len(parsed["items"]), 2)

    def test_direct_dict_or_list_input_passthrough(self):
        dict_input = {"tool_name": "direct_tool"}
        self.assertEqual(extract_json_payload(dict_input), dict_input)

        list_input = [{"a": 1}, {"b": 2}]
        self.assertEqual(extract_json_payload(list_input), {"items": list_input})


class TestPromptAssemblyEdgeCases(unittest.TestCase):
    """Adversarial testing of prompt builders with edge-case schemas."""

    def test_build_tool_summary_empty_list(self):
        summary = build_tool_summary([])
        self.assertEqual(summary, "")

    def test_build_tool_summary_tool_without_parameters(self):
        tool = ToolDefinition(name="ping_health", description="Health check without parameters", parameters={})
        summary = build_tool_summary([tool])
        self.assertIn("### Tool: `ping_health`", summary)
        self.assertIn("- **Description**: Health check without parameters", summary)
        self.assertIn("- **Parameters**: None", summary)

    def test_build_tool_summary_deeply_nested_parameters(self):
        nested_props = {
            "config": ToolParameter(
                name="config",
                type="object",
                description="Nested configuration",
                required=True,
                properties={
                    "level1": {
                        "type": "object",
                        "properties": {
                            "level2": {
                                "type": "object",
                                "properties": {"level3": {"type": "string", "enum": ["A", "B"]}},
                            }
                        },
                    }
                },
            ),
            "flags": ToolParameter(
                name="flags",
                type="array",
                description="List of flags",
                required=False,
                items={"type": "string"},
                enum=["fast", "accurate", "debug"],
            ),
        }
        tool = ToolDefinition(name="deep_tool", description="Tool with nested params", parameters=nested_props)
        summary = build_tool_summary([tool])
        self.assertIn("`config` (object, REQUIRED)", summary)
        self.assertIn("`flags` (array, optional)", summary)
        self.assertIn("[Enum: fast, accurate, debug]", summary)

    def test_build_tool_summary_with_dict_tools(self):
        raw_tools = [
            {
                "name": "raw_tool_1",
                "description": "A dict tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "description": "Max results", "default": 10},
                    },
                    "required": ["query"],
                },
                "capabilities": {"max_limit": 100},
            }
        ]
        summary = build_tool_summary(raw_tools)
        self.assertIn("### Tool: `raw_tool_1`", summary)
        self.assertIn("`query` (string, REQUIRED)", summary)
        self.assertIn("`limit` (integer, optional)", summary)
        self.assertIn('{"max_limit": 100}', summary)

    def test_build_stage1_prompt_with_capabilities(self):
        tool = ToolDefinition(name="audio_fx", description="Audio processing", parameters={})
        prompt = build_stage1_prompt(tool, capabilities={"supported_codecs": ["mp3", "flac"]})
        self.assertIn("audio_fx", prompt)
        self.assertIn("supported_codecs", prompt)
        self.assertIn("flac", prompt)

    def test_build_stage2_prompt_boundary_tier(self):
        interps = [
            ToolInterpretation(
                tool_name="tool_boundary",
                what_it_does="Boundary testing tool",
                what_it_needs="param1",
                why_its_used="Testing",
                enterprise_context=["QA"],
            )
        ]
        prompt = build_stage2_prompt(interps, n_tools=1, tier="boundary")
        self.assertIn("fault-testing scenarios", prompt)
        self.assertIn("Missing required parameters", prompt)
        self.assertIn("1 tools total", prompt)

    def test_build_stage2_prompt_custom_tier_falls_back_to_simple(self):
        interps = [
            ToolInterpretation(
                tool_name="tool_fallback",
                what_it_does="Fallback tool",
                what_it_needs="none",
                why_its_used="Testing",
            )
        ]
        prompt = build_stage2_prompt(interps, n_tools=1, tier="non_existent_tier")
        self.assertIn("straightforward, and commonplace", prompt)

    def test_build_stage3_prompt_with_none_example_outputs(self):
        sc = Scenario(title="Test", prompt="Prompt test", agent_workflow=[])
        prompt = build_stage3_prompt(sc, example_outputs=None)
        self.assertIn("No prior reference outputs provided", prompt)

    def test_build_stage4_prompt_with_string_or_dict_scenario(self):
        prompt_str = build_stage4_prompt("string_scenario_title")
        self.assertIn("string_scenario_title", prompt_str)

        prompt_dict = build_stage4_prompt({"title": "Dict Scenario", "prompt": "Do task", "agent_followup": "Next?"})
        self.assertIn("Dict Scenario", prompt_dict)
        self.assertIn("Do task", prompt_dict)
        self.assertIn("Next?", prompt_dict)


class TestPipelineFaultToleranceAndFallbacks(unittest.TestCase):
    """Verifies pipeline graceful degradation when clients return malformed data or raise errors."""

    def setUp(self):
        self.tools = [
            ToolDefinition(
                name="chirp_tts",
                description="Converts text to speech.",
                parameters={
                    "text": ToolParameter(name="text", type="string", required=True),
                    "voice": ToolParameter(name="voice", type="string", required=False, enum=["voice_a", "voice_b"]),
                },
            ),
            ToolDefinition(
                name="nanobanana_image",
                description="Generates images.",
                parameters={
                    "prompt": ToolParameter(name="prompt", type="string", required=True),
                },
            ),
        ]

    def test_stage1_fallback_on_client_format_error(self):
        client = MockClient(canned_responses="Not valid JSON at all")
        pipeline = SyntheticEvalPipeline(client=client, offline=False)

        interps = pipeline.interpret_spec(self.tools)
        self.assertEqual(len(interps), 2)
        self.assertEqual(interps[0].tool_name, "chirp_tts")
        self.assertIn("text", interps[0].what_it_needs)
        self.assertEqual(interps[1].tool_name, "nanobanana_image")

    def test_stage1_fallback_on_client_exception(self):
        client = MockClient(error_to_raise=LLMTimeoutError("Request timed out"))
        pipeline = SyntheticEvalPipeline(client=client, offline=False)

        interps = pipeline.interpret_spec(self.tools)
        self.assertEqual(len(interps), 2)
        self.assertEqual(interps[0].tool_name, "chirp_tts")

    def test_stage2_fallback_on_malformed_categories(self):
        client = MockClient(canned_responses={"unexpected_root": 123})
        pipeline = SyntheticEvalPipeline(client=client, offline=False)

        interps = pipeline.interpret_spec(self.tools)
        scenarios = pipeline.generate_scenarios(interps, tools=self.tools, tiers=["simple"])
        self.assertIsInstance(scenarios, ScenarioCollection)
        self.assertGreaterEqual(len(scenarios), 2)
        covered = {s.function_name for sc in scenarios for s in sc.agent_workflow}
        self.assertIn("chirp_tts", covered)
        self.assertIn("nanobanana_image", covered)

    def test_stage3_fallback_on_empty_mock_workflow(self):
        client = MockClient(canned_responses={"mock_workflow": []})
        pipeline = SyntheticEvalPipeline(client=client, offline=False)

        sc = Scenario(
            title="TTS Scenario",
            prompt="Speak this message",
            agent_workflow=[AgentWorkflowStep(function_name="chirp_tts", parameters={"text": "Hello world"})],
        )
        mock_scs = pipeline.generate_mock_outputs([sc])
        self.assertEqual(len(mock_scs), 1)
        self.assertEqual(len(mock_scs[0].mock_workflow), 1)
        self.assertEqual(mock_scs[0].mock_workflow[0].function_name, "chirp_tts")
        self.assertIn("status", mock_scs[0].mock_workflow[0].mock_output)

    def test_stage4_fallback_on_invalid_turns(self):
        client = MockClient(canned_responses={"turns": "not a list"})
        pipeline = SyntheticEvalPipeline(client=client, offline=False)

        mock_sc = GroundedMockScenario(
            scenario_title="TTS Scenario",
            tier="simple",
            scenario=Scenario(
                title="TTS Scenario",
                prompt="Speak this message",
                agent_workflow=[AgentWorkflowStep(function_name="chirp_tts", parameters={"text": "Hello"})],
                agent_followup="Can you change the voice?",
            ),
            mock_workflow=[
                GroundedMockCall(
                    function_name="chirp_tts",
                    parameters={"text": "Hello"},
                    mock_output={"audio_uri": "gs://bucket/audio.wav"},
                    confidence="high",
                )
            ],
        )
        transcripts = pipeline.expand_multi_turn([mock_sc])
        self.assertEqual(len(transcripts), 1)
        self.assertEqual(len(transcripts[0].turns), 2)
        self.assertEqual(transcripts[0].turns[0].turn_index, 1)
        self.assertEqual(transcripts[0].turns[1].turn_index, 2)


class TestPipelineEmptyAndExtremeInputs(unittest.TestCase):
    """Stress testing pipeline behavior on empty, zero-tool, and extreme input boundaries."""

    def test_empty_tool_list_produces_empty_harness(self):
        pipeline = SyntheticEvalPipeline(offline=True)
        spec = ServerSpec(server_name="empty-server", tools=[])
        harness = pipeline.generate_pipeline(spec)

        self.assertEqual(harness.server_name, "empty-server")
        self.assertEqual(len(harness.interpretations), 0)
        self.assertEqual(len(harness.scenarios), 0)
        self.assertEqual(len(harness.mock_scenarios), 0)
        self.assertEqual(len(harness.transcripts), 0)
        self.assertEqual(harness.metadata["total_tools"], 0)

    def test_single_tool_without_parameters(self):
        tool = ToolDefinition(name="ping", description="Ping server", parameters={})
        pipeline = SyntheticEvalPipeline(offline=True)
        spec = ServerSpec(server_name="ping-server", tools=[tool])
        harness = pipeline.generate_pipeline(spec, tiers=["simple", "boundary"])

        self.assertEqual(len(harness.interpretations), 1)
        self.assertEqual(harness.interpretations[0].tool_name, "ping")
        self.assertEqual(harness.interpretations[0].what_it_needs, "No parameters required.")

        for sc in harness.scenarios:
            self.assertEqual(sc.agent_workflow[0].function_name, "ping")
            self.assertEqual(sc.agent_workflow[0].parameters, {})

    def test_tool_with_50_parameters_and_deep_nesting(self):
        params: Dict[str, ToolParameter] = {}
        for idx in range(50):
            p_name = f"param_{idx:02d}"
            p_type = "string" if idx % 3 == 0 else ("integer" if idx % 3 == 1 else "boolean")
            params[p_name] = ToolParameter(
                name=p_name,
                type=p_type,
                description=f"Generated parameter {idx}",
                required=(idx < 10),
                default=f"default_{idx}" if idx >= 40 else None,
            )

        tool = ToolDefinition(name="mega_tool", description="High-dimensional tool", parameters=params)
        pipeline = SyntheticEvalPipeline(offline=True)
        spec = ServerSpec(server_name="mega-server", tools=[tool])
        harness = pipeline.generate_pipeline(spec, tiers=["simple", "boundary"])

        self.assertEqual(len(harness.interpretations), 1)
        self.assertIn("Required parameters:", harness.interpretations[0].what_it_needs)
        self.assertIn("Optional parameters:", harness.interpretations[0].what_it_needs)

        simple_sc = next(s for s in harness.scenarios if s.tier == "simple")
        for idx in range(10):
            self.assertIn(f"param_{idx:02d}", simple_sc.agent_workflow[0].parameters)

    def test_multi_tool_chaining_in_complex_tier(self):
        tools = [
            ToolDefinition(name=f"stage_{i}_tool", parameters={"input_uri": ToolParameter(name="input_uri", type="string", required=True)})
            for i in range(1, 6)
        ]
        pipeline = SyntheticEvalPipeline(offline=True)
        scenarios = pipeline.generate_scenarios([], tools=tools, tiers=["complex"])
        self.assertGreaterEqual(len(scenarios), 1)

        complex_sc = next(s for s in scenarios if s.tier == "complex")
        self.assertEqual(complex_sc.title, "Composite Multi-Tool Chained Pipeline")
        self.assertGreaterEqual(len(complex_sc.agent_workflow), 4)

        step1 = complex_sc.agent_workflow[0]
        step2 = complex_sc.agent_workflow[1]
        self.assertEqual(step1.parameters.get("input_uri"), "gs://mock-bucket/assets/initial.png")
        self.assertEqual(step2.parameters.get("input_uri"), "gs://mock-bucket/step_1_out.mp4")

    def test_coverage_enforcement_when_some_tools_missing_from_live_generation(self):
        tools = [
            ToolDefinition(name="tool_a", description="Tool A"),
            ToolDefinition(name="tool_b", description="Tool B"),
            ToolDefinition(name="tool_c", description="Tool C"),
        ]
        # Mock client returns scenario covering only tool_a
        partial_response = {
            "categories": [
                {
                    "category": "Partial",
                    "scenarios": [
                        {
                            "title": "Only Tool A",
                            "prompt": "Run tool A",
                            "agent_workflow": [{"function_name": "tool_a", "parameters": {}}],
                        }
                    ],
                }
            ]
        }
        client = MockClient(canned_responses=partial_response)
        pipeline = SyntheticEvalPipeline(client=client, offline=False)

        interps = [ToolInterpretation(tool_name=t.name, what_it_does=t.description, what_it_needs="", why_its_used="") for t in tools]
        scenarios = pipeline.generate_scenarios(interps, tools=tools, tiers=["simple"])

        # Enforce 100% tool coverage verification
        covered_tools = {step.function_name for sc in scenarios for step in sc.agent_workflow}
        self.assertIn("tool_a", covered_tools)
        self.assertIn("tool_b", covered_tools)
        self.assertIn("tool_c", covered_tools)


class TestSerializationAndDeserializationFidelity(unittest.TestCase):
    """Verifies lossless round-trip serialization for all models and collections."""

    def test_tool_interpretation_serialization_round_trip(self):
        original = ToolInterpretation(
            tool_name="lyria_generate_music",
            what_it_does="Generates musical compositions from text prompts.",
            what_it_needs="Required prompt, optional bpm and key.",
            why_its_used="Background score creation",
            enterprise_context=["Audio Production", "Marketing"],
        )
        d = original.to_dict()
        restored = ToolInterpretation.from_dict(d)

        self.assertEqual(original.tool_name, restored.tool_name)
        self.assertEqual(original.what_it_does, restored.what_it_does)
        self.assertEqual(original.what_it_needs, restored.what_it_needs)
        self.assertEqual(original.why_its_used, restored.why_its_used)
        self.assertEqual(original.enterprise_context, restored.enterprise_context)

        self.assertEqual(restored["tool_name"], "lyria_generate_music")
        self.assertEqual(restored.get("non_existent", "default_val"), "default_val")

    def test_tool_interpretation_unicode_round_trip(self):
        original = ToolInterpretation(
            tool_name="音频处理_🎛️",
            what_it_does="Traitement audio & musique (日本語/한국어/العربية).",
            what_it_needs="Paramètres: {freq: 44100, format: 'wav'}",
            why_its_used="Global localisation 🌍",
            enterprise_context=["Multinational 🌐", "IA Générative"],
        )
        d = original.to_dict()
        restored = ToolInterpretation.from_dict(d)

        self.assertEqual(original.tool_name, restored.tool_name)
        self.assertEqual(original.what_it_does, restored.what_it_does)
        self.assertEqual(original.enterprise_context, restored.enterprise_context)

    def test_tool_interpretation_from_dict_with_string_enterprise_context(self):
        data = {
            "tool_name": "tool_x",
            "what_it_does": "Does X",
            "what_it_needs": "Needs X",
            "why_its_used": "Used for X",
            "enterprise_context": "SingleCategory",
        }
        interp = ToolInterpretation.from_dict(data)
        self.assertEqual(interp.enterprise_context, ["SingleCategory"])

    def test_agent_workflow_step_serialization_round_trip(self):
        original = AgentWorkflowStep(
            function_name="avtool_layer_audio",
            parameters={"audio_tracks": ["gs://b/1.mp3", "gs://b/2.mp3"], "gain_db": -3.5},
            quick_explanation="Layer voiceover on top of background score",
        )
        d = original.to_dict()
        restored = AgentWorkflowStep.from_dict(d)

        self.assertEqual(original.function_name, restored.function_name)
        self.assertEqual(original.parameters, restored.parameters)
        self.assertEqual(original.quick_explanation, restored.quick_explanation)
        self.assertEqual(restored["function_name"], "avtool_layer_audio")

    def test_scenario_serialization_round_trip(self):
        original = Scenario(
            title="Podcast Audio Mix",
            prompt="Mix voiceover with intro music",
            agent_workflow=[
                AgentWorkflowStep(function_name="chirp_tts", parameters={"text": "Intro text"}),
                AgentWorkflowStep(function_name="avtool_layer", parameters={"gain": -2.0}),
            ],
            novelty_reason="Validates audio compositing",
            agent_followup="Should I normalize levels?",
            tier="complex",
            category="Audio Production",
            expected_tools=["chirp_tts", "avtool_layer"],
            injected_fault=None,
            expected_taxonomy=None,
        )
        d = original.to_dict()
        restored = Scenario.from_dict(d)

        self.assertEqual(original.title, restored.title)
        self.assertEqual(original.prompt, restored.prompt)
        self.assertEqual(len(original.agent_workflow), len(restored.agent_workflow))
        self.assertEqual(original.agent_workflow[0].function_name, restored.agent_workflow[0].function_name)
        self.assertEqual(original.agent_workflow[1].parameters, restored.agent_workflow[1].parameters)
        self.assertEqual(original.tier, restored.tier)
        self.assertEqual(original.category, restored.category)
        self.assertEqual(original.expected_tools, restored.expected_tools)

        self.assertEqual(restored["title"], "Podcast Audio Mix")
        self.assertIsInstance(restored["agent_workflow"], list)
        self.assertEqual(restored["agent_workflow"][0]["function_name"], "chirp_tts")

    def test_scenario_collection_dual_access_semantics(self):
        sc1 = Scenario(title="S1", prompt="P1", agent_workflow=[], tier="simple", category="Cat A")
        sc2 = Scenario(title="S2", prompt="P2", agent_workflow=[], tier="complex", category="Cat B")
        sc3 = Scenario(title="S3", prompt="P3", agent_workflow=[], tier="simple", category="Cat A")

        collection = ScenarioCollection([sc1, sc2, sc3])

        self.assertEqual(len(collection), 3)
        self.assertEqual(collection[0].title, "S1")
        self.assertEqual(collection[1].title, "S2")
        self.assertEqual([s.title for s in collection], ["S1", "S2", "S3"])

        self.assertIn("categories", collection)
        cats = collection["categories"]
        self.assertEqual(len(cats), 2)
        cat_a = next(c for c in cats if c["category"] == "Cat A")
        self.assertEqual(len(cat_a["scenarios"]), 2)
        self.assertEqual(collection.get("categories")[0]["category"], "Cat A")
        self.assertIsNone(collection.get("unknown_key"))

    def test_grounded_mock_scenario_round_trip(self):
        sc = Scenario(title="Grounded Test", prompt="Run tool", agent_workflow=[])
        mock_call = GroundedMockCall(
            function_name="veo_generate",
            parameters={"prompt": "nature clip"},
            quick_explanation="Generate clip",
            mock_output={"video_uri": "gs://b/nature.mp4"},
            confidence="high",
            expected_response={"summary": "Rendered nature video."},
        )
        mock_sc = GroundedMockScenario(
            scenario_title="Grounded Test",
            tier="simple",
            scenario=sc,
            mock_workflow=[mock_call],
        )

        d = mock_sc.to_dict()
        restored = GroundedMockScenario.from_dict(d)

        self.assertEqual(mock_sc.scenario_title, restored.scenario_title)
        self.assertEqual(mock_sc.tier, restored.tier)
        self.assertEqual(len(mock_sc.mock_workflow), len(restored.mock_workflow))
        self.assertEqual(restored.mock_workflow[0].confidence, "high")
        self.assertEqual(restored.mock_workflow[0].mock_output["video_uri"], "gs://b/nature.mp4")
        self.assertEqual(restored["mock_workflow"][0]["confidence"], "high")

    def test_multi_turn_transcript_serialization_and_to_text(self):
        turn1 = ConversationTurn(
            turn_index=1,
            user_message="Generate background music for a tech ad.",
            agent_tool_calls=[ToolCall(name="lyria_generate", arguments={"prompt": "electronic synth"})],
            tool_responses=[{"tool_name": "lyria_generate", "output": {"uri": "gs://b/track1.mp3"}}],
            agent_response="I composed your electronic synth track at gs://b/track1.mp3.",
        )
        turn2 = ConversationTurn(
            turn_index=2,
            user_message="Lower the tempo to 90 BPM.",
            agent_tool_calls=[ToolCall(name="lyria_generate", arguments={"prompt": "electronic synth", "bpm": 90})],
            tool_responses=[{"tool_name": "lyria_generate", "output": {"uri": "gs://b/track2.mp3"}}],
            agent_response="Here is the slower version at 90 BPM: gs://b/track2.mp3.",
        )
        transcript = MultiTurnTranscript(
            scenario_title="Tech Ad Music",
            tier="simple",
            turns=[turn1, turn2],
            held_out_workflow=[AgentWorkflowStep(function_name="lyria_generate", parameters={"bpm": 90})],
        )

        d = transcript.to_dict()
        restored = MultiTurnTranscript.from_dict(d)

        self.assertEqual(transcript.scenario_title, restored.scenario_title)
        self.assertEqual(len(transcript.turns), len(restored.turns))
        self.assertEqual(restored.turns[0].agent_tool_calls[0].name, "lyria_generate")
        self.assertEqual(restored.turns[1].agent_tool_calls[0].arguments["bpm"], 90)

        text = transcript.to_text()
        self.assertIn("Turn 1:", text)
        self.assertIn("USER: Generate background music for a tech ad.", text)
        self.assertIn("AGENT TOOL CALLS: lyria_generate(", text)
        self.assertIn("ASSISTANT: I composed your electronic synth track", text)
        self.assertIn("Turn 2:", text)
        self.assertIn("USER: Lower the tempo to 90 BPM.", text)

    def test_multi_turn_transcript_pure_dialogue_without_tool_calls(self):
        turn = ConversationTurn(
            turn_index=1,
            user_message="Hello, can you help me?",
            agent_tool_calls=[],
            tool_responses=[],
            agent_response="Hello! I am ready to assist with tool calling tasks.",
        )
        transcript = MultiTurnTranscript(scenario_title="Greeting", tier="simple", turns=[turn])
        text = transcript.to_text()
        self.assertIn("Turn 1:", text)
        self.assertIn("USER: Hello, can you help me?", text)
        self.assertNotIn("AGENT TOOL CALLS:", text)
        self.assertIn("ASSISTANT: Hello! I am ready to assist", text)

    def test_synthetic_harness_complete_round_trip(self):
        harness = SyntheticHarness(
            server_name="full-suite",
            interpretations=[ToolInterpretation(tool_name="tool_1", what_it_does="does 1", what_it_needs="", why_its_used="")],
            scenarios=[Scenario(title="Sc 1", prompt="Prompt 1", agent_workflow=[AgentWorkflowStep(function_name="tool_1")])],
            mock_scenarios=[GroundedMockScenario(scenario_title="Sc 1", tier="simple", scenario=Scenario(title="Sc 1", prompt="P", agent_workflow=[]), mock_workflow=[])],
            transcripts=[MultiTurnTranscript(scenario_title="Sc 1", tier="simple", turns=[ConversationTurn(turn_index=1, user_message="P", agent_response="A")])],
            metadata={"seed": 42},
        )
        d = harness.to_dict()
        self.assertEqual(d["server_name"], "full-suite")
        self.assertEqual(len(d["interpretations"]), 1)
        self.assertEqual(len(d["scenarios"]), 1)
        self.assertEqual(len(d["mock_scenarios"]), 1)
        self.assertEqual(len(d["transcripts"]), 1)
        self.assertEqual(d["metadata"]["seed"], 42)


class TestDatasetExportFilesystemErrors(unittest.TestCase):
    """Adversarial stress testing of dataset export under abnormal filesystem conditions."""

    def setUp(self):
        self.harness = SyntheticHarness(
            server_name="test-server",
            interpretations=[
                ToolInterpretation(
                    tool_name="test_tool",
                    what_it_does="Testing tool",
                    what_it_needs="none",
                    why_its_used="Validation",
                )
            ],
            scenarios=[
                Scenario(
                    title="Test Scenario",
                    prompt="Test prompt",
                    agent_workflow=[AgentWorkflowStep(function_name="test_tool", parameters={})],
                )
            ],
            mock_scenarios=[],
            transcripts=[],
            metadata={"version": "1.0.0"},
        )

    def test_export_creates_missing_nested_directories(self):
        temp_base = tempfile.mkdtemp(prefix="seer_deep_dir_")
        try:
            deep_output_dir = os.path.join(temp_base, "level1", "level2", "level3", "export")
            paths = self.harness.export_json(deep_output_dir)

            self.assertTrue(os.path.isdir(deep_output_dir))
            for key, path in paths.items():
                self.assertTrue(os.path.exists(path), f"File not found: {path}")
                with open(path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    self.assertIsNotNone(content)
        finally:
            shutil.rmtree(temp_base, ignore_errors=True)

    def test_export_to_read_only_directory_raises_permission_error(self):
        temp_base = tempfile.mkdtemp(prefix="seer_readonly_")
        ro_dir = os.path.join(temp_base, "ro_target")
        os.makedirs(ro_dir, exist_ok=True)
        os.chmod(ro_dir, stat.S_IREAD | stat.S_IXUSR)

        try:
            with self.assertRaises((PermissionError, OSError)):
                self.harness.export_json(ro_dir)
        finally:
            os.chmod(ro_dir, stat.S_IWRITE | stat.S_IREAD | stat.S_IXUSR)
            shutil.rmtree(temp_base, ignore_errors=True)

    def test_export_when_target_is_an_existing_file_raises_os_error(self):
        temp_base = tempfile.mkdtemp(prefix="seer_file_collision_")
        try:
            file_as_dir = os.path.join(temp_base, "existing_file.txt")
            with open(file_as_dir, "w", encoding="utf-8") as f:
                f.write("I am a file, not a directory.")

            with self.assertRaises((FileExistsError, NotADirectoryError, OSError)):
                self.harness.export_json(file_as_dir)
        finally:
            shutil.rmtree(temp_base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
