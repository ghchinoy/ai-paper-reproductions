#!/usr/bin/env python3
"""Unified Agent Seer Discrimination Runner for all MCP servers & judge models.

Usage:
  python3 runner.py --server veo
  python3 runner.py --server nanobanana --enriched
  python3 runner.py --server lyria --all-judges
  python3 runner.py --all-servers --enriched
"""
import argparse
import importlib
import json
import math
import os
import sys

import gemini_client as gc
import judge

HERE = os.path.dirname(os.path.abspath(__file__))
SERVERS_DIR = os.path.join(HERE, "servers")
ART = os.path.join(HERE, "artifacts")
os.makedirs(ART, exist_ok=True)


def load_server(server_name):
    sdir = os.path.join(SERVERS_DIR, server_name)
    if not os.path.isdir(sdir):
        raise ValueError(f"Server directory not found: {sdir}")

    with open(os.path.join(sdir, "tools_list.json")) as f:
        tools = json.load(f)["tools"]

    caps_path = os.path.join(sdir, "capabilities.json")
    caps = {}
    if os.path.exists(caps_path):
        with open(caps_path) as f:
            caps = json.load(f)

    # Import transcripts dynamically
    sys.path.insert(0, sdir)
    transcripts_mod = importlib.import_module("transcripts")
    cases = transcripts_mod.CASES
    sys.path.pop(0)

    return tools, caps, cases


def run_discrimination(server_name, enriched=False, judges=None):
    tools, caps, cases = load_server(server_name)
    judges = judges or ["gemini-2.5-flash"]

    tool_specs_raw = json.dumps(tools, indent=2)
    if enriched and caps:
        tool_specs = (
            tool_specs_raw
            + "\n\nCRITICAL BACKEND MODEL CAPABILITY MATRIX (MUST ENFORCE):\n"
            + json.dumps(caps, indent=2)
        )
    else:
        tool_specs = tool_specs_raw

    results = []
    print(f"\n========================================================")
    print(f"Running Discrimination for [{server_name}] (Enriched={enriched})")
    print(f"Judges: {judges}")
    print(f"========================================================")

    for label, kind, prompt, calls, fault, exp_tax in cases:
        row = {
            "label": label,
            "kind": kind,
            "injected_fault": fault,
            "expected_taxonomy": exp_tax,
            "prompt": prompt,
            "calls": calls,
            "scores": {}
        }
        for j_model in judges:
            print(f"  [{j_model}] judging {label} ...", file=sys.stderr)
            try:
                res = judge.judge_tc(tool_specs, prompt, calls, model=j_model)
                row["scores"][j_model] = {
                    "tc": round(res.get("tc_overall", 0.0), 3),
                    "dims": res.get("dimensions", {}),
                    "argument_subscores": res.get("argument_subscores", {}),
                    "failures": res.get("failures", []),
                    "rationale": res.get("rationale", "")
                }
            except Exception as e:
                print(f"    ERROR with {j_model}: {e}", file=sys.stderr)
                row["scores"][j_model] = {"tc": None, "error": str(e)}

        results.append(row)

    # Summary analysis
    summary = compute_summary(results, judges)
    out_data = {
        "server": server_name,
        "enriched": enriched,
        "judges": judges,
        "summary": summary,
        "results": results
    }

    out_name = f"discrimination_{server_name}{'_enriched' if enriched else ''}.json"
    out_path = os.path.join(ART, out_name)
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2)
    print(f"Saved results -> {out_path}")

    print_table(results, judges)
    return out_data


def compute_summary(results, judges):
    summary = {}
    for j_model in judges:
        correct_tcs = [r["scores"][j_model]["tc"] for r in results if r["kind"] == "correct" and r["scores"][j_model]["tc"] is not None]
        broken_tcs = [r["scores"][j_model]["tc"] for r in results if r["kind"] == "broken" and r["scores"][j_model]["tc"] is not None]

        mean_correct = sum(correct_tcs) / len(correct_tcs) if correct_tcs else 0.0
        mean_broken = sum(broken_tcs) / len(broken_tcs) if broken_tcs else 0.0

        # Taxonomy hits
        hits = 0
        total_broken = 0
        for r in results:
            if r["kind"] == "broken":
                total_broken += 1
                exp = r["expected_taxonomy"].lower()
                failures = [f.lower() for f in r["scores"][j_model].get("failures", [])]
                rationale = r["scores"][j_model].get("rationale", "").lower()
                sub_scores = r["scores"][j_model].get("argument_subscores", {})
                
                # Check if expected failure is named in failures list, rationale, or has low subscore
                found = any(exp in f for f in failures) or (exp in rationale)
                if not found:
                    for k, v in sub_scores.items():
                        if (exp in k or k in exp) and v < 0.8:
                            found = True
                            break
                if found:
                    hits += 1

        summary[j_model] = {
            "mean_correct": round(mean_correct, 3),
            "mean_broken": round(mean_broken, 3),
            "gap": round(mean_correct - mean_broken, 3),
            "taxonomy_hits": f"{hits}/{total_broken}"
        }
    return summary


def print_table(results, judges):
    header = f"{'Case':<25} | {'Kind':<7} | " + " | ".join([f"{j[:12]:<12}" for j in judges]) + " | Injected Fault"
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        scores_str = " | ".join([f"{r['scores'][j].get('tc', 0.0) or 0.0:12.3f}" if r['scores'][j].get('tc') is not None else f"{'ERR':<12}" for j in judges])
        print(f"{r['label']:<25} | {r['kind']:<7} | {scores_str} | {r['injected_fault'][:35]}")


def main():
    parser = argparse.ArgumentParser(description="Agent Seer Discrimination Runner")
    parser.add_argument("--server", default="veo", choices=["veo", "nanobanana", "lyria", "omni", "all"], help="Server to evaluate")
    parser.add_argument("--all-servers", action="store_true", help="Run on all available servers")
    parser.add_argument("--enriched", action="store_true", help="Include capability matrix in judge context")
    parser.add_argument("--second-judge", action="store_true", help="Include Gemini 2.5 Pro")
    parser.add_argument("--gemma", action="store_true", help="Include Gemma 24B/27B out-of-family judge")
    parser.add_argument("--all-judges", action="store_true", help="Run all available judges")

    args = parser.parse_args()

    judges = ["gemini-2.5-flash"]
    if args.second_judge or args.all_judges:
        judges.append("gemini-2.5-pro")
    if args.gemma or args.all_judges:
        judges.append("gemma-2-27b-it")

    servers = ["veo", "nanobanana", "lyria", "omni"] if (args.all_servers or args.server == "all") else [args.server]

    for s in servers:
        run_discrimination(s, enriched=args.enriched, judges=judges)


if __name__ == "__main__":
    main()
