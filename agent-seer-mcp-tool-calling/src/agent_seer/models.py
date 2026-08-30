"""Data models and type definitions for Agent Seer.

Defines standardized dataclasses and schemas for MCP tool definitions, tool calls,
lint violations, scoring rubrics, and evaluation results.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class Severity(str, Enum):
    """Severity levels for linting violations."""
    ERROR = "ERROR"
    WARNING = "WARNING"
    CAPABILITY_VIOLATION = "CAPABILITY_VIOLATION"
    INFO = "INFO"


@dataclass
class ToolParameter:
    """Specification of a single parameter in an MCP tool input schema."""
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    enum: Optional[List[Any]] = None
    properties: Optional[Dict[str, Any]] = None
    items: Optional[Dict[str, Any]] = None
    default: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert parameter to dictionary schema format."""
        d: Dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
        }
        if self.enum is not None:
            d["enum"] = self.enum
        if self.properties is not None:
            d["properties"] = self.properties
        if self.items is not None:
            d["items"] = self.items
        if self.default is not None:
            d["default"] = self.default
        return d

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any], required: bool = False) -> ToolParameter:
        """Construct a ToolParameter from a JSON Schema property dict."""
        return cls(
            name=name,
            type=data.get("type", "string"),
            description=data.get("description", ""),
            required=required or data.get("required", False),
            enum=data.get("enum"),
            properties=data.get("properties"),
            items=data.get("items"),
            default=data.get("default"),
        )


@dataclass
class ToolDefinition:
    """Standardized representation of an MCP tool specification."""
    name: str
    description: str = ""
    parameters: Dict[str, ToolParameter] = field(default_factory=dict)
    input_schema: Optional[Dict[str, Any]] = None
    capabilities: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert tool definition to JSON-compatible dictionary."""
        props: Dict[str, Any] = {}
        required: List[str] = []

        for p_name, p_def in self.parameters.items():
            param_dict = p_def.to_dict()
            param_dict.pop("name", None)
            is_req = param_dict.pop("required", False)
            if is_req:
                required.append(p_name)
            props[p_name] = param_dict

        schema = self.input_schema or {
            "type": "object",
            "properties": props,
            "required": required,
        }

        res: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema,
        }
        if self.capabilities:
            res["capabilities"] = self.capabilities
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolDefinition:
        """Construct ToolDefinition from raw MCP tool schema dictionary."""
        name = data.get("name", "")
        description = data.get("description", "")
        schema = data.get("inputSchema") or data.get("input_schema") or data.get("parameters") or {}
        if isinstance(schema, dict) and "properties" in schema:
            properties = schema.get("properties") or {}
            required_list = set(schema.get("required") or [])
        elif isinstance(schema, dict):
            properties = schema
            required_list = set()
        else:
            properties = {}
            required_list = set()

        params: Dict[str, ToolParameter] = {}
        for p_name, p_spec in properties.items():
            if isinstance(p_spec, ToolParameter):
                params[p_name] = p_spec
            elif isinstance(p_spec, dict):
                params[p_name] = ToolParameter.from_dict(
                    name=p_name,
                    data=p_spec,
                    required=(p_name in required_list or p_spec.get("required", False)),
                )
            else:
                params[p_name] = ToolParameter(name=p_name, required=(p_name in required_list))

        return cls(
            name=name,
            description=description,
            parameters=params,
            input_schema=schema if isinstance(schema, dict) else {},
            capabilities=data.get("capabilities"),
        )

    @classmethod
    def from_mcp_tool(cls, tool_dict: Dict[str, Any]) -> ToolDefinition:
        """Alias for from_dict to load directly from MCP JSON-RPC tools/list result."""
        return cls.from_dict(tool_dict)


@dataclass
class ToolCall:
    """Emitted tool call from an agent."""
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    call_id: Optional[str] = None

    @property
    def function_name(self) -> str:
        """Backward-compatible alias for name."""
        return self.name

    @property
    def parameters(self) -> Dict[str, Any]:
        """Backward-compatible alias for arguments."""
        return self.arguments

    def to_dict(self) -> Dict[str, Any]:
        """Serialize tool call to dictionary."""
        d: Dict[str, Any] = {
            "name": self.name,
            "function_name": self.name,
            "arguments": self.arguments,
            "parameters": self.arguments,
        }
        if self.call_id:
            d["call_id"] = self.call_id
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolCall:
        """Deserialize from dictionary supporting either name/arguments or function_name/parameters."""
        name = data.get("name") or data.get("function_name") or ""
        arguments = data.get("arguments") or data.get("parameters") or {}
        call_id = data.get("call_id") or data.get("id")
        return cls(name=name, arguments=arguments, call_id=call_id)


@dataclass
class LintViolation:
    """Static schema or capability contract violation identified by the linter."""
    tool_name: str
    parameter_name: Optional[str] = None
    rule_id: str = ""
    message: str = ""
    severity: str = Severity.ERROR.value
    call_index: int = 0

    def __init__(
        self,
        tool_name: str = "",
        parameter_name: Optional[str] = None,
        rule_id: str = "",
        message: str = "",
        severity: Union[Severity, str] = Severity.ERROR,
        call_index: int = 0,
        **kwargs,
    ):
        self.tool_name = kwargs.get("tool_name", tool_name)
        self.parameter_name = kwargs.get("parameter_name", parameter_name)
        self.rule_id = kwargs.get("rule_id", rule_id)
        self.message = kwargs.get("message", message)
        sev = kwargs.get("severity", severity)
        self.severity = sev.value if isinstance(sev, Severity) else str(sev)
        self.call_index = kwargs.get("call_index", call_index)

    @property
    def parameter(self) -> Optional[str]:
        """Alias for parameter_name."""
        return self.parameter_name

    @property
    def category(self) -> str:
        """Alias for rule_id."""
        return self.rule_id

    def to_dict(self) -> Dict[str, Any]:
        """Serialize violation to dictionary."""
        return {
            "call_index": self.call_index,
            "tool_name": self.tool_name,
            "parameter_name": self.parameter_name,
            "parameter": self.parameter_name,
            "rule_id": self.rule_id,
            "category": self.rule_id,
            "message": self.message,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LintViolation:
        """Construct from dictionary."""
        return cls(
            tool_name=data.get("tool_name", ""),
            parameter_name=data.get("parameter_name") or data.get("parameter"),
            rule_id=data.get("rule_id") or data.get("category", "unknown"),
            message=data.get("message", ""),
            severity=data.get("severity", Severity.ERROR.value),
            call_index=data.get("call_index", 0),
        )


# Alias for backward compatibility with spike
LintError = LintViolation


@dataclass
class LintResult:
    """Aggregated output of deterministic linting."""
    is_valid: bool = True
    errors: List[LintViolation] = field(default_factory=list)
    violations: List[LintViolation] = field(default_factory=list)
    violations_by_rule: Dict[str, List[LintViolation]] = field(default_factory=dict)
    latency_ms: float = 0.0
    checked_calls: int = 0
    total_calls: int = 0
    total_violations: int = 0

    def __init__(
        self,
        is_valid: bool = True,
        errors: Optional[List[LintViolation]] = None,
        violations: Optional[List[LintViolation]] = None,
        violations_by_rule: Optional[Dict[str, List[LintViolation]]] = None,
        latency_ms: float = 0.0,
        checked_calls: int = 0,
        total_calls: int = 0,
        total_violations: int = 0,
        **kwargs,
    ):
        self.is_valid = is_valid
        v_list = violations if violations is not None else (errors or [])
        self.violations = list(v_list)
        self.errors = self.violations
        self.violations_by_rule = dict(violations_by_rule) if violations_by_rule is not None else {}
        self.latency_ms = latency_ms
        self.total_calls = total_calls or checked_calls or kwargs.get("total_calls", 0)
        self.checked_calls = self.total_calls
        self.total_violations = total_violations or len(self.violations)

    def to_dict(self) -> Dict[str, Any]:
        """Convert lint result to dictionary."""
        return {
            "is_valid": self.is_valid,
            "errors": [e.to_dict() for e in self.errors],
            "violations": [e.to_dict() for e in self.violations],
            "violations_by_rule": {k: [v.to_dict() for v in val] for k, val in self.violations_by_rule.items()},
            "latency_ms": round(self.latency_ms, 4),
            "checked_calls": self.checked_calls,
            "total_calls": self.total_calls,
            "total_violations": self.total_violations,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LintResult:
        """Construct LintResult from dictionary."""
        errors = [LintViolation.from_dict(e) for e in (data.get("errors") or [])]
        return cls(
            is_valid=data.get("is_valid", False),
            errors=errors,
            latency_ms=data.get("latency_ms", 0.0),
            checked_calls=data.get("checked_calls", len(errors)),
        )


@dataclass
class ToolCallingScores:
    """Normalized Tool-Calling evaluation subscores and aggregates across 14 subdimensions."""
    necessity: float = 1.0
    overuse_detection: float = 0.0
    correctness: float = 1.0
    specificity: float = 1.0
    completeness_selection: float = 1.0
    sequence_logic: Optional[float] = None
    dependency_handling: Optional[float] = None
    execution_efficiency: Optional[float] = None
    args_completeness: float = 1.0
    name_accuracy: float = 1.0
    value_accuracy: float = 1.0
    type_compliance: float = 1.0
    format_compliance: float = 1.0
    relevancy: float = 1.0
    overall_tool_calling: float = 1.0
    dimensions: Dict[str, float] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize scores to dictionary."""
        return {
            "necessity": round(self.necessity, 4),
            "overuse_detection": round(self.overuse_detection, 4),
            "correctness": round(self.correctness, 4),
            "specificity": round(self.specificity, 4),
            "completeness_selection": round(self.completeness_selection, 4),
            "sequence_logic": round(self.sequence_logic, 4) if self.sequence_logic is not None else None,
            "dependency_handling": round(self.dependency_handling, 4) if self.dependency_handling is not None else None,
            "execution_efficiency": round(self.execution_efficiency, 4) if self.execution_efficiency is not None else None,
            "args_completeness": round(self.args_completeness, 4),
            "name_accuracy": round(self.name_accuracy, 4),
            "value_accuracy": round(self.value_accuracy, 4),
            "type_compliance": round(self.type_compliance, 4),
            "format_compliance": round(self.format_compliance, 4),
            "relevancy": round(self.relevancy, 4),
            "overall_tool_calling": round(self.overall_tool_calling, 4),
            "dimensions": {k: round(v, 4) for k, v in self.dimensions.items()},
            "failures": self.failures,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolCallingScores:
        """Construct from dictionary."""
        return cls(
            necessity=float(data.get("necessity", 1.0)),
            overuse_detection=float(data.get("overuse_detection", 0.0)),
            correctness=float(data.get("correctness", 1.0)),
            specificity=float(data.get("specificity", 1.0)),
            completeness_selection=float(data.get("completeness_selection", 1.0)),
            sequence_logic=float(data["sequence_logic"]) if data.get("sequence_logic") is not None else None,
            dependency_handling=float(data["dependency_handling"]) if data.get("dependency_handling") is not None else None,
            execution_efficiency=float(data["execution_efficiency"]) if data.get("execution_efficiency") is not None else None,
            args_completeness=float(data.get("args_completeness", data.get("arguments", {}).get("completeness", 1.0))),
            name_accuracy=float(data.get("name_accuracy", data.get("arguments", {}).get("name_accuracy", 1.0))),
            value_accuracy=float(data.get("value_accuracy", data.get("arguments", {}).get("value_accuracy", 1.0))),
            type_compliance=float(data.get("type_compliance", data.get("arguments", {}).get("type_compliance", 1.0))),
            format_compliance=float(data.get("format_compliance", data.get("arguments", {}).get("format_compliance", 1.0))),
            relevancy=float(data.get("relevancy", data.get("arguments", {}).get("relevancy", 1.0))),
            overall_tool_calling=float(data.get("overall_tool_calling", data.get("tc_overall", 1.0))),
            dimensions=data.get("dimensions", {}),
            failures=data.get("failures", []),
            rationale=data.get("rationale", ""),
        )


SubdimensionScores = ToolCallingScores


@dataclass
class CoherenceScores:
    """Normalized conversational coherence evaluation scores across 5 dimensions."""
    logical_flow: float = 1.0
    completeness: float = 1.0
    conciseness: float = 1.0
    topic_relevance: float = 1.0
    context_retention: Optional[float] = None
    overall_coherence: float = 1.0
    manifestations: List[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize coherence scores to dictionary."""
        return {
            "logical_flow": round(self.logical_flow, 4),
            "completeness": round(self.completeness, 4),
            "conciseness": round(self.conciseness, 4),
            "topic_relevance": round(self.topic_relevance, 4),
            "context_retention": round(self.context_retention, 4) if self.context_retention is not None else None,
            "overall_coherence": round(self.overall_coherence, 4),
            "manifestations": self.manifestations,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CoherenceScores:
        """Construct from dictionary."""
        return cls(
            logical_flow=float(data.get("logical_flow", 1.0)),
            completeness=float(data.get("completeness", 1.0)),
            conciseness=float(data.get("conciseness", 1.0)),
            topic_relevance=float(data.get("topic_relevance", 1.0)),
            context_retention=float(data["context_retention"]) if data.get("context_retention") is not None else None,
            overall_coherence=float(data.get("overall_coherence", data.get("coh_overall", 1.0))),
            manifestations=data.get("manifestations", []),
            rationale=data.get("rationale", ""),
        )


@dataclass
class CapabilityMatrix:
    """Backend model capabilities and constraints registry for an MCP server."""
    server_name: str
    models: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize capability matrix."""
        return {
            "server_name": self.server_name,
            "models": self.models,
            "metadata": self.metadata or {},
        }

    @classmethod
    def from_dict(cls, server_name: str, data: Dict[str, Any]) -> CapabilityMatrix:
        """Construct CapabilityMatrix from loaded JSON dictionary."""
        # Handle cases where data is keyed directly by model name or has a top-level wrapper
        if "models" in data and isinstance(data["models"], dict):
            return cls(
                server_name=server_name,
                models=data["models"],
                metadata=data.get("metadata"),
            )
        return cls(server_name=server_name, models=data)


@dataclass
class ServerSpec:
    """Specification of an MCP server including tool definitions and capability matrices."""
    server_name: str = ""
    tools: List[ToolDefinition] = field(default_factory=list)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    source: str = "file"  # "stdio", "directory", "file"
    source_dir: Optional[str] = None
    seed_outputs: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        server_name: str = "",
        tools: Optional[List[ToolDefinition]] = None,
        capabilities: Optional[Dict[str, Any]] = None,
        source: str = "file",
        source_dir: Optional[str] = None,
        name: Optional[str] = None,
        seed_outputs: Optional[Dict[str, Any]] = None,
    ):
        self.server_name = name or server_name or ""
        self.tools = list(tools) if tools is not None else []
        self.capabilities = dict(capabilities) if capabilities is not None else {}
        self.source = source
        self.source_dir = source_dir
        self.seed_outputs = dict(seed_outputs) if seed_outputs is not None else {}

    @property
    def name(self) -> str:
        return self.server_name

    def to_dict(self) -> Dict[str, Any]:
        """Convert ServerSpec to dictionary."""
        return {
            "server_name": self.server_name,
            "tools": [t.to_dict() if isinstance(t, ToolDefinition) else t for t in self.tools],
            "capabilities": self.capabilities,
            "source": self.source,
            "seed_outputs": self.seed_outputs or {},
        }


@dataclass
class EvaluationResult:
    """Complete evaluation report combining deterministic linting and LLM judging."""
    tool_calling: Optional[ToolCallingScores] = None
    coherence: Optional[CoherenceScores] = None
    lint_result: Optional[LintResult] = None
    passed: bool = True
    raw_judge_output: Optional[Dict[str, Any]] = None
    rationale: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        tool_calling: Optional[ToolCallingScores] = None,
        coherence: Optional[CoherenceScores] = None,
        lint_result: Optional[LintResult] = None,
        passed: bool = True,
        raw_judge_output: Optional[Dict[str, Any]] = None,
        rationale: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        tc_scores: Optional[ToolCallingScores] = None,
        coh_scores: Optional[CoherenceScores] = None,
        **kwargs,
    ):
        self.tool_calling = tc_scores or tool_calling or kwargs.get("tool_calling_scores")
        self.coherence = coh_scores or coherence or kwargs.get("coherence_scores")
        self.lint_result = lint_result
        self.passed = passed
        self.raw_judge_output = raw_judge_output
        self.rationale = rationale or (self.tool_calling.rationale if self.tool_calling else "")
        self.metadata = dict(metadata) if metadata is not None else {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize evaluation result to dictionary."""
        return {
            "passed": self.passed,
            "tool_calling": self.tool_calling.to_dict() if self.tool_calling else None,
            "coherence": self.coherence.to_dict() if self.coherence else None,
            "lint_result": self.lint_result.to_dict() if self.lint_result else None,
            "raw_judge_output": self.raw_judge_output,
            "rationale": self.rationale,
            "metadata": self.metadata,
        }
