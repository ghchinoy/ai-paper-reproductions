"""Deterministic Pre-Pass Capability & Schema Linter Engine (arXiv:2608.26133)."""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Set, Union

from .discovery import load_registry, load_server_directory
from .models import (
    CapabilityMatrix,
    LintError,
    LintResult,
    LintViolation,
    ServerSpec,
    Severity,
    ToolCall,
    ToolDefinition,
    ToolParameter,
)

# Built-in fallback tool definitions and capability matrices for standalone usage
_DEFAULT_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "veo": {
        "veo-2.0-generate-001": {
            "SupportsGenerateAudio": False,
            "SupportedAspectRatios": ["16:9", "9:16"],
            "SupportsFirstLastFrame": False,
            "SupportsReferenceImage": False,
        },
        "veo-3.0-generate-001": {
            "SupportsGenerateAudio": False,
            "SupportedAspectRatios": ["16:9", "9:16"],
            "SupportsFirstLastFrame": True,
            "SupportsReferenceImage": False,
        },
        "veo-3.1-generate-001": {
            "SupportsGenerateAudio": True,
            "SupportedAspectRatios": ["16:9", "9:16"],
            "SupportsFirstLastFrame": True,
            "SupportsReferenceImage": True,
        },
        "veo-3.1-generate-preview": {
            "SupportsGenerateAudio": True,
            "SupportedAspectRatios": ["16:9", "9:16"],
            "SupportsFirstLastFrame": True,
            "SupportsReferenceImage": True,
        },
    },
    "nanobanana": {
        "gemini-2.5-flash-image": {
            "SupportedImageSizes": ["1K", "2K"],
            "SupportedAspectRatios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        },
        "gemini-3.1-flash-lite-image": {
            "SupportedImageSizes": ["1K"],
            "SupportedAspectRatios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        },
        "gemini-3-pro-image": {
            "SupportedImageSizes": ["1K", "2K", "4K"],
            "SupportedAspectRatios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "1:4", "4:1"],
        },
    },
    "lyria": {
        "models": ["lyria-1.0-generate", "lyria-2.0-generate", "lyria-default"],
    },
    "avtool": {
        "max_gif_fps": 60,
    },
    "chirp": {
        "supported_encodings": ["LINEAR16", "MP3", "OGG_OPUS", "ALAW", "MULAW"],
    },
}

_DEFAULT_TOOLS: Dict[str, ToolDefinition] = {
    "veo_t2v": ToolDefinition(
        name="veo_t2v",
        description="Generates video from text prompt using Google Veo.",
        parameters={
            "prompt": ToolParameter(name="prompt", type="string", required=True),
            "model": ToolParameter(name="model", type="string", required=False),
            "aspect_ratio": ToolParameter(name="aspect_ratio", type="string", required=False, enum=["16:9", "9:16"]),
            "duration_seconds": ToolParameter(name="duration_seconds", type="integer", required=False),
            "generate_audio": ToolParameter(name="generate_audio", type="boolean", required=False),
        },
    ),
    "veo_i2v": ToolDefinition(
        name="veo_i2v",
        description="Generates video from image and prompt.",
        parameters={
            "prompt": ToolParameter(name="prompt", type="string", required=True),
            "image_uri": ToolParameter(name="image_uri", type="string", required=True),
            "model": ToolParameter(name="model", type="string", required=False),
            "aspect_ratio": ToolParameter(name="aspect_ratio", type="string", required=False),
        },
    ),
    "veo_first_last_to_video": ToolDefinition(
        name="veo_first_last_to_video",
        description="Generates video interpolated between first and last frame.",
        parameters={
            "prompt": ToolParameter(name="prompt", type="string", required=True),
            "first_frame_uri": ToolParameter(name="first_frame_uri", type="string", required=True),
            "last_frame_uri": ToolParameter(name="last_frame_uri", type="string", required=True),
            "model": ToolParameter(name="model", type="string", required=False),
        },
    ),
    "veo_reference_to_video": ToolDefinition(
        name="veo_reference_to_video",
        description="Generates video conditioned on reference character/object image.",
        parameters={
            "prompt": ToolParameter(name="prompt", type="string", required=True),
            "reference_image_uri": ToolParameter(name="reference_image_uri", type="string", required=True),
            "model": ToolParameter(name="model", type="string", required=False),
        },
    ),
    "nanobanana_image_generation": ToolDefinition(
        name="nanobanana_image_generation",
        description="Generates images from prompt using NanoBanana / Imagen.",
        parameters={
            "prompt": ToolParameter(name="prompt", type="string", required=True),
            "model": ToolParameter(name="model", type="string", required=False),
            "aspect_ratio": ToolParameter(name="aspect_ratio", type="string", required=False),
            "image_size": ToolParameter(name="image_size", type="string", required=False),
        },
    ),
    "lyria_generate_music": ToolDefinition(
        name="lyria_generate_music",
        description="Composes instrumental music and soundtrack from prompt.",
        parameters={
            "prompt": ToolParameter(name="prompt", type="string", required=True),
            "sample_count": ToolParameter(name="sample_count", type="integer", required=False),
            "model_id": ToolParameter(name="model_id", type="string", required=False),
            "bpm": ToolParameter(name="bpm", type="integer", required=False),
        },
    ),
    "ffmpeg_video_to_gif": ToolDefinition(
        name="ffmpeg_video_to_gif",
        description="Converts video clip to animated GIF.",
        parameters={
            "input_video_uri": ToolParameter(name="input_video_uri", type="string", required=True),
            "fps": ToolParameter(name="fps", type="integer", required=False),
        },
    ),
    "chirp_tts": ToolDefinition(
        name="chirp_tts",
        description="Synthesizes expressive text to speech using Google Chirp.",
        parameters={
            "text": ToolParameter(name="text", type="string", required=True),
            "encoding": ToolParameter(name="encoding", type="string", required=False),
            "voice": ToolParameter(name="voice", type="string", required=False),
        },
    ),
}


class DeterministicLinter:
    """Sub-millisecond static schema and model-capability contract validator."""

    def __init__(
        self,
        tools: Optional[Union[List[Any], Dict[str, Any]]] = None,
        capabilities: Optional[Union[Dict[str, Any], CapabilityMatrix]] = None,
        servers_dir: Optional[str] = None,
    ):
        self._tool_cache: Dict[str, ToolDefinition] = dict(_DEFAULT_TOOLS)
        self.capabilities: Dict[str, Any] = dict(_DEFAULT_CAPABILITIES)

        DEFAULT_SERVERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "spike", "servers"))
        if not tools and not servers_dir and os.path.exists(DEFAULT_SERVERS_DIR):
            servers_dir = DEFAULT_SERVERS_DIR

        if servers_dir and os.path.exists(servers_dir):
            registry = load_registry(servers_dir)
            for sname, spec in registry.items():
                for t in spec.tools:
                    self._tool_cache[t.name] = t
                if spec.capabilities:
                    self.capabilities[sname] = spec.capabilities

        if tools:
            if isinstance(tools, dict):
                raw_tools = list(tools.values())
            else:
                raw_tools = tools
            for t in raw_tools:
                if t is None:
                    continue
                if isinstance(t, ToolDefinition):
                    self._tool_cache[t.name] = t
                elif isinstance(t, dict):
                    self._tool_cache[t.get("name", "")] = ToolDefinition.from_mcp_tool(t)

        if capabilities:
            caps_dict = capabilities.to_dict() if hasattr(capabilities, "to_dict") else capabilities
            if isinstance(caps_dict, dict):
                self.capabilities.update(caps_dict)

    @property
    def schemas(self) -> Dict[str, Dict[str, Any]]:
        """Dictionary of tool schemas for compatibility."""
        return {name: t.to_dict() for name, t in self._tool_cache.items()}

    def lint_call(self, call: Union[Dict[str, Any], ToolCall], index: int = 0) -> List[LintViolation]:
        """Lints a single tool call and returns a list of LintViolations."""
        violations: List[LintViolation] = []

        if isinstance(call, ToolCall):
            fname = call.name
            params = call.arguments
        elif isinstance(call, dict):
            fname = call.get("function_name", call.get("name"))
            params = call.get("parameters", call.get("arguments", {}))
        else:
            violations.append(
                LintViolation(
                    call_index=index,
                    tool_name="unknown",
                    rule_id="malformed_call",
                    message="Tool call must be a dict or ToolCall instance",
                    severity=Severity.ERROR,
                )
            )
            return violations

        # Phase 1: Tool existence & unhashable type check
        if not fname or not isinstance(fname, str):
            violations.append(
                LintViolation(
                    call_index=index,
                    tool_name=str(fname) if fname is not None else "",
                    rule_id="malformed_call",
                    message="Tool call missing valid 'function_name' string",
                    severity=Severity.ERROR,
                )
            )
            return violations

        if fname not in self._tool_cache:
            violations.append(
                LintViolation(
                    call_index=index,
                    tool_name=fname,
                    rule_id="unknown_tool",
                    message=f"Tool '{fname}' not found in registered MCP schemas",
                    severity=Severity.ERROR,
                )
            )
            return violations

        tool_def = self._tool_cache[fname]
        prop_defs = tool_def.parameters
        required_params = {pname for pname, p in prop_defs.items() if p.required}

        if not isinstance(params, dict):
            violations.append(
                LintViolation(
                    call_index=index,
                    tool_name=fname,
                    rule_id="type_mismatch",
                    message=f"Tool arguments must be a dict, got {type(params).__name__}",
                    severity=Severity.ERROR,
                )
            )
            return violations

        # Phase 2: Required parameters check
        for req in required_params:
            if req not in params or params[req] is None or params[req] == "":
                violations.append(
                    LintViolation(
                        call_index=index,
                        tool_name=fname,
                        parameter_name=req,
                        rule_id="missing_required",
                        message=f"Required parameter '{req}' is missing or empty",
                        severity=Severity.ERROR,
                    )
                )

        # Phase 3 & 4 & 5: Unknown params, Types, Enums, URIs
        for p_name, p_val in params.items():
            if p_name not in prop_defs:
                violations.append(
                    LintViolation(
                        call_index=index,
                        tool_name=fname,
                        parameter_name=p_name,
                        rule_id="unknown_param",
                        message=f"Parameter '{p_name}' not in schema. Allowed: {list(prop_defs.keys())}",
                        severity=Severity.ERROR,
                    )
                )
                continue

            param_spec = prop_defs[p_name]
            exp_type = param_spec.type.lower() if param_spec.type else "string"

            # Type check
            if exp_type == "string" and not isinstance(p_val, str):
                violations.append(
                    LintViolation(
                        call_index=index,
                        tool_name=fname,
                        parameter_name=p_name,
                        rule_id="type_mismatch",
                        message=f"Parameter '{p_name}' expected string, got {type(p_val).__name__}",
                        severity=Severity.ERROR,
                    )
                )
            elif exp_type in ("integer", "number"):
                if isinstance(p_val, bool) or not isinstance(p_val, (int, float)):
                    violations.append(
                        LintViolation(
                            call_index=index,
                            tool_name=fname,
                            parameter_name=p_name,
                            rule_id="type_mismatch",
                            message=f"Parameter '{p_name}' expected {exp_type}, got {type(p_val).__name__}",
                            severity=Severity.ERROR,
                        )
                    )
            elif exp_type == "boolean" and not isinstance(p_val, bool):
                violations.append(
                    LintViolation(
                        call_index=index,
                        tool_name=fname,
                        parameter_name=p_name,
                        rule_id="type_mismatch",
                        message=f"Parameter '{p_name}' expected boolean, got {type(p_val).__name__}",
                        severity=Severity.ERROR,
                    )
                )
            elif exp_type == "array" and not isinstance(p_val, list):
                violations.append(
                    LintViolation(
                        call_index=index,
                        tool_name=fname,
                        parameter_name=p_name,
                        rule_id="type_mismatch",
                        message=f"Parameter '{p_name}' expected array, got {type(p_val).__name__}",
                        severity=Severity.ERROR,
                    )
                )
            elif exp_type == "object" and not isinstance(p_val, dict):
                violations.append(
                    LintViolation(
                        call_index=index,
                        tool_name=fname,
                        parameter_name=p_name,
                        rule_id="type_mismatch",
                        message=f"Parameter '{p_name}' expected object, got {type(p_val).__name__}",
                        severity=Severity.ERROR,
                    )
                )

            # Enum check (safely handling unhashable types)
            if param_spec.enum:
                try:
                    if p_val not in param_spec.enum:
                        violations.append(
                            LintViolation(
                                call_index=index,
                                tool_name=fname,
                                parameter_name=p_name,
                                rule_id="illegal_enum",
                                message=f"Value '{p_val}' not in allowed enum: {param_spec.enum}",
                                severity=Severity.ERROR,
                            )
                        )
                except TypeError:
                    violations.append(
                        LintViolation(
                            call_index=index,
                            tool_name=fname,
                            parameter_name=p_name,
                            rule_id="illegal_enum",
                            message=f"Unhashable value '{p_val}' not in allowed enum: {param_spec.enum}",
                            severity=Severity.ERROR,
                        )
                    )

            # URI check
            if ("uri" in p_name or "gcs_bucket" in p_name) and isinstance(p_val, str):
                if p_name in ("image_uri", "video_uri", "input_audio_uri", "input_video_uri", "first_frame_uri", "last_frame_uri", "reference_image_uri"):
                    if not (p_val.startswith("gs://") or p_val.startswith("/") or p_val.startswith("file://") or p_val.startswith("s3://") or p_val.startswith("http://") or p_val.startswith("https://")):
                        violations.append(
                            LintViolation(
                                call_index=index,
                                tool_name=fname,
                                parameter_name=p_name,
                                rule_id="invalid_uri",
                                message=f"URI '{p_val}' must be absolute path, gs://, s3://, or http(s):// URI",
                                severity=Severity.ERROR,
                            )
                        )

        # Phase 6: Model capability contract rules
        violations.extend(self._lint_capabilities(index, fname, params))

        return violations

    def _lint_capabilities(self, idx: int, fname: str, params: Dict[str, Any]) -> List[LintViolation]:
        cap_violations: List[LintViolation] = []

        # Veo capability rules
        if fname.startswith("veo_"):
            veo_caps = self.capabilities.get("veo", {})
            model = params.get("model")
            if model:
                if model not in veo_caps:
                    cap_violations.append(
                        LintViolation(
                            call_index=idx,
                            tool_name=fname,
                            parameter_name="model",
                            rule_id="unknown_model",
                            message=f"Unknown Veo model '{model}'",
                            severity=Severity.ERROR,
                        )
                    )
                else:
                    mc = veo_caps[model]
                    if params.get("generate_audio") is True:
                        sup_audio = str(mc.get("SupportsGenerateAudio")).lower() == "true" or mc.get("SupportsGenerateAudio") is True
                        if not sup_audio:
                            cap_violations.append(
                                LintViolation(
                                    call_index=idx,
                                    tool_name=fname,
                                    parameter_name="generate_audio",
                                    rule_id="capability_violation",
                                    message=f"Model '{model}' does not support audio generation",
                                    severity=Severity.CAPABILITY_VIOLATION,
                                )
                            )
                    aspect = params.get("aspect_ratio")
                    if aspect:
                        supported = mc.get("SupportedAspectRatios", [])
                        if isinstance(supported, str):
                            supported = ["16:9", "9:16"] if "9:16" in supported else ["16:9"]
                        if aspect not in supported:
                            cap_violations.append(
                                LintViolation(
                                    call_index=idx,
                                    tool_name=fname,
                                    parameter_name="aspect_ratio",
                                    rule_id="capability_violation",
                                    message=f"Aspect ratio '{aspect}' unsupported on '{model}'. Supported: {supported}",
                                    severity=Severity.CAPABILITY_VIOLATION,
                                )
                            )
                    if fname == "veo_first_last_to_video":
                        sup_fl = str(mc.get("SupportsFirstLast", mc.get("SupportsFirstLastFrame", "false"))).lower() == "true" or mc.get("SupportsFirstLastFrame") is True or mc.get("SupportsFirstLast") is True
                        if not sup_fl:
                            cap_violations.append(
                                LintViolation(
                                    call_index=idx,
                                    tool_name=fname,
                                    parameter_name="model",
                                    rule_id="capability_violation",
                                    message=f"Model '{model}' does not support first/last frame generation",
                                    severity=Severity.CAPABILITY_VIOLATION,
                                )
                            )
                    if fname == "veo_reference_to_video":
                        sup_ref = str(mc.get("SupportsReferenceImage", "false")).lower() == "true" or mc.get("SupportsReferenceImage") is True
                        if not sup_ref:
                            cap_violations.append(
                                LintViolation(
                                    call_index=idx,
                                    tool_name=fname,
                                    parameter_name="model",
                                    rule_id="capability_violation",
                                    message=f"Model '{model}' does not support reference image conditioning",
                                    severity=Severity.CAPABILITY_VIOLATION,
                                )
                            )

        # Nanobanana capability rules
        elif fname == "nanobanana_image_generation":
            nb_caps = self.capabilities.get("nanobanana", {})
            model = params.get("model")
            if model:
                if model not in nb_caps:
                    cap_violations.append(
                        LintViolation(
                            call_index=idx,
                            tool_name=fname,
                            parameter_name="model",
                            rule_id="unknown_model",
                            message=f"Unknown NanoBanana model '{model}'",
                            severity=Severity.ERROR,
                        )
                    )
                else:
                    mc = nb_caps[model]
                    img_size = params.get("image_size")
                    if img_size and img_size not in mc.get("SupportedImageSizes", []):
                        cap_violations.append(
                            LintViolation(
                                call_index=idx,
                                tool_name=fname,
                                parameter_name="image_size",
                                rule_id="capability_violation",
                                message=f"image_size '{img_size}' unsupported on '{model}'. Supported: {mc.get('SupportedImageSizes')}",
                                severity=Severity.CAPABILITY_VIOLATION,
                            )
                        )
                    aspect = params.get("aspect_ratio")
                    if aspect and aspect not in mc.get("SupportedAspectRatios", []):
                        cap_violations.append(
                            LintViolation(
                                call_index=idx,
                                tool_name=fname,
                                parameter_name="aspect_ratio",
                                rule_id="capability_violation",
                                message=f"aspect_ratio '{aspect}' unsupported on '{model}'. Supported: {mc.get('SupportedAspectRatios')}",
                                severity=Severity.CAPABILITY_VIOLATION,
                            )
                        )

        # Lyria capability rules
        elif fname == "lyria_generate_music":
            lyria_caps = self.capabilities.get("lyria", {})
            model_id = params.get("model_id")
            if model_id:
                known_models = lyria_caps.get("models", ["lyria-1.0-generate", "lyria-2.0-generate", "lyria-default"])
                if model_id not in known_models:
                    cap_violations.append(
                        LintViolation(
                            call_index=idx,
                            tool_name=fname,
                            parameter_name="model_id",
                            rule_id="unknown_model",
                            message=f"Unknown Lyria model '{model_id}'",
                            severity=Severity.ERROR,
                        )
                    )
            sample_count = params.get("sample_count")
            if isinstance(sample_count, (int, float)) and not isinstance(sample_count, bool):
                if sample_count < 1:
                    cap_violations.append(
                        LintViolation(
                            call_index=idx,
                            tool_name=fname,
                            parameter_name="sample_count",
                            rule_id="invalid_value",
                            message=f"sample_count must be >= 1, got {sample_count}",
                            severity=Severity.ERROR,
                        )
                    )

        # FFmpeg video to gif
        elif fname == "ffmpeg_video_to_gif":
            fps = params.get("fps")
            if isinstance(fps, (int, float)) and not isinstance(fps, bool):
                if fps > 60 or fps < 1:
                    cap_violations.append(
                        LintViolation(
                            call_index=idx,
                            tool_name=fname,
                            parameter_name="fps",
                            rule_id="capability_violation",
                            message=f"fps must be between 1 and 60, got {fps}",
                            severity=Severity.CAPABILITY_VIOLATION,
                        )
                    )

        # Chirp TTS
        elif fname == "chirp_tts":
            encoding = params.get("encoding")
            if encoding:
                valid_encodings = self.capabilities.get("chirp", {}).get("supported_encodings", ["LINEAR16", "MP3", "OGG_OPUS", "ALAW", "MULAW"])
                if encoding not in valid_encodings:
                    cap_violations.append(
                        LintViolation(
                            call_index=idx,
                            tool_name=fname,
                            parameter_name="encoding",
                            rule_id="capability_violation",
                            message=f"Encoding '{encoding}' unsupported. Allowed: {valid_encodings}",
                            severity=Severity.CAPABILITY_VIOLATION,
                        )
                    )

        return cap_violations

    def lint(self, calls: List[Union[Dict[str, Any], ToolCall]]) -> LintResult:
        """Lints a sequence of tool calls and computes aggregate metrics."""
        t0 = time.perf_counter()
        violations: List[LintViolation] = []

        if not isinstance(calls, list):
            calls = [calls]

        for idx, call in enumerate(calls):
            violations.extend(self.lint_call(call, index=idx))

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        is_valid = len(violations) == 0

        # Group by rule_id and severity
        by_rule: Dict[str, List[LintViolation]] = {}
        for v in violations:
            by_rule.setdefault(v.rule_id, []).append(v)

        return LintResult(
            is_valid=is_valid,
            total_calls=len(calls),
            total_violations=len(violations),
            violations=violations,
            violations_by_rule=by_rule,
            latency_ms=elapsed_ms,
        )


# Class alias for backward compatibility
DeterministicCapabilityLinter = DeterministicLinter
