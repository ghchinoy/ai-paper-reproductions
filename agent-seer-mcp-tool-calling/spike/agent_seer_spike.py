#!/usr/bin/env python3
"""Agent Seer spike pipeline for mcp-veo-go (arXiv 2608.26133, phases 1-3).

Runs:
  Phase 1  Ingest spec  -> load real tools/list JSON
  Stage 1  Tool Interpretation (per tool)
  Stage 2  Scenario Generation (simple + complex, coverage suffix)
  Stage 3  Mock Output Generation (seeded with real smoke-test veo response)

Writes all intermediate artifacts under ./artifacts/. Multi-turn expansion
(Stage 4) is intentionally skipped for this spike (brief: skip 4-5).
"""
import json
import os
import sys

import gemini_client as gc
import prompts

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "artifacts")
os.makedirs(ART, exist_ok=True)


def load_spec():
    with open(os.path.join(ART, "veo_tools_list.json")) as f:
        return json.load(f)["tools"]


def tool_summary(tools):
    """Compact per-tool summary block used in the Stage-2 generation prompt."""
    lines = []
    for t in tools:
        schema = t.get("inputSchema", {})
        props = schema.get("properties", {})
        req = set(schema.get("required", []))
        lines.append(f"### {t['name']}")
        lines.append((t.get("description") or "").strip())
        lines.append("Parameters:")
        for pn, pv in props.items():
            typ = pv.get("type", "?")
            flag = "REQUIRED" if pn in req else "optional"
            desc = (pv.get("description") or "").strip().replace("\n", " ")
            lines.append(f"  - {pn} ({typ}, {flag}): {desc[:400]}")
        lines.append("")
    return "\n".join(lines)


def full_specs(tools):
    """Full JSON tool specs, given to the judge verbatim."""
    return json.dumps(tools, indent=2)


def stage1_interpret(tools):
    out = []
    for t in tools:
        prompt = prompts.STAGE1_TOOL_INTERPRETATION.format(
            tool_info=json.dumps(t, indent=2))
        print(f"  [stage1] interpreting {t['name']} ...", file=sys.stderr)
        j = gc.generate_json(prompt, gc.GENERATOR_MODEL, temperature=0.7)
        out.append(j)
    with open(os.path.join(ART, "stage1_interpretations.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


def stage2_scenarios(interpretations, n_tools):
    summary = json.dumps(interpretations, indent=2)
    results = {}
    for tier, tmpl in (("simple", prompts.STAGE2_SIMPLE),
                       ("complex", prompts.STAGE2_COMPLEX)):
        prompt = tmpl.format(tool_summary=summary, N=n_tools)
        print(f"  [stage2] generating {tier} scenarios ...", file=sys.stderr)
        j = gc.generate_json(prompt, gc.GENERATOR_MODEL, temperature=0.7)
        results[tier] = j
    with open(os.path.join(ART, "stage2_scenarios.json"), "w") as f:
        json.dump(results, f, indent=2)
    return results


def _flatten_scenarios(stage2):
    flat = []
    for tier, blob in stage2.items():
        for cat in blob.get("categories", []):
            for sc in cat.get("scenarios", []):
                sc["_tier"] = tier
                sc["_category"] = cat.get("category", "")
                flat.append(sc)
    return flat


def stage3_mock_outputs(scenarios, seed):
    example_block = json.dumps(seed, indent=2)
    out = []
    for i, sc in enumerate(scenarios):
        prompt = prompts.STAGE3_MOCK_OUTPUT.format(
            prompt=sc.get("prompt", ""),
            novelty_reason=sc.get("novelty_reason", ""),
            agent_workflow=json.dumps(sc.get("agent_workflow", []), indent=2),
            example_outputs=example_block,
        )
        print(f"  [stage3] mock outputs for scenario {i+1}/{len(scenarios)} "
              f"({sc.get('title','')[:40]}) ...", file=sys.stderr)
        try:
            j = gc.generate_json(prompt, gc.GENERATOR_MODEL, temperature=0.7)
        except Exception as e:  # spike: don't abort the whole run on one failure
            j = {"error": str(e)}
        out.append({"scenario_title": sc.get("title"), "tier": sc.get("_tier"),
                    "mock": j})
    with open(os.path.join(ART, "stage3_mock_outputs.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


def main():
    tools = load_spec()
    print(f"Ingested {len(tools)} tools: {[t['name'] for t in tools]}",
          file=sys.stderr)
    with open(os.path.join(HERE, "seed_outputs.json")) as f:
        seed = json.load(f)

    interps = stage1_interpret(tools)
    stage2 = stage2_scenarios(interps, len(tools))
    scenarios = _flatten_scenarios(stage2)
    print(f"Generated {len(scenarios)} scenarios "
          f"({sum(1 for s in scenarios if s['_tier']=='simple')} simple, "
          f"{sum(1 for s in scenarios if s['_tier']=='complex')} complex)",
          file=sys.stderr)
    stage3_mock_outputs(scenarios, seed)
    print("Pipeline complete. Artifacts in ./artifacts/", file=sys.stderr)


if __name__ == "__main__":
    main()
