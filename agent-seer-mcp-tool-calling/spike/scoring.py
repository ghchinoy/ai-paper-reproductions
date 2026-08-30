"""Aggregation of judge sub-scores into TC / Coherence, per Section 4 & App. E.

TC (tool-calling):
  - sub-scores are 0-10, normalized to 0-1 (x/10) before aggregation.
  - usage dimension score = necessity sub-score directly (overuse is diagnostic,
    excluded from the aggregate).
  - selection / ordering / arguments dimension score = arithmetic mean of their
    sub-scores.
  - ordering is N/A (excluded) when only one tool is called.
  - the (2, 3, or 4) top-level dimension scores combine via arithmetic mean.

Coherence:
  - sub-aspects 1-3, normalized to 0-1 via (x-1)/2, aggregated by arithmetic mean.
  - context_retention excluded when there is no conversation history.
"""


def _norm10(x):
    return max(0.0, min(1.0, x / 10.0))


def aggregate_tc(j):
    """j = parsed TC judge JSON. Returns dict with dimension + overall scores."""
    usage = _norm10(j["usage"]["necessity"])

    sel = j["selection"]
    selection = sum(_norm10(sel[k]) for k in ("correctness", "specificity", "completeness")) / 3.0

    arg = j["arguments"]
    arg_keys = ("completeness", "name_accuracy", "value_accuracy",
                "type_compliance", "format_compliance", "relevancy")
    arguments = sum(_norm10(arg[k]) for k in arg_keys) / len(arg_keys)

    dims = {"usage": usage, "selection": selection, "arguments": arguments}

    ordering = j.get("ordering", {})
    if not ordering.get("not_applicable", True):
        ok = ("sequence_logic", "dependency_handling", "execution_efficiency")
        vals = [ordering[k] for k in ok if ordering.get(k) is not None]
        if vals:
            dims["ordering"] = sum(_norm10(v) for v in vals) / len(vals)

    overall = sum(dims.values()) / len(dims)
    return {
        "dimensions": dims,
        "argument_subscores": {k: _norm10(arg[k]) for k in arg_keys},
        "tc_overall": overall,
        "failures": j.get("failures", []),
        "rationale": j.get("rationale", ""),
    }


def aggregate_coherence(j):
    def n(x):
        return (x - 1) / 2.0
    keys = ["logical_flow", "completeness", "conciseness", "topic_relevance"]
    vals = [n(j[k]) for k in keys]
    cr = j.get("context_retention", {})
    if not cr.get("not_applicable", True) and cr.get("score") is not None:
        vals.append(n(cr["score"]))
    overall = sum(vals) / len(vals)
    return {
        "coh_overall": overall,
        "manifestations": j.get("manifestations", []),
        "rationale": j.get("rationale", ""),
    }
