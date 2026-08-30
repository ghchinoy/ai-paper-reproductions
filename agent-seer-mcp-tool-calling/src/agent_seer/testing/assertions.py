"""Testing & Pytest Assertion Utilities for Agent Tool Calling."""
from typing import Any, Dict, List, Optional

from ..discovery import load_tools_and_capabilities
from ..judge import AgentSeerJudge
from ..linter import DeterministicLinter, LintResult


def assert_valid_tool_calls(
    calls: List[Dict[str, Any]],
    server_path_or_tools: Any,
    capabilities: Optional[Dict[str, Any]] = None,
) -> LintResult:
    """Pytest helper asserting that tool calls satisfy schemas and capability matrices."""
    if isinstance(server_path_or_tools, list):
        tools = server_path_or_tools
        caps = capabilities or {}
    else:
        tools, caps = load_tools_and_capabilities(str(server_path_or_tools), capabilities)

    linter = DeterministicLinter(tools=tools, capabilities=caps)
    res = linter.lint(calls)
    if not res.is_valid:
        error_msgs = "\n".join(f"  - [{e.category}] {e.tool_name}.{e.parameter}: {e.message}" for e in res.errors)
        raise AssertionError(f"Deterministic tool-calling lint failed with {len(res.errors)} error(s):\n{error_msgs}")
    return res


def evaluate_transcript(
    user_prompt: str,
    calls: List[Dict[str, Any]],
    server_path_or_tools: Any,
    capabilities: Optional[Dict[str, Any]] = None,
    min_tc_score: float = 0.85,
    model: str = "gemini-2.5-flash",
) -> Dict[str, Any]:
    """Pytest helper judging tool calls with LLM and asserting a minimum score threshold."""
    if isinstance(server_path_or_tools, list):
        tools = server_path_or_tools
        caps = capabilities or {}
    else:
        tools, caps = load_tools_and_capabilities(str(server_path_or_tools), capabilities)

    judge = AgentSeerJudge(model=model)
    report = judge.evaluate_tool_calling(
        tool_specs=tools,
        user_prompt=user_prompt,
        agent_calls=calls,
        capabilities=caps,
        enriched=True,
    )
    score = report.get("tc_overall", 0.0)
    if score < min_tc_score:
        failures = ", ".join(report.get("failures", [])) or "low score"
        raise AssertionError(
            f"Agent tool-calling score {score:.3f} fell below minimum required threshold {min_tc_score:.3f} ({failures}). Rationale: {report.get('rationale')}"
        )
    return report
