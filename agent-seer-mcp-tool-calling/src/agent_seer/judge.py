"""LLM-as-a-Judge Evaluation Engine & Decomposed Rubric Evaluator."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

from .clients import BaseLLMClient, GeminiClient, GemmaClient, create_client
from .linter import DeterministicLinter
from .models import CapabilityMatrix, EvaluationResult, LintResult, ServerSpec, ToolCall, ToolDefinition
from .prompts import COHERENCE_JUDGE_PROMPT, TC_JUDGE_PROMPT
from .scoring import (
    aggregate_coherence,
    aggregate_tc,
    apply_cascading_penalty_collapse,
    compute_coherence_score,
    compute_tool_calling_score,
)

logger = logging.getLogger("agent_seer.judge")


def extract_json_payload(raw_text: str) -> Dict[str, Any]:
    """Extracts and parses JSON from raw LLM output handling markdown fences."""
    text = raw_text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    text = text.strip()

    # If extra text precedes JSON object
    if "{" in text and not text.startswith("{"):
        text = text[text.find("{") :]
    if "}" in text and not text.endswith("}"):
        text = text[: text.rfind("}") + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON payload: {e}\nRaw text: {raw_text[:500]}")
        raise


def format_tool_specs(
    tool_specs: Union[List[Dict[str, Any]], List[ToolDefinition], Dict[str, Any]],
    capabilities: Union[Dict[str, Any], CapabilityMatrix, None] = None,
    enriched: bool = True,
) -> str:
    """Formats tool schemas and optional capability matrix for the judge prompt."""
    if isinstance(tool_specs, dict) and "tools" in tool_specs:
        raw_tools = tool_specs["tools"]
    elif isinstance(tool_specs, dict):
        raw_tools = list(tool_specs.values())
    else:
        raw_tools = tool_specs

    tools_list = [t.to_dict() if hasattr(t, "to_dict") else t for t in raw_tools]
    specs_str = json.dumps(tools_list, indent=2)

    if enriched and capabilities:
        caps_dict = capabilities.to_dict() if hasattr(capabilities, "to_dict") else capabilities
        specs_str += (
            "\n\nCRITICAL BACKEND MODEL CAPABILITY MATRIX (MUST ENFORCE):\n"
            + json.dumps(caps_dict, indent=2)
        )
    return specs_str


def format_agent_calls(agent_calls: Union[List[Dict[str, Any]], List[ToolCall]]) -> str:
    """Formats agent tool calls into standardized JSON for the judge prompt."""
    calls_list = [c.to_dict() if hasattr(c, "to_dict") else c for c in agent_calls]
    return json.dumps(calls_list, indent=2)


def judge_tc(
    tool_specs: Any,
    user_prompt: str,
    agent_calls: Any,
    capabilities: Any = None,
    model: str = "gemini-2.5-flash",
    enriched: bool = True,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Top-level functional judge for Tool-Calling correctness."""
    specs_str = format_tool_specs(tool_specs, capabilities=capabilities, enriched=enriched)
    calls_str = format_agent_calls(agent_calls)

    prompt = TC_JUDGE_PROMPT.format(
        tool_specs=specs_str,
        user_prompt=user_prompt,
        agent_calls=calls_str,
    )

    if client:
        llm = client
    elif "gemma" in model.lower():
        llm = GemmaClient()
    else:
        llm = GeminiClient()

    if hasattr(llm, "generate_json"):
        raw_json = llm.generate_json(prompt, model=model, temperature=0.0)
    else:
        raw_text = llm.generate(prompt, model=model, temperature=0.0)
        raw_json = extract_json_payload(raw_text)

    collapsed = apply_cascading_penalty_collapse(raw_json)
    res = aggregate_tc(collapsed)
    res["scores"] = compute_tool_calling_score(collapsed)
    res["_raw"] = raw_json
    return res


def judge_coherence(
    transcript_text: str,
    model: str = "gemini-2.5-flash",
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Top-level functional judge for Conversational Coherence."""
    prompt = COHERENCE_JUDGE_PROMPT.format(transcript=transcript_text)

    if client:
        llm = client
    elif "gemma" in model.lower():
        llm = GemmaClient()
    else:
        llm = GeminiClient()

    if hasattr(llm, "generate_json"):
        raw_json = llm.generate_json(prompt, model=model, temperature=0.0)
    else:
        raw_text = llm.generate(prompt, model=model, temperature=0.0)
        raw_json = extract_json_payload(raw_text)

    res = aggregate_coherence(raw_json)
    res["coh_overall"] = res.get("coherence_overall", 1.0)
    res["scores"] = compute_coherence_score(raw_json)
    res["_raw"] = raw_json
    return res


class JudgeEngine:
    """Orchestrates deterministic linting, LLM judging, and EvaluationResult reporting."""

    def __init__(
        self,
        client: Optional[Any] = None,
        linter: Optional[DeterministicLinter] = None,
        model_name: str = "gemini-2.5-flash",
    ):
        self.client = client
        self.linter = linter or DeterministicLinter()
        self.model_name = model_name

    def evaluate_tool_calls(
        self,
        tool_specs: Any,
        user_prompt: str,
        agent_calls: Any,
        capabilities: Any = None,
        enriched: bool = True,
    ) -> EvaluationResult:
        """Evaluates tool calls deterministically and semantically."""
        # 1. Deterministic Lint
        lint_res = self.linter.lint(agent_calls)

        # 2. Semantic LLM Judge
        specs_str = format_tool_specs(tool_specs, capabilities=capabilities, enriched=enriched)
        calls_str = format_agent_calls(agent_calls)
        prompt = TC_JUDGE_PROMPT.format(
            tool_specs=specs_str,
            user_prompt=user_prompt,
            agent_calls=calls_str,
        )

        if self.client and hasattr(self.client, "generate_json"):
            raw_json = self.client.generate_json(prompt, model=self.model_name, temperature=0.0)
        elif self.client:
            raw_text = self.client.generate(prompt, model=self.model_name, temperature=0.0)
            raw_json = extract_json_payload(raw_text)
        else:
            llm = GeminiClient()
            raw_json = llm.generate_json(prompt, model=self.model_name, temperature=0.0)

        # 3. Cascading penalty collapse using lint violations
        collapsed = apply_cascading_penalty_collapse(raw_json, lint_res.errors)
        tc_scores = compute_tool_calling_score(collapsed)

        passed = lint_res.is_valid and (tc_scores.overall_tool_calling >= 0.85)

        return EvaluationResult(
            passed=passed,
            tool_calling=tc_scores,
            lint_result=lint_res,
            raw_judge_output=raw_json,
            rationale=raw_json.get("rationale", ""),
        )

    def evaluate_transcript(self, transcript_text: str) -> EvaluationResult:
        """Evaluates conversational coherence of a multi-turn transcript."""
        prompt = COHERENCE_JUDGE_PROMPT.format(transcript=transcript_text)
        if self.client and hasattr(self.client, "generate_json"):
            raw_json = self.client.generate_json(prompt, model=self.model_name, temperature=0.0)
        elif self.client:
            raw_text = self.client.generate(prompt, model=self.model_name, temperature=0.0)
            raw_json = extract_json_payload(raw_text)
        else:
            llm = GeminiClient()
            raw_json = llm.generate_json(prompt, model=self.model_name, temperature=0.0)

        coh_scores = compute_coherence_score(raw_json)
        passed = coh_scores.overall_coherence >= 0.80

        return EvaluationResult(
            passed=passed,
            coherence=coh_scores,
            raw_judge_output=raw_json,
            rationale=raw_json.get("rationale", ""),
        )


# Class alias
AgentSeerJudge = JudgeEngine
