"""Arithmetic Aggregation, Normalization & Cascading Penalty Engine."""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional

from .models import CoherenceScores, LintViolation, ToolCallingScores


def norm10(x: Any) -> float:
    """Normalizes 0-10 subscore to 0.0-1.0 range."""
    if x is None:
        return 1.0
    try:
        val = float(x)
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return max(0.0, min(1.0, val / 10.0))
    except (ValueError, TypeError):
        return 0.0


def norm3(x: Any) -> float:
    """Normalizes 1-3 subscore to 0.0-1.0 range via (x - 1) / 2."""
    if x is None:
        return 1.0
    try:
        val = float(x)
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return max(0.0, min(1.0, (val - 1.0) / 2.0))
    except (ValueError, TypeError):
        return 0.0


def apply_cascading_penalty_collapse(
    raw_judge_output: Dict[str, Any], violations: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """Applies Agent Seer Table 18 cascading penalty rules to judge output."""
    output = copy.deepcopy(raw_judge_output) if isinstance(raw_judge_output, dict) else {}
    if output.get("arguments") is None:
        output["arguments"] = {}
    if output.get("usage") is None:
        output["usage"] = {}
    if output.get("selection") is None:
        output["selection"] = {}
    if output.get("ordering") is None:
        output["ordering"] = {"not_applicable": True}
    if output.get("failures") is None:
        output["failures"] = []

    args = output["arguments"]
    failures = output["failures"]

    has_name_or_required_err = False
    has_value_or_cap_err = False

    if violations:
        for v in violations:
            rule = getattr(v, "rule_id", getattr(v, "category", getattr(v, "rule", ""))) if hasattr(v, "__dict__") or isinstance(v, dict) else str(v)
            if isinstance(v, dict):
                rule = v.get("rule_id", v.get("category", ""))
            if rule in ("missing_required", "unknown_param", "malformed_call"):
                has_name_or_required_err = True
            elif rule in ("capability_violation", "illegal_enum", "type_mismatch", "invalid_uri", "invalid_value", "unknown_model"):
                has_value_or_cap_err = True

    # Also check failures list from LLM output
    for f in failures:
        f_lower = str(f).lower()
        if "name" in f_lower or "missing" in f_lower or "unknown_param" in f_lower:
            has_name_or_required_err = True
        if "value" in f_lower or "capab" in f_lower or "enum" in f_lower:
            has_value_or_cap_err = True

    # Rule 1: Parameter name wrong or required missing -> collapse all argument subscores to 0
    if has_name_or_required_err or (args.get("name_accuracy") is not None and args.get("name_accuracy") <= 2):
        args["completeness"] = 0
        args["name_accuracy"] = 0
        args["value_accuracy"] = 0
        args["type_compliance"] = 0
        args["format_compliance"] = 0
        args["relevancy"] = min(args.get("relevancy", 10), 2)
        if "argument_name_collapse" not in failures:
            failures.append("argument_name_collapse")

    # Rule 2: Parameter value wrong / capability violation -> collapse value/type/format
    elif has_value_or_cap_err or (args.get("value_accuracy") is not None and args.get("value_accuracy") <= 2):
        args["value_accuracy"] = 0
        args["type_compliance"] = 0
        args["format_compliance"] = 0
        args["relevancy"] = min(args.get("relevancy", 10), 2)
        if "argument_value_collapse" not in failures:
            failures.append("argument_value_collapse")

    return output


def compute_tool_calling_score(raw_judge_output: Dict[str, Any]) -> ToolCallingScores:
    """Computes normalized ToolCallingScores from raw or collapsed judge JSON."""
    usage_dict = raw_judge_output.get("usage") or {}
    usage_necessity = norm10(usage_dict.get("necessity", 10))
    usage_overuse = norm10(usage_dict.get("overuse_detection", usage_dict.get("overuse", 0)))

    sel = raw_judge_output.get("selection") or {}
    sel_correctness = norm10(sel.get("correctness", 10))
    sel_specificity = norm10(sel.get("specificity", 10))
    sel_completeness = norm10(sel.get("completeness", 10))
    selection_dim = (sel_correctness + sel_specificity + sel_completeness) / 3.0

    arg = raw_judge_output.get("arguments") or {}
    arg_comp = norm10(arg.get("completeness", 10))
    arg_name = norm10(arg.get("name_accuracy", 10))
    arg_val = norm10(arg.get("value_accuracy", 10))
    arg_type = norm10(arg.get("type_compliance", 10))
    arg_fmt = norm10(arg.get("format_compliance", 10))
    arg_rel = norm10(arg.get("relevancy", 10))
    args_dim = (arg_comp + arg_name + arg_val + arg_type + arg_fmt + arg_rel) / 6.0

    dims: Dict[str, float] = {
        "usage": usage_necessity,
        "selection": selection_dim,
        "arguments": args_dim,
    }

    ordering = raw_judge_output.get("ordering") or {}
    is_na = ordering.get("not_applicable", True)
    ord_seq = None
    ord_dep = None
    ord_eff = None

    if not is_na:
        ord_seq = norm10(ordering.get("sequence_logic", 10))
        ord_dep = norm10(ordering.get("dependency_handling", 10))
        ord_eff = norm10(ordering.get("execution_efficiency", 10))
        dims["ordering"] = (ord_seq + ord_dep + ord_eff) / 3.0

    overall = sum(dims.values()) / float(len(dims))

    return ToolCallingScores(
        necessity=usage_necessity,
        overuse_detection=usage_overuse,
        correctness=sel_correctness,
        specificity=sel_specificity,
        completeness_selection=sel_completeness,
        sequence_logic=ord_seq,
        dependency_handling=ord_dep,
        execution_efficiency=ord_eff,
        args_completeness=arg_comp,
        name_accuracy=arg_name,
        value_accuracy=arg_val,
        type_compliance=arg_type,
        format_compliance=arg_fmt,
        relevancy=arg_rel,
        overall_tool_calling=round(overall, 4),
        dimensions={k: round(v, 4) for k, v in dims.items()},
    )


def compute_coherence_score(raw_judge_output: Dict[str, Any]) -> CoherenceScores:
    """Computes normalized CoherenceScores from raw judge JSON."""
    lf = norm3(raw_judge_output.get("logical_flow", 3))
    comp = norm3(raw_judge_output.get("completeness", 3))
    conc = norm3(raw_judge_output.get("conciseness", 3))
    tr = norm3(raw_judge_output.get("topic_relevance", 3))

    cr_dict = raw_judge_output.get("context_retention") or {}
    cr_na = cr_dict.get("not_applicable", True)
    cr = None
    vals = [lf, comp, conc, tr]

    if not cr_na and cr_dict.get("score") is not None:
        cr = norm3(cr_dict["score"])
        vals.append(cr)

    overall = sum(vals) / float(len(vals))

    return CoherenceScores(
        logical_flow=lf,
        completeness=comp,
        conciseness=conc,
        topic_relevance=tr,
        context_retention=cr,
        overall_coherence=round(overall, 4),
    )


def aggregate_tc(raw_judge_output: Dict[str, Any]) -> Dict[str, Any]:
    """Backward compatibility aggregation returning dictionary."""
    tc_scores = compute_tool_calling_score(raw_judge_output)
    return {
        "tc_overall": round(tc_scores.overall_tool_calling, 3),
        "dimensions": tc_scores.dimensions,
        "argument_subscores": {
            "completeness": tc_scores.args_completeness,
            "name_accuracy": tc_scores.name_accuracy,
            "value_accuracy": tc_scores.value_accuracy,
            "type_compliance": tc_scores.type_compliance,
            "format_compliance": tc_scores.format_compliance,
            "relevancy": tc_scores.relevancy,
        },
        "failures": raw_judge_output.get("failures", []),
        "rationale": raw_judge_output.get("rationale", ""),
    }


def aggregate_coherence(raw_judge_output: Dict[str, Any]) -> Dict[str, Any]:
    """Backward compatibility aggregation returning dictionary."""
    coh_scores = compute_coherence_score(raw_judge_output)
    return {
        "coherence_overall": round(coh_scores.overall_coherence, 3),
        "coh_overall": round(coh_scores.overall_coherence, 3),
        "scores": {
            "logical_flow": raw_judge_output.get("logical_flow"),
            "completeness": raw_judge_output.get("completeness"),
            "conciseness": raw_judge_output.get("conciseness"),
            "topic_relevance": raw_judge_output.get("topic_relevance"),
        },
        "manifestations": raw_judge_output.get("manifestations", []),
        "rationale": raw_judge_output.get("rationale", ""),
    }
