"""Narrative Cross-Server Media Production Experiment: Storyboard -> Omni Video -> Lyria Score -> AVTool Mux.

Evaluates multi-turn multi-tool agent orchestration across:
1. mcp-nanobanana-go (Storyboard Concept Art)
2. mcp-omni-go (Video Generation with Ambient Audio)
3. mcp-lyria-go (Original Soundtrack Composition)
4. mcp-avtool-go (Audio/Video Muxing & Remastering)
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "artifacts")
os.makedirs(ART, exist_ok=True)

PROMPT_NARRATIVE = (
    "Produce a complete 16:9 cinematic short commercial for a deep-sea exploration submersible: "
    "1. Generate a 16:9 2K storyboard hero concept of the bioluminescent submarine exploring a coral trench. "
    "2. Animate that storyboard image into a video clip using Gemini Omni with ambient submarine hum and sonar ping audio. "
    "3. Compose a 30-second atmospheric orchestral underwater music soundtrack with Google Lyria. "
    "4. Mux the Omni video and Lyria soundtrack together into a final composite video saved to gs://genmedia-bucket/final/deep_sea_commercial.mp4."
)

NARRATIVE_CASES = [
    (
        "NP0-correct-narrative-pipeline",
        "correct",
        PROMPT_NARRATIVE,
        [
            {
                "function_name": "nanobanana_image_generation",
                "parameters": {
                    "prompt": "Bioluminescent yellow research submarine gliding over a glowing abyssal trench, deep blue ocean, cinematic lighting, 16:9",
                    "model": "gemini-3.1-flash-image",
                    "aspect_ratio": "16:9",
                    "image_size": "2K",
                    "gcs_bucket_uri": "gs://genmedia-bucket/storyboard/",
                    "output_filename": "sub_concept.png"
                }
            },
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Bioluminescent submarine explores deep sea coral canyon, headlights piercing dark water, ambient hum and periodic sonar pings",
                    "images": ["gs://genmedia-bucket/storyboard/sub_concept.png"],
                    "model": "gemini-omni-1.1-flash-preview",
                    "gcs_bucket_uri": "gs://genmedia-bucket/video/",
                    "output_filename": "sub_animation.mp4"
                }
            },
            {
                "function_name": "lyria_generate_music",
                "parameters": {
                    "prompt": "Atmospheric cinematic orchestral underwater soundtrack, slow strings, mysterious resonant synth pads",
                    "model_id": "lyria-3-clip-preview",
                    "output_gcs_bucket": "genmedia-bucket",
                    "output_filename": "sub_theme.wav"
                }
            },
            {
                "function_name": "ffmpeg_combine_audio_and_video",
                "parameters": {
                    "input_video_uri": "gs://genmedia-bucket/video/sub_animation.mp4",
                    "input_audio_uri": "gs://genmedia-bucket/sub_theme.wav",
                    "output_gcs_bucket": "genmedia-bucket",
                    "output_filename": "deep_sea_commercial.mp4"
                }
            }
        ],
        "none",
        "none"
    ),
    (
        "NP1-broken-uri-pipe",
        "broken",
        PROMPT_NARRATIVE,
        [
            {
                "function_name": "nanobanana_image_generation",
                "parameters": {
                    "prompt": "Bioluminescent yellow research submarine in ocean trench, 16:9",
                    "model": "gemini-3.1-flash-image",
                    "aspect_ratio": "16:9",
                    "gcs_bucket_uri": "gs://genmedia-bucket/storyboard/",
                    "output_filename": "sub_concept.png"
                }
            },
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Submarine explores deep sea coral canyon",
                    "images": ["gs://genmedia-bucket/storyboard/hallucinated_unrelated_render.png"],
                    "model": "gemini-omni-1.1-flash-preview",
                    "gcs_bucket_uri": "gs://genmedia-bucket/video/",
                    "output_filename": "sub_animation.mp4"
                }
            },
            {
                "function_name": "lyria_generate_music",
                "parameters": {
                    "prompt": "Atmospheric orchestral underwater soundtrack",
                    "model_id": "lyria-3-clip-preview",
                    "output_gcs_bucket": "genmedia-bucket",
                    "output_filename": "sub_theme.wav"
                }
            },
            {
                "function_name": "ffmpeg_combine_audio_and_video",
                "parameters": {
                    "input_video_uri": "gs://genmedia-bucket/video/sub_animation.mp4",
                    "input_audio_uri": "gs://genmedia-bucket/sub_theme.wav",
                    "output_gcs_bucket": "genmedia-bucket",
                    "output_filename": "deep_sea_commercial.mp4"
                }
            }
        ],
        "Step 2 omni_video_generation references a nonexistent image URI rather than the output of Step 1",
        "argument_value"
    ),
    (
        "NP2-aspect-ratio-and-size-mismatch",
        "broken",
        PROMPT_NARRATIVE,
        [
            {
                "function_name": "nanobanana_image_generation",
                "parameters": {
                    "prompt": "Bioluminescent yellow research submarine in ocean trench",
                    "model": "gemini-2.5-flash-image",
                    "aspect_ratio": "1:8",
                    "image_size": "4K",
                    "gcs_bucket_uri": "gs://genmedia-bucket/storyboard/"
                }
            },
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Submarine explores deep sea coral canyon",
                    "images": ["gs://genmedia-bucket/storyboard/sub_concept.png"],
                    "model": "gemini-omni-1.1-flash-preview",
                    "gcs_bucket_uri": "gs://genmedia-bucket/video/"
                }
            },
            {
                "function_name": "lyria_generate_music",
                "parameters": {
                    "prompt": "Atmospheric underwater soundtrack",
                    "model_id": "lyria-3-clip-preview",
                    "output_gcs_bucket": "genmedia-bucket"
                }
            },
            {
                "function_name": "ffmpeg_combine_audio_and_video",
                "parameters": {
                    "input_video_uri": "gs://genmedia-bucket/video/sub_animation.mp4",
                    "input_audio_uri": "gs://genmedia-bucket/sub_theme.wav",
                    "output_gcs_bucket": "genmedia-bucket",
                    "output_filename": "deep_sea_commercial.mp4"
                }
            }
        ],
        "Step 1 uses illegal aspect_ratio 1:8 and unsupported image_size 4K on gemini-2.5-flash-image",
        "argument_value"
    ),
    (
        "NP3-broken-pipeline-ordering",
        "broken",
        PROMPT_NARRATIVE,
        [
            {
                "function_name": "ffmpeg_combine_audio_and_video",
                "parameters": {
                    "input_video_uri": "gs://genmedia-bucket/video/sub_animation.mp4",
                    "input_audio_uri": "gs://genmedia-bucket/sub_theme.wav",
                    "output_gcs_bucket": "genmedia-bucket",
                    "output_filename": "deep_sea_commercial.mp4"
                }
            },
            {
                "function_name": "nanobanana_image_generation",
                "parameters": {
                    "prompt": "Bioluminescent yellow research submarine in ocean trench, 16:9",
                    "model": "gemini-3.1-flash-image",
                    "aspect_ratio": "16:9",
                    "gcs_bucket_uri": "gs://genmedia-bucket/storyboard/",
                    "output_filename": "sub_concept.png"
                }
            },
            {
                "function_name": "omni_video_generation",
                "parameters": {
                    "prompt": "Submarine explores deep sea coral canyon",
                    "images": ["gs://genmedia-bucket/storyboard/sub_concept.png"],
                    "model": "gemini-omni-1.1-flash-preview",
                    "gcs_bucket_uri": "gs://genmedia-bucket/video/"
                }
            },
            {
                "function_name": "lyria_generate_music",
                "parameters": {
                    "prompt": "Atmospheric orchestral underwater soundtrack",
                    "model_id": "lyria-3-clip-preview",
                    "output_gcs_bucket": "genmedia-bucket"
                }
            }
        ],
        "Pipeline ordering is broken: ffmpeg mux is invoked before video or audio assets have been generated",
        "sequence_logic"
    )
]


def load_narrative_tools():
    """Loads consolidated tool definitions for Nanobanana, Omni, Lyria, and AVTool."""
    servers_dir = os.path.join(HERE, "servers")
    all_tools = []
    for sname in ["nanobanana", "omni", "lyria", "avtool"]:
        sdir = os.path.join(servers_dir, sname)
        with open(os.path.join(sdir, "tools_list.json")) as f:
            tdata = json.load(f)
            all_tools.extend(tdata.get("tools", []))
    return all_tools


def load_narrative_capabilities():
    """Loads consolidated capability matrix for Nanobanana, Omni, Lyria, and AVTool."""
    servers_dir = os.path.join(HERE, "servers")
    combined_caps = {}
    for sname in ["nanobanana", "omni", "lyria", "avtool"]:
        caps_path = os.path.join(servers_dir, sname, "capabilities.json")
        if os.path.exists(caps_path):
            with open(caps_path) as f:
                combined_caps[sname] = json.load(f)
    return combined_caps


def run_narrative_evaluation(enriched=True, second_judge=False):
    """Evaluates narrative multi-tool transcripts using the unified judge."""
    import gemini_client as gc
    import judge
    from linter import DeterministicCapabilityLinter

    linter = DeterministicCapabilityLinter()
    all_tools = load_narrative_tools()
    all_caps = load_narrative_capabilities()
    tool_specs_raw = json.dumps(all_tools, indent=2)

    if enriched:
        tool_specs = (
            tool_specs_raw
            + "\n\nCRITICAL MULTI-SERVER CAPABILITY MATRICES (MUST ENFORCE):\n"
            + json.dumps(all_caps, indent=2)
        )
    else:
        tool_specs = tool_specs_raw

    judges = ["gemini-2.5-flash"]
    if second_judge:
        judges.append("gemini-2.5-pro")

    print("\n========================================================")
    print(f"Running Narrative Cross-Server Media Production Evaluation (Enriched={enriched})")
    print(f"Tools in scope ({len(all_tools)}): {[t['name'] for t in all_tools]}")
    print("========================================================")

    results = []
    for label, kind, prompt, calls, fault, exp_tax in NARRATIVE_CASES:
        lint_res = linter.lint(calls)

        row = {
            "label": label,
            "kind": kind,
            "injected_fault": fault,
            "expected_taxonomy": exp_tax,
            "deterministic_linter": lint_res.to_dict(),
            "scores": {}
        }

        for j_model in judges:
            print(f"  [{j_model}] judging {label} ...", file=sys.stderr)
            res = judge.judge_tc(tool_specs, prompt, calls, model=j_model)
            row["scores"][j_model] = {
                "tc": round(res.get("tc_overall", 0.0), 3),
                "dimensions": res.get("dimensions", {}),
                "argument_subscores": res.get("argument_subscores", {}),
                "failures": res.get("failures", []),
                "rationale": res.get("rationale", "")
            }
        results.append(row)

    out_name = f"discrimination_narrative_pipeline{'_enriched' if enriched else ''}.json"
    out_path = os.path.join(ART, out_name)
    with open(out_path, "w") as f:
        json.dump({"pipeline": "narrative_media_production", "enriched": enriched, "results": results}, f, indent=2)
    print(f"\nSaved narrative pipeline results -> {out_path}")

    # Print summary table
    print("\n" + f"{'Case':<35} | {'Kind':<7} | {'Linter':<6} | {'TC (Flash)':<10} | Injected Fault")
    print("-" * 85)
    for r in results:
        linter_status = "VALID" if r["deterministic_linter"]["is_valid"] else "ERROR"
        tc_score = r["scores"]["gemini-2.5-flash"]["tc"]
        print(f"{r['label']:<35} | {r['kind']:<7} | {linter_status:<6} | {tc_score:<10.3f} | {r['injected_fault'][:30]}")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Narrative Pipeline Runner")
    parser.add_argument("--unenriched", action="store_true", help="Run baseline un-enriched judge")
    parser.add_argument("--second-judge", action="store_true", help="Include Gemini 2.5 Pro judge")
    args = parser.parse_args()
    run_narrative_evaluation(enriched=(not args.unenriched), second_judge=args.second_judge)
