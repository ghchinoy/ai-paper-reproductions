"""Unit and boundary tests for agent_seer.models.

Covers:
- ToolParameter (basic types, enums, nested properties, boundary validation)
- ToolDefinition (parameters mapping, capability attachment, schema representation)
- ToolCall (attribute access, aliases, ID tracking, payload integrity)
- LintViolation / LintError & LintResult (serialization, error categories, severities)
- ToolCallingScores & CoherenceScores (subdimension bounds, optional ordering/history)
- ServerSpec (multi-source server specifications)
"""
import os
import sys
import unittest

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

try:
    from agent_seer.models import (
        CoherenceScores,
        LintResult,
        LintViolation,
        ServerSpec,
        ToolCall,
        ToolCallingScores,
        ToolDefinition,
        ToolParameter,
    )
except ImportError:
    # Fallback to spike or direct import if package not yet installed in site-packages
    from agent_seer.models import (
        CoherenceScores,
        LintResult,
        LintViolation,
        ServerSpec,
        ToolCall,
        ToolCallingScores,
        ToolDefinition,
        ToolParameter,
    )


class TestToolParameter(unittest.TestCase):
    """Tier 1 & Tier 2 tests for ToolParameter data model."""

    def test_basic_parameter_creation(self):
        """Tier 1: Happy path creation of basic required string parameter."""
        param = ToolParameter(
            name="prompt",
            type="string",
            description="The text prompt describing video generation",
            required=True,
        )
        self.assertEqual(param.name, "prompt")
        self.assertEqual(param.type, "string")
        self.assertEqual(param.description, "The text prompt describing video generation")
        self.assertTrue(param.required)
        self.assertIsNone(param.enum)
        self.assertIsNone(param.properties)

    def test_enum_parameter_creation(self):
        """Tier 1: Parameter with enum constraints."""
        aspect_ratios = ["16:9", "9:16", "1:1"]
        param = ToolParameter(
            name="aspect_ratio",
            type="string",
            description="Video aspect ratio",
            required=False,
            enum=aspect_ratios,
        )
        self.assertEqual(param.enum, ["16:9", "9:16", "1:1"])
        self.assertFalse(param.required)

    def test_nested_object_parameter(self):
        """Tier 1: Parameter with complex nested object properties."""
        nested_props = {
            "width": {"type": "integer", "description": "Width in pixels"},
            "height": {"type": "integer", "description": "Height in pixels"},
        }
        param = ToolParameter(
            name="resolution",
            type="object",
            description="Output resolution dimensions",
            required=False,
            properties=nested_props,
        )
        self.assertEqual(param.type, "object")
        self.assertEqual(param.properties, nested_props)

    def test_parameter_boundary_empty_fields(self):
        """Tier 2: Parameter boundary testing with empty string values and empty lists."""
        param = ToolParameter(
            name="",
            type="string",
            description="",
            required=False,
            enum=[],
            properties={},
        )
        self.assertEqual(param.name, "")
        self.assertEqual(param.description, "")
        self.assertEqual(param.enum, [])
        self.assertEqual(param.properties, {})

    def test_parameter_numeric_types(self):
        """Tier 2: Parameter supporting integer and number types."""
        param_int = ToolParameter(name="sample_count", type="integer", description="Number of samples", required=True)
        param_num = ToolParameter(name="fps", type="number", description="Frames per second", required=False)
        self.assertEqual(param_int.type, "integer")
        self.assertEqual(param_num.type, "number")


class TestToolDefinition(unittest.TestCase):
    """Tier 1 & Tier 2 tests for ToolDefinition data model."""

    def test_basic_tool_definition(self):
        """Tier 1: Happy path creation of ToolDefinition."""
        prompt_param = ToolParameter(name="prompt", type="string", description="Prompt", required=True)
        tool = ToolDefinition(
            name="generate_video",
            description="Generates high-definition video from text",
            parameters={"prompt": prompt_param},
        )
        self.assertEqual(tool.name, "generate_video")
        self.assertEqual(tool.description, "Generates high-definition video from text")
        self.assertIn("prompt", tool.parameters)
        self.assertIsNone(tool.capabilities)

    def test_tool_definition_with_capabilities(self):
        """Tier 1: ToolDefinition enriched with backend capability matrix metadata."""
        caps = {
            "supported_models": ["veo-2.0-generate-001", "veo-3.0-generate-001"],
            "max_duration_seconds": 60,
            "supports_audio": False,
        }
        tool = ToolDefinition(
            name="veo_generate_video",
            description="Veo video generation",
            parameters={},
            capabilities=caps,
        )
        self.assertIsNotNone(tool.capabilities)
        self.assertEqual(tool.capabilities["max_duration_seconds"], 60)
        self.assertFalse(tool.capabilities["supports_audio"])

    def test_tool_definition_multiple_parameters(self):
        """Tier 1: ToolDefinition with diverse required and optional parameters."""
        params = {
            "prompt": ToolParameter(name="prompt", type="string", description="Prompt", required=True),
            "model": ToolParameter(name="model", type="string", description="Model ID", required=False, enum=["v1", "v2"]),
            "duration": ToolParameter(name="duration", type="integer", description="Duration", required=False),
        }
        tool = ToolDefinition(name="synth_tool", description="Multi-param tool", parameters=params)
        self.assertEqual(len(tool.parameters), 3)
        self.assertTrue(tool.parameters["prompt"].required)
        self.assertFalse(tool.parameters["duration"].required)

    def test_tool_definition_boundary_empty_parameters(self):
        """Tier 2: Boundary test for parameterless tools (e.g., status/ping tools)."""
        tool = ToolDefinition(name="get_status", description="Get server status", parameters={})
        self.assertEqual(len(tool.parameters), 0)
        self.assertEqual(tool.name, "get_status")

    def test_tool_definition_special_characters(self):
        """Tier 2: Tool definition with unicode descriptions and namespace separators."""
        tool = ToolDefinition(
            name="mcp__audio_synth__v2",
            description="Synthesis with special chars: 𝄞 & 100% fidelity <xml>",
            parameters={},
        )
        self.assertEqual(tool.name, "mcp__audio_synth__v2")
        self.assertIn("𝄞", tool.description)


class TestToolCall(unittest.TestCase):
    """Tier 1 & Tier 2 tests for ToolCall data model."""

    def test_tool_call_creation(self):
        """Tier 1: Happy path ToolCall creation."""
        call = ToolCall(
            name="generate_image",
            arguments={"prompt": "cyberpunk city skyline", "aspect_ratio": "16:9"},
            call_id="call_abc_123",
        )
        self.assertEqual(call.name, "generate_image")
        self.assertEqual(call.arguments["prompt"], "cyberpunk city skyline")
        self.assertEqual(call.call_id, "call_abc_123")

    def test_tool_call_default_call_id(self):
        """Tier 1: ToolCall without explicit call_id defaults to None."""
        call = ToolCall(name="query_database", arguments={"query": "SELECT 1"})
        self.assertIsNone(call.call_id)
        self.assertEqual(call.arguments, {"query": "SELECT 1"})

    def test_tool_call_empty_arguments(self):
        """Tier 2: ToolCall with empty argument dictionary."""
        call = ToolCall(name="get_media_info", arguments={})
        self.assertEqual(call.name, "get_media_info")
        self.assertEqual(call.arguments, {})

    def test_tool_call_nested_complex_arguments(self):
        """Tier 2: ToolCall containing nested lists, dicts, and primitive types."""
        complex_args = {
            "layers": [
                {"source": "gs://bucket/audio1.mp3", "volume": 0.8},
                {"source": "gs://bucket/audio2.mp3", "volume": 0.4},
            ],
            "output_format": "wav",
            "normalize": True,
            "sample_rate": 48000,
        }
        call = ToolCall(name="avtool_layer_audio", arguments=complex_args, call_id="c_42")
        self.assertEqual(len(call.arguments["layers"]), 2)
        self.assertTrue(call.arguments["normalize"])
        self.assertEqual(call.arguments["sample_rate"], 48000)

    def test_tool_call_compatibility_accessors(self):
        """Tier 2: Check standard attribute availability on ToolCall."""
        call = ToolCall(name="test_fn", arguments={"x": 10})
        self.assertEqual(getattr(call, "name", None), "test_fn")
        self.assertEqual(getattr(call, "arguments", None), {"x": 10})


class TestLintViolationAndResult(unittest.TestCase):
    """Tier 1 & Tier 2 tests for LintViolation and LintResult data models."""

    def test_lint_violation_creation(self):
        """Tier 1: Creation of a LintViolation instance."""
        violation = LintViolation(
            tool_name="veo_generate_video",
            parameter_name="generate_audio",
            rule_id="capability_violation",
            message="Veo-2.0 model does not support audio generation",
            severity="ERROR",
        )
        self.assertEqual(violation.tool_name, "veo_generate_video")
        self.assertEqual(violation.parameter_name, "generate_audio")
        self.assertEqual(violation.rule_id, "capability_violation")
        self.assertEqual(violation.severity, "ERROR")

    def test_lint_result_valid(self):
        """Tier 1: LintResult representing a clean pass."""
        result = LintResult(is_valid=True, errors=[], latency_ms=0.005, checked_calls=3)
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(result.checked_calls, 3)
        self.assertLess(result.latency_ms, 0.010)

    def test_lint_result_with_violations(self):
        """Tier 1: LintResult containing multiple violations."""
        v1 = LintViolation("tool_a", "param_1", "missing_required", "Missing required param", "ERROR")
        v2 = LintViolation("tool_b", "model", "unknown_model", "Model not recognized", "ERROR")
        result = LintResult(is_valid=False, errors=[v1, v2], latency_ms=0.008, checked_calls=2)
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 2)

    def test_lint_result_to_dict_serialization(self):
        """Tier 2: LintResult serialization to dictionary for JSON output."""
        v = LintViolation("nanobanana", "image_size", "capability_violation", "4K not supported", "ERROR")
        result = LintResult(is_valid=False, errors=[v], latency_ms=0.004, checked_calls=1)
        res_dict = result.to_dict()
        self.assertIsInstance(res_dict, dict)
        self.assertIn("is_valid", res_dict)
        self.assertIn("errors", res_dict)
        self.assertIn("latency_ms", res_dict)
        self.assertIn("checked_calls", res_dict)
        self.assertFalse(res_dict["is_valid"])
        self.assertEqual(len(res_dict["errors"]), 1)

    def test_lint_violation_null_parameter(self):
        """Tier 2: LintViolation for tool-level errors (e.g. unknown tool) where parameter is None."""
        v = LintViolation(
            tool_name="unregistered_tool",
            parameter_name=None,
            rule_id="unknown_tool",
            message="Tool not found in registry",
            severity="ERROR",
        )
        self.assertIsNone(v.parameter_name)
        self.assertEqual(v.rule_id, "unknown_tool")


class TestScoresDataModels(unittest.TestCase):
    """Tier 1 & Tier 2 tests for ToolCallingScores and CoherenceScores data models."""

    def test_tool_calling_scores_full(self):
        """Tier 1: Full 14-subdimension ToolCallingScores instantiation."""
        tc = ToolCallingScores(
            necessity=1.0,
            overuse_detection=1.0,
            correctness=0.9,
            specificity=0.9,
            completeness_selection=1.0,
            sequence_logic=0.8,
            dependency_handling=0.9,
            execution_efficiency=0.85,
            args_completeness=1.0,
            name_accuracy=1.0,
            value_accuracy=0.95,
            type_compliance=1.0,
            format_compliance=1.0,
            relevancy=0.9,
            overall_tool_calling=0.93,
        )
        self.assertEqual(tc.necessity, 1.0)
        self.assertEqual(tc.sequence_logic, 0.8)
        self.assertEqual(tc.overall_tool_calling, 0.93)

    def test_tool_calling_scores_single_call_none_ordering(self):
        """Tier 1: ToolCallingScores with ordering subdimensions as None (single tool call)."""
        tc = ToolCallingScores(
            necessity=1.0,
            overuse_detection=1.0,
            correctness=1.0,
            specificity=1.0,
            completeness_selection=1.0,
            sequence_logic=None,
            dependency_handling=None,
            execution_efficiency=None,
            args_completeness=1.0,
            name_accuracy=1.0,
            value_accuracy=1.0,
            type_compliance=1.0,
            format_compliance=1.0,
            relevancy=1.0,
            overall_tool_calling=1.0,
        )
        self.assertIsNone(tc.sequence_logic)
        self.assertIsNone(tc.dependency_handling)
        self.assertIsNone(tc.execution_efficiency)
        self.assertEqual(tc.overall_tool_calling, 1.0)

    def test_coherence_scores_full(self):
        """Tier 1: Full 5-subdimension CoherenceScores instantiation."""
        coh = CoherenceScores(
            logical_flow=1.0,
            completeness=0.8,
            conciseness=1.0,
            topic_relevance=1.0,
            context_retention=0.9,
            overall_coherence=0.94,
        )
        self.assertEqual(coh.logical_flow, 1.0)
        self.assertEqual(coh.context_retention, 0.9)
        self.assertEqual(coh.overall_coherence, 0.94)

    def test_coherence_scores_no_history(self):
        """Tier 2: CoherenceScores when context_retention is None (first turn / no prior history)."""
        coh = CoherenceScores(
            logical_flow=0.9,
            completeness=0.9,
            conciseness=0.9,
            topic_relevance=0.9,
            context_retention=None,
            overall_coherence=0.9,
        )
        self.assertIsNone(coh.context_retention)
        self.assertEqual(coh.overall_coherence, 0.9)


class TestServerSpec(unittest.TestCase):
    """Tier 1 & Tier 2 tests for ServerSpec data model."""

    def test_server_spec_creation(self):
        """Tier 1: Creation of ServerSpec data structure."""
        spec = ServerSpec(
            server_name="mcp-veo-go",
            tools=[{"name": "veo_generate_video"}],
            capabilities={"veo-2.0-generate-001": {"supports_audio": False}},
            source="directory",
        )
        self.assertEqual(spec.server_name, "mcp-veo-go")
        self.assertEqual(len(spec.tools), 1)
        self.assertEqual(spec.source, "directory")

    def test_server_spec_boundary_empty(self):
        """Tier 2: ServerSpec with empty tool list and capabilities."""
        spec = ServerSpec(
            server_name="empty-server",
            tools=[],
            capabilities={},
            source="stdio",
        )
        self.assertEqual(spec.server_name, "empty-server")
        self.assertEqual(spec.tools, [])
        self.assertEqual(spec.capabilities, {})
        self.assertEqual(spec.source, "stdio")


if __name__ == "__main__":
    unittest.main()
