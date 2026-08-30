"""Deterministic Pre-Pass Capability & Schema Linter for Generative Media MCP Tool Calls.

Executes sub-millisecond static schema and model-capability validation without invoking LLMs.
Implements the Tier 1 recommendation from the Agent Seer roadmap.
"""
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LintError:
    call_index: int
    tool_name: str
    parameter: Optional[str]
    category: str  # e.g., 'missing_required', 'unknown_param', 'type_mismatch', 'capability_violation', 'illegal_enum'
    message: str
    severity: str = "ERROR"


@dataclass
class LintResult:
    is_valid: bool
    errors: List[LintError] = field(default_factory=list)
    latency_ms: float = 0.0
    checked_calls: int = 0

    def to_dict(self):
        return {
            "is_valid": self.is_valid,
            "errors": [e.__dict__ for e in self.errors],
            "latency_ms": round(self.latency_ms, 3),
            "checked_calls": self.checked_calls,
        }


class DeterministicCapabilityLinter:
    def __init__(self, servers_dir: Optional[str] = None):
        self.servers_dir = servers_dir or os.path.join(os.path.dirname(__file__), "servers")
        self.schemas: Dict[str, Dict[str, Any]] = {}
        self.capabilities: Dict[str, Dict[str, Any]] = {}
        self._load_registry()

    def _load_registry(self):
        """Loads all tools_list.json and capabilities.json across servers."""
        if not os.path.exists(self.servers_dir):
            return

        for sname in os.listdir(self.servers_dir):
            sdir = os.path.join(self.servers_dir, sname)
            if not os.path.isdir(sdir):
                continue

            # Load tools
            tpath = os.path.join(sdir, "tools_list.json")
            if os.path.exists(tpath):
                with open(tpath) as f:
                    data = json.load(f)
                    for t in data.get("tools", []):
                        self.schemas[t["name"]] = t

            # Load capabilities
            cpath = os.path.join(sdir, "capabilities.json")
            if os.path.exists(cpath):
                with open(cpath) as f:
                    self.capabilities[sname] = json.load(f)

    def lint(self, calls: List[Dict[str, Any]]) -> LintResult:
        """Lints an ordered list of agent tool calls."""
        start_time = time.perf_counter()
        errors: List[LintError] = []

        for idx, call in enumerate(calls):
            fname = call.get("function_name")
            params = call.get("parameters", {})

            if not fname:
                errors.append(LintError(idx, "", None, "malformed_call", "Tool call missing 'function_name'"))
                continue

            if fname not in self.schemas:
                errors.append(LintError(idx, fname, None, "unknown_tool", f"Tool '{fname}' not found in registered MCP schemas"))
                continue

            tool_def = self.schemas[fname]
            schema = tool_def.get("inputSchema", {})
            properties = schema.get("properties", {})
            required = set(schema.get("required", []))

            # 1. Required parameters check
            for req in required:
                if req not in params or params[req] is None or params[req] == "":
                    errors.append(LintError(idx, fname, req, "missing_required", f"Required parameter '{req}' is missing"))

            # 2. Unknown / misspelled parameter check
            for p_name, p_val in params.items():
                if p_name not in properties:
                    errors.append(LintError(idx, fname, p_name, "unknown_param", f"Parameter '{p_name}' is not in tool schema. Allowed: {list(properties.keys())}"))
                    continue

                # 3. Type check
                prop_spec = properties[p_name]
                expected_type = prop_spec.get("type")
                if expected_type:
                    if expected_type == "string" and not isinstance(p_val, str):
                        errors.append(LintError(idx, fname, p_name, "type_mismatch", f"Parameter '{p_name}' expected string, got {type(p_val).__name__}"))
                    elif expected_type == "number" and not isinstance(p_val, (int, float)):
                        errors.append(LintError(idx, fname, p_name, "type_mismatch", f"Parameter '{p_name}' expected number, got {type(p_val).__name__}"))
                    elif expected_type == "boolean" and not isinstance(p_val, bool):
                        errors.append(LintError(idx, fname, p_name, "type_mismatch", f"Parameter '{p_name}' expected boolean, got {type(p_val).__name__}"))
                    elif expected_type == "array" and not isinstance(p_val, list):
                        errors.append(LintError(idx, fname, p_name, "type_mismatch", f"Parameter '{p_name}' expected array, got {type(p_val).__name__}"))

                # 4. Enum check
                if "enum" in prop_spec and p_val not in prop_spec["enum"]:
                    errors.append(LintError(idx, fname, p_name, "illegal_enum", f"Value '{p_val}' not in allowed enum: {prop_spec['enum']}"))

                # 5. URI format check
                if ("uri" in p_name or "gcs_bucket" in p_name or "bucket" in p_name) and isinstance(p_val, str):
                    if p_name in ("image_uri", "video_uri", "input_audio_uri", "input_video_uri") and "gs://" not in p_val and not p_val.startswith("/"):
                        errors.append(LintError(idx, fname, p_name, "invalid_uri", f"URI '{p_val}' is invalid. Must be absolute local path or gs:// URI"))

            # 6. Backend Model Capability Contract Validation
            errors.extend(self._lint_capabilities(idx, fname, params))

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return LintResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            latency_ms=elapsed_ms,
            checked_calls=len(calls),
        )

    def _lint_capabilities(self, idx: int, fname: str, params: Dict[str, Any]) -> List[LintError]:
        cap_errors: List[LintError] = []

        # Veo Capability Checks
        if fname.startswith("veo_"):
            veo_caps = self.capabilities.get("veo", {})
            model = params.get("model")
            if model:
                if model not in veo_caps:
                    cap_errors.append(LintError(idx, fname, "model", "unknown_model", f"Veo model '{model}' is not recognized in model registry"))
                else:
                    mc = veo_caps[model]
                    # Check audio support
                    if params.get("generate_audio") is True:
                        sup_audio = str(mc.get("SupportsGenerateAudio")).lower() == "true"
                        if not sup_audio:
                            cap_errors.append(LintError(idx, fname, "generate_audio", "capability_violation", f"Model '{model}' does not support audio generation"))

                    # Check aspect ratio
                    aspect = params.get("aspect_ratio")
                    if aspect:
                        supported_ratios = mc.get("SupportedAspectRatios", [])
                        if isinstance(supported_ratios, str):
                            # parse string representation if present
                            supported_ratios = ["16:9", "9:16"] if "9:16" in supported_ratios else ["16:9"]
                        if aspect not in supported_ratios:
                            cap_errors.append(LintError(idx, fname, "aspect_ratio", "capability_violation", f"Aspect ratio '{aspect}' is not supported on model '{model}'. Supported: {supported_ratios}"))

        # Nanobanana Capability Checks
        elif fname == "nanobanana_image_generation":
            nb_caps = self.capabilities.get("nanobanana", {})
            model = params.get("model")
            if model:
                if model not in nb_caps:
                    cap_errors.append(LintError(idx, fname, "model", "unknown_model", f"Image model '{model}' is not recognized in registry"))
                else:
                    mc = nb_caps[model]
                    # Check image size support
                    img_size = params.get("image_size")
                    if img_size:
                        supported_sizes = mc.get("SupportedImageSizes", [])
                        if img_size not in supported_sizes:
                            cap_errors.append(LintError(idx, fname, "image_size", "capability_violation", f"Model '{model}' does not support image_size '{img_size}'. Supported: {supported_sizes}"))

                    # Check aspect ratio support
                    aspect = params.get("aspect_ratio")
                    if aspect:
                        supported_ratios = mc.get("SupportedAspectRatios", [])
                        if aspect not in supported_ratios:
                            cap_errors.append(LintError(idx, fname, "aspect_ratio", "capability_violation", f"Aspect ratio '{aspect}' is not supported on model '{model}'. Supported: {supported_ratios}"))

        # Lyria Capability Checks
        elif fname == "lyria_generate_music":
            lyria_caps = self.capabilities.get("lyria", {})
            model_id = params.get("model_id")
            if model_id and model_id not in lyria_caps:
                cap_errors.append(LintError(idx, fname, "model_id", "unknown_model", f"Lyria model '{model_id}' is not recognized in registry"))

            sample_count = params.get("sample_count")
            if sample_count is not None and isinstance(sample_count, (int, float)) and sample_count < 1:
                cap_errors.append(LintError(idx, fname, "sample_count", "invalid_value", f"sample_count must be >= 1, got {sample_count}"))

        return cap_errors
