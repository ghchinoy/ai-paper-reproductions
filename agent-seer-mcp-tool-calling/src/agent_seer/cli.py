"""Command Line Interface for Agent Seer."""
import argparse
import importlib.util
import json
import os
import sys
from typing import Any, Dict, List

from .discovery import load_tools_and_capabilities
from .judge import AgentSeerJudge
from .linter import DeterministicLinter
from .pipeline import SyntheticHarnessGenerator


def load_transcript(transcript_path: str) -> List[Dict[str, Any]]:
    """Loads transcripts from JSON file or Python CASES list."""
    if transcript_path.endswith(".py"):
        spec = importlib.util.spec_from_file_location("transcripts", transcript_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cases = getattr(mod, "CASES", [])
            # If CASES format: (label, kind, prompt, calls, fault, exp)
            formatted = []
            for item in cases:
                if isinstance(item, (tuple, list)):
                    formatted.append({
                        "label": item[0],
                        "kind": item[1],
                        "prompt": item[2],
                        "calls": item[3],
                        "injected_fault": item[4] if len(item) > 4 else "none"
                    })
                elif isinstance(item, dict):
                    formatted.append(item)
            return formatted
    with open(transcript_path) as f:
        data = json.load(f)
        if isinstance(data, list):
            return data
        return [data]


def cmd_inspect(args):
    """Inspects tool schemas and capabilities for a server."""
    tools, caps = load_tools_and_capabilities(args.server, args.caps)
    print(f"\n========================================================")
    print(f"Inspecting MCP Server: {args.server}")
    print(f"Tools Discovered ({len(tools)}): {[t['name'] for t in tools]}")
    print(f"Capability Matrix Registered: {bool(caps)}")
    print(f"========================================================\n")

    for t in tools:
        schema = t.get("inputSchema", {})
        props = schema.get("properties", {})
        req = schema.get("required", [])
        print(f"Tool: {t['name']}")
        print(f"  Description: {t.get('description', '').strip()[:150]}...")
        print(f"  Required: {req}")
        print(f"  Parameters ({len(props)}):")
        for pn, pv in props.items():
            flag = " [REQUIRED]" if pn in req else ""
            print(f"    - {pn} ({pv.get('type', '?')}){flag}: {pv.get('description', '').strip()[:80]}")
        print("")


def cmd_lint(args):
    """Runs deterministic capability and schema linting."""
    tools, caps = load_tools_and_capabilities(args.server, args.caps)
    linter = DeterministicLinter(tools=tools, capabilities=caps)
    transcripts = load_transcript(args.transcript)

    print(f"\n========================================================")
    print(f"Linting {len(transcripts)} transcript(s) against {args.server}")
    print(f"========================================================\n")

    total_valid = 0
    for idx, item in enumerate(transcripts):
        label = item.get("label", f"Case-{idx+1}")
        calls = item.get("calls", item.get("agent_calls", []))
        res = linter.lint(calls)
        status = "VALID" if res.is_valid else "ERROR"
        if res.is_valid:
            total_valid += 1
        print(f"[{status}] {label:<30} ({res.latency_ms:.3f} ms)")
        for err in res.errors:
            print(f"    -> [{err.category}] {err.tool_name}.{err.parameter or ''}: {err.message}")

    print(f"\nResult: {total_valid}/{len(transcripts)} transcripts valid.\n")


def cmd_eval(args):
    """Runs LLM-as-judge evaluation on transcripts."""
    tools, caps = load_tools_and_capabilities(args.server, args.caps)
    judge = AgentSeerJudge(model=args.model)
    transcripts = load_transcript(args.transcript)

    print(f"\n========================================================")
    print(f"Evaluating {len(transcripts)} transcript(s) with Judge [{args.model}]")
    print(f"Enriched with Capabilities: {not args.unenriched}")
    print(f"========================================================\n")

    results = []
    for idx, item in enumerate(transcripts):
        label = item.get("label", f"Case-{idx+1}")
        prompt = item.get("prompt", item.get("user_prompt", ""))
        calls = item.get("calls", item.get("agent_calls", []))

        print(f"  Judging {label} ...", file=sys.stderr)
        report = judge.evaluate_tool_calling(
            tool_specs=tools,
            user_prompt=prompt,
            agent_calls=calls,
            capabilities=caps,
            enriched=(not args.unenriched),
        )
        score = report.get("tc_overall", 0.0)
        failures = ", ".join(report.get("failures", [])) or "none"
        print(f"[{score:5.3f}] {label:<30} | Failures: {failures}")
        results.append({"label": label, "score": score, "report": report})

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved evaluation report -> {args.output}")


def main():
    parser = argparse.ArgumentParser(
        prog="agent-seer",
        description="Agent Seer: Spec-Driven MCP Evaluation, Deterministic Linting & Synthetic Scenarios.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect an MCP server schema and capabilities.")
    p_inspect.add_argument("server", help="Path to server directory, JSON file, or live binary command.")
    p_inspect.add_argument("--caps", help="Optional path to capabilities.json overlay.")
    p_inspect.set_defaults(func=cmd_inspect)

    # lint
    p_lint = subparsers.add_parser("lint", help="Run deterministic schema and capability linting on tool calls.")
    p_lint.add_argument("transcript", help="Path to transcript JSON or Python cases file.")
    p_lint.add_argument("--server", required=True, help="Server directory, JSON file, or live binary.")
    p_lint.add_argument("--caps", help="Optional path to capabilities.json overlay.")
    p_lint.set_defaults(func=cmd_lint)

    # eval
    p_eval = subparsers.add_parser("eval", help="Run LLM-as-judge scoring on agent tool-calling transcripts.")
    p_eval.add_argument("transcript", help="Path to transcript JSON or Python cases file.")
    p_eval.add_argument("--server", required=True, help="Server directory, JSON file, or live binary.")
    p_eval.add_argument("--caps", help="Optional path to capabilities.json overlay.")
    p_eval.add_argument("--model", default="gemini-2.5-flash", help="Judge model name.")
    p_eval.add_argument("--unenriched", action="store_true", help="Disable capability matrix context.")
    p_eval.add_argument("--output", help="Optional path to write JSON evaluation results.")
    p_eval.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
