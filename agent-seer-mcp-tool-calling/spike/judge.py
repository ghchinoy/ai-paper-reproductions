"""Judge runner: applies the TC + Coherence rubric prompts and aggregates.

Supports both Gemini (primary & same-family Pro) and Gemma (out-of-family) backends.
"""
import json

import gemini_client as gc
import gemma_client as gmc
import prompts
import scoring


def _generate_json(prompt, model, temperature=0.0):
    if model and ("gemma" in model.lower()):
        return gmc.generate_json(prompt, model=model, temperature=temperature)
    return gc.generate_json(prompt, model=model or gc.JUDGE_MODEL, temperature=temperature)


def judge_tc(tool_specs_json, user_prompt, agent_calls, model=None):
    model = model or gc.JUDGE_MODEL
    prompt = prompts.TC_JUDGE_PROMPT.format(
        tool_specs=tool_specs_json,
        user_prompt=user_prompt,
        agent_calls=json.dumps(agent_calls, indent=2),
    )
    raw = _generate_json(prompt, model, temperature=0.0)
    agg = scoring.aggregate_tc(raw)
    agg["_raw"] = raw
    return agg


def judge_coherence(transcript_text, model=None):
    model = model or gc.JUDGE_MODEL
    prompt = prompts.COHERENCE_JUDGE_PROMPT.format(transcript=transcript_text)
    raw = _generate_json(prompt, model, temperature=0.0)
    agg = scoring.aggregate_coherence(raw)
    agg["_raw"] = raw
    return agg
