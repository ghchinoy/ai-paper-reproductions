#!/usr/bin/env python3
"""The actual proof-of-concept: does the judge discriminate good vs broken
tool calls on veo's REAL schema?

We hand-build correct and deliberately-broken agent transcripts grounded in
mcp-veo-go's real tools/list and its documented footguns (wrong Veo model that
rejects generate_audio, illegal aspect_ratio enum, hallucinated model ID,
missing required field, wrong-tool selection, wrong param name, malformed GCS
URI). We run the reconstructed TC judge (Gemini 2.5 Flash, temp 0) and check
that broken calls score materially lower than their correct baseline, AND that
the judge's failure taxonomy names the injected fault.

Agent-under-test decision (unresolved in the investigation, Q2): rather than
stand up a live agent-under-test (Gemini CLI / a function-calling loop) — which
is the runner the paper describes but does NOT provide, and is out of spike
scope — we author the transcripts directly. This isolates the load-bearing
question (does the JUDGE produce discriminating signal?) from runner
integration risk. A full build would replace these hand-authored calls with a
real agent's emitted calls; the judge is unchanged.
"""
import json
import os
import sys

import gemini_client as gc
import judge

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "artifacts")

with open(os.path.join(ART, "veo_tools_list.json")) as f:
    TOOLS = json.load(f)["tools"]
TOOL_SPECS = json.dumps(TOOLS, indent=2)

# --- Scenario A: text-to-video, 16:9 + audio, GCS output ------------------
PROMPT_A = ("Generate a 16:9 cinematic video of a slow pan across a calm "
            "mountain lake at sunrise, with audio. Save it to "
            "gs://mybucket/out/.")

# --- Scenario B: image-to-video chain -------------------------------------
PROMPT_B = ("I already have an image at gs://mybucket/in.png. Animate it into "
            "a short video and save it to gs://mybucket/out/.")

CASES = [
    # label, kind, prompt, agent_calls, injected_fault, expected_taxonomy
    ("A0-correct", "correct", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-3.1-fast-generate-001",
            "aspect_ratio": "16:9", "generate_audio": True,
            "bucket": "gs://mybucket/out/"}}],
     "none", "none"),

    ("A1-wrong-model-value", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-2.0-generate-001",  # does NOT support generate_audio
            "aspect_ratio": "16:9", "generate_audio": True,
            "bucket": "gs://mybucket/out/"}}],
     "veo-2.0 model rejects generate_audio=true", "argument_value"),

    ("A2-illegal-enum", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-3.1-fast-generate-001",
            "aspect_ratio": "21:9",  # not a supported aspect ratio
            "generate_audio": True, "bucket": "gs://mybucket/out/"}}],
     "aspect_ratio 21:9 not supported", "argument_format"),

    ("A3-hallucinated-model", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-3.5-ultra-generate-001",  # does not exist
            "aspect_ratio": "16:9", "generate_audio": True,
            "bucket": "gs://mybucket/out/"}}],
     "model ID does not exist in spec", "argument_value"),

    ("A4-missing-required", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {  # 'prompt' is REQUIRED
            "model": "veo-3.1-fast-generate-001",
            "aspect_ratio": "16:9", "generate_audio": True,
            "bucket": "gs://mybucket/out/"}}],
     "missing required 'prompt'", "argument_completeness"),

    ("A5-wrong-tool", "broken", PROMPT_A, [
        {"function_name": "veo_i2v", "parameters": {  # no image was provided
            "image_uri": "gs://mybucket/nonexistent.png",
            "bucket": "gs://mybucket/out/"}}],
     "used i2v with no source image (should be t2v)", "selection"),

    ("A6-wrong-param-names", "broken", PROMPT_A, [
        {"function_name": "veo_t2v", "parameters": {
            "prompt": "a slow cinematic pan across a calm mountain lake at sunrise",
            "model": "veo-3.1-fast-generate-001",
            "ratio": "16:9",            # should be aspect_ratio
            "gcs_bucket": "gs://mybucket/out/"}}],  # should be bucket
     "invalid parameter names ratio/gcs_bucket", "argument_name"),

    ("B0-correct", "correct", PROMPT_B, [
        {"function_name": "veo_i2v", "parameters": {
            "image_uri": "gs://mybucket/in.png",
            "model": "veo-3.1-generate-001",
            "bucket": "gs://mybucket/out/"}}],
     "none", "none"),

    ("B1-wrong-tool", "broken", PROMPT_B, [
        {"function_name": "veo_t2v", "parameters": {  # ignores the image
            "prompt": "animate the image into a short video",
            "model": "veo-3.1-generate-001",
            "bucket": "gs://mybucket/out/"}}],
     "used t2v, ignoring the provided image (should be i2v)", "selection"),

    ("B2-missing-required-image", "broken", PROMPT_B, [
        {"function_name": "veo_i2v", "parameters": {  # image_uri REQUIRED
            "prompt": "animate it", "bucket": "gs://mybucket/out/"}}],
     "missing required image_uri", "argument_completeness"),

    ("B3-malformed-uri", "broken", PROMPT_B, [
        {"function_name": "veo_i2v", "parameters": {
            "image_uri": "in.png",  # must be a gs:// URI
            "model": "veo-3.1-generate-001",
            "bucket": "gs://mybucket/out/"}}],
     "image_uri not a gs:// URI", "argument_format"),
]


def run(second_judge=False):
    results = []
    for label, kind, prompt, calls, fault, exp_tax in CASES:
        print(f"[judge] {label} ...", file=sys.stderr)
        agg = judge.judge_tc(TOOL_SPECS, prompt, calls)
        row = {
            "label": label, "kind": kind, "injected_fault": fault,
            "expected_taxonomy": exp_tax,
            "tc_overall": round(agg["tc_overall"], 3),
            "dimensions": {k: round(v, 3) for k, v in agg["dimensions"].items()},
            "arg_subscores": {k: round(v, 3) for k, v in agg["argument_subscores"].items()},
            "failures": agg["failures"],
            "rationale": agg["rationale"],
        }
        if second_judge:
            print(f"[judge2] {label} ...", file=sys.stderr)
            agg2 = judge.judge_tc(TOOL_SPECS, prompt, calls,
                                  model=gc.SECOND_JUDGE_MODEL)
            row["tc_overall_second_judge"] = round(agg2["tc_overall"], 3)
            row["failures_second_judge"] = agg2["failures"]
        results.append(row)

    with open(os.path.join(ART, "discrimination_results.json"), "w") as f:
        json.dump(results, f, indent=2)

    _report(results, second_judge)
    return results


def _report(results, second_judge):
    correct = [r for r in results if r["kind"] == "correct"]
    broken = [r for r in results if r["kind"] == "broken"]
    mc = sum(r["tc_overall"] for r in correct) / len(correct)
    mb = sum(r["tc_overall"] for r in broken) / len(broken)
    max_broken = max(r["tc_overall"] for r in broken)
    min_correct = min(r["tc_overall"] for r in correct)

    print("\n==================== DISCRIMINATION RESULTS ====================")
    hdr = f"{'case':<26}{'kind':<9}{'TC':>6}"
    if second_judge:
        hdr += f"{'TC(2)':>7}"
    hdr += "  failures / injected-fault"
    print(hdr)
    print("-" * 78)
    for r in results:
        line = f"{r['label']:<26}{r['kind']:<9}{r['tc_overall']:>6.3f}"
        if second_judge:
            line += f"{r.get('tc_overall_second_judge', float('nan')):>7.3f}"
        tax = ",".join(r["failures"]) or "-"
        line += f"  {tax}"
        print(line)
    print("-" * 78)
    print(f"mean TC  correct = {mc:.3f}   broken = {mb:.3f}   gap = {mc - mb:.3f}")
    print(f"min correct = {min_correct:.3f}   max broken = {max_broken:.3f}   "
          f"separation = {min_correct - max_broken:.3f}")

    # Taxonomy hit: did the judge name the expected failure dimension?
    tax_hits = 0
    tax_total = 0
    for r in results:
        if r["kind"] != "broken":
            continue
        tax_total += 1
        if any(r["expected_taxonomy"] in f or f in r["expected_taxonomy"]
               for f in r["failures"]):
            tax_hits += 1
    print(f"taxonomy hits (expected fault named): {tax_hits}/{tax_total}")

    verdict = "DISCRIMINATES" if (mc - mb) >= 0.15 and min_correct > max_broken \
        else ("WEAK/PARTIAL" if (mc - mb) >= 0.05 else "DOES NOT DISCRIMINATE")
    print(f"\nVERDICT: judge {verdict} good vs broken tool calls "
          f"(clean separation={'yes' if min_correct > max_broken else 'no'}).")
    print("================================================================\n")


if __name__ == "__main__":
    run(second_judge="--second-judge" in sys.argv)
