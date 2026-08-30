"""Cross-Server Multi-Tool Orchestration Pipeline & Discrimination Suite.

Chains tools across mcp-nanobanana-go, mcp-veo-go, mcp-lyria-go, and mcp-avtool-go.
Implements the Tier 2 recommendation from the Agent Seer roadmap.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "artifacts")
os.makedirs(ART, exist_ok=True)

# Master multi-tool scenario prompt
PROMPT_CROSS_SERVER = (
    "Create a 16:9 animated cinematic commercial for a solar-powered vehicle: "
    "1. First generate a 16:9 concept image of the sleek solar car at sunset in 2K. "
    "2. Animate that image into a video clip saved to gs://mybucket/anim.mp4. "
    "3. Compose a 30-second futuristic electronic ambient soundtrack saved to gs://mybucket/bgm.wav. "
    "4. Combine the video and audio into a final video saved to gs://mybucket/commercial.mp4."
)

CROSS_SERVER_CASES = [
    # (label, kind, prompt, agent_calls, injected_fault, expected_taxonomy)
    ("CS0-correct-pipeline", "correct", PROMPT_CROSS_SERVER, [
        {
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "sleek aerodynamic solar vehicle driving at sunset, cinematic lighting, 16:9",
                "model": "gemini-3.1-flash-image",
                "aspect_ratio": "16:9",
                "image_size": "2K",
                "gcs_bucket_uri": "gs://mybucket/outputs/",
                "output_filename": "car_sunset.png"
            }
        },
        {
            "function_name": "veo_i2v",
            "parameters": {
                "image_uri": "gs://mybucket/outputs/car_sunset.png",
                "prompt": "the solar car accelerates smoothly down a coastal highway during golden hour",
                "model": "veo-3.1-generate-001",
                "aspect_ratio": "16:9",
                "bucket": "gs://mybucket/outputs/"
            }
        },
        {
            "function_name": "lyria_generate_music",
            "parameters": {
                "prompt": "uplifting futuristic electronic ambient synth with gentle pulse",
                "model_id": "lyria-3-clip-preview",
                "output_gcs_bucket": "mybucket",
                "output_filename": "bgm.wav"
            }
        },
        {
            "function_name": "ffmpeg_combine_audio_and_video",
            "parameters": {
                "input_video_uri": "gs://mybucket/outputs/car_sunset_video.mp4",
                "input_audio_uri": "gs://mybucket/bgm.wav",
                "output_filename": "commercial.mp4",
                "output_gcs_bucket": "mybucket"
            }
        }
    ], "none", "none"),

    ("CS1-broken-uri-pipe", "broken", PROMPT_CROSS_SERVER, [
        {
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "sleek aerodynamic solar vehicle driving at sunset",
                "model": "gemini-3.1-flash-image",
                "aspect_ratio": "16:9",
                "gcs_bucket_uri": "gs://mybucket/outputs/",
                "output_filename": "car_sunset.png"
            }
        },
        {
            "function_name": "veo_i2v",
            "parameters": {
                # BROKEN: references a hallucinated/wrong image URI
                "image_uri": "gs://mybucket/outputs/wrong_random_frame.png",
                "prompt": "the solar car accelerates smoothly",
                "model": "veo-3.1-generate-001",
                "aspect_ratio": "16:9",
                "bucket": "gs://mybucket/outputs/"
            }
        },
        {
            "function_name": "lyria_generate_music",
            "parameters": {
                "prompt": "futuristic electronic synth",
                "model_id": "lyria-3-clip-preview",
                "output_gcs_bucket": "mybucket"
            }
        },
        {
            "function_name": "ffmpeg_combine_audio_and_video",
            "parameters": {
                "input_video_uri": "gs://mybucket/outputs/video.mp4",
                "input_audio_uri": "gs://mybucket/bgm.wav",
                "output_gcs_bucket": "mybucket"
            }
        }
    ], "Step 2 image_uri is broken: does not reference upstream nanobanana output URI", "argument_value"),

    ("CS2-aspect-ratio-mismatch", "broken", PROMPT_CROSS_SERVER, [
        {
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "sleek aerodynamic solar vehicle driving at sunset",
                "model": "gemini-3.1-flash-image",
                # BROKEN: Generated 9:16 vertical image instead of requested 16:9
                "aspect_ratio": "9:16",
                "gcs_bucket_uri": "gs://mybucket/outputs/",
                "output_filename": "car_sunset.png"
            }
        },
        {
            "function_name": "veo_i2v",
            "parameters": {
                "image_uri": "gs://mybucket/outputs/car_sunset.png",
                "prompt": "the solar car accelerates smoothly",
                "model": "veo-3.1-generate-001",
                "aspect_ratio": "16:9",
                "bucket": "gs://mybucket/outputs/"
            }
        },
        {
            "function_name": "lyria_generate_music",
            "parameters": {
                "prompt": "futuristic synth",
                "model_id": "lyria-3-clip-preview",
                "output_gcs_bucket": "mybucket"
            }
        },
        {
            "function_name": "ffmpeg_combine_audio_and_video",
            "parameters": {
                "input_video_uri": "gs://mybucket/outputs/video.mp4",
                "input_audio_uri": "gs://mybucket/bgm.wav",
                "output_gcs_bucket": "mybucket"
            }
        }
    ], "Step 1 generated 9:16 portrait image violating prompt request for 16:9 landscape", "argument_value"),

    ("CS3-broken-pipeline-ordering", "broken", PROMPT_CROSS_SERVER, [
        {
            "function_name": "nanobanana_image_generation",
            "parameters": {
                "prompt": "sleek aerodynamic solar vehicle driving at sunset",
                "model": "gemini-3.1-flash-image",
                "aspect_ratio": "16:9",
                "output_filename": "car_sunset.png"
            }
        },
        # BROKEN: Calling combine_audio_and_video before video and music have even been synthesized!
        {
            "function_name": "ffmpeg_combine_audio_and_video",
            "parameters": {
                "input_video_uri": "gs://mybucket/outputs/video.mp4",
                "input_audio_uri": "gs://mybucket/bgm.wav",
                "output_gcs_bucket": "mybucket"
            }
        },
        {
            "function_name": "veo_i2v",
            "parameters": {
                "image_uri": "gs://mybucket/outputs/car_sunset.png",
                "prompt": "the solar car accelerates smoothly",
                "model": "veo-3.1-generate-001"
            }
        },
        {
            "function_name": "lyria_generate_music",
            "parameters": {
                "prompt": "futuristic electronic synth",
                "model_id": "lyria-3-clip-preview"
            }
        }
    ], "ffmpeg_combine_audio_and_video invoked out of order before video and audio were generated", "ordering_sequence_logic")
]


def run_cross_server_evaluation(enriched=True, second_judge=False):
    """Evaluates cross-server multi-tool transcripts using the unified judge."""
    import gemini_client as gc
    import judge
    from linter import DeterministicCapabilityLinter

    linter = DeterministicCapabilityLinter()
    all_tools = list(linter.schemas.values())
    tool_specs_raw = json.dumps(all_tools, indent=2)

    if enriched:
        tool_specs = (
            tool_specs_raw
            + "\n\nCRITICAL MULTI-SERVER CAPABILITY MATRICES (MUST ENFORCE):\n"
            + json.dumps(linter.capabilities, indent=2)
        )
    else:
        tool_specs = tool_specs_raw

    judges = ["gemini-2.5-flash"]
    if second_judge:
        judges.append("gemini-2.5-pro")

    print("\n========================================================")
    print(f"Running Cross-Server Multi-Tool Evaluation (Enriched={enriched})")
    print(f"Tools in scope: {[t['name'] for t in all_tools]}")
    print("========================================================")

    results = []
    for label, kind, prompt, calls, fault, exp_tax in CROSS_SERVER_CASES:
        # 1. Deterministic pre-pass
        lint_res = linter.lint(calls)

        row = {
            "label": label,
            "kind": kind,
            "injected_fault": fault,
            "expected_taxonomy": exp_tax,
            "deterministic_linter": lint_res.to_dict(),
            "scores": {}
        }

        # 2. LLM Judge
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

    out_name = f"discrimination_cross_server{'_enriched' if enriched else ''}.json"
    out_path = os.path.join(ART, out_name)
    with open(out_path, "w") as f:
        json.dump({"pipeline": "cross_server_media_production", "enriched": enriched, "results": results}, f, indent=2)
    print(f"\nSaved cross-server results -> {out_path}")

    # Print summary table
    print("\n" + f"{'Case':<30} | {'Kind':<7} | {'Linter':<6} | {'TC (Flash)':<10} | Injected Fault")
    print("-" * 80)
    for r in results:
        linter_status = "VALID" if r["deterministic_linter"]["is_valid"] else "ERROR"
        tc_score = r["scores"]["gemini-2.5-flash"]["tc"]
        print(f"{r['label']:<30} | {r['kind']:<7} | {linter_status:<6} | {tc_score:<10.3f} | {r['injected_fault'][:30]}")

    return results


if __name__ == "__main__":
    run_cross_server_evaluation(enriched=True)
