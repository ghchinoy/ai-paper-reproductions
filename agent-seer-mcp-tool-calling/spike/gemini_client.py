"""Minimal Vertex AI Gemini client for the Agent Seer spike.

No third-party deps (the spike box has no pip / google-genai / requests): this
talks to the Vertex `generateContent` REST endpoint with urllib and a gcloud
access token. Kept deliberately small — this is throwaway spike scaffolding.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "ghchinoy-genai-sa")
# Vertex "global" endpoint works for the gemini-2.5-* models in this project.
LOCATION = "global"
_BASE = "https://aiplatform.googleapis.com/v1"

# Models used, matching the paper's roles:
#   generator = Gemini 2.5 Flash Lite (temp 0.7, structured output)
#   judge     = Gemini 2.5 Flash      (temp 0, deterministic)
GENERATOR_MODEL = "gemini-2.5-flash-lite"
JUDGE_MODEL = "gemini-2.5-flash"
# Same-family "second judge" for the optional circularity spot-check. NOT truly
# out-of-family (the paper uses Qwen3.5); documented as a limitation.
SECOND_JUDGE_MODEL = "gemini-2.5-pro"

_token_cache = {"tok": None, "ts": 0.0}


def _access_token():
    # Tokens last ~1h; cache for 30 min to avoid a gcloud fork per call.
    now = time.time()
    if _token_cache["tok"] and now - _token_cache["ts"] < 1800:
        return _token_cache["tok"]
    tok = subprocess.check_output(
        ["gcloud", "auth", "print-access-token"], text=True
    ).strip()
    _token_cache.update(tok=tok, ts=now)
    return tok


def generate(prompt, model, temperature=0.0, json_output=False, max_retries=3):
    """Single-turn generation. Returns the response text (str).

    On json_output=True we set responseMimeType=application/json so the model
    is constrained to emit parseable JSON (the paper's "structured output mode").
    Retries transient HTTP errors with backoff.
    """
    url = (
        f"{_BASE}/projects/{PROJECT}/locations/{LOCATION}"
        f"/publishers/google/models/{model}:generateContent"
    )
    gen_config = {"temperature": temperature, "maxOutputTokens": 8192}
    if json_output:
        gen_config["responseMimeType"] = "application/json"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }
    data = json.dumps(body).encode()
    last_err = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {_access_token()}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read())
            cand = payload["candidates"][0]
            parts = cand.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            if not text.strip():
                raise ValueError(f"empty response (finish={cand.get('finishReason')})")
            return text
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError) as e:
            last_err = e
            if isinstance(e, urllib.error.HTTPError):
                detail = e.read().decode(errors="replace")[:300]
                last_err = f"HTTP {e.code}: {detail}"
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"generate failed after {max_retries} tries: {last_err}")


def generate_json(prompt, model, temperature=0.0, max_retries=3):
    """generate() + tolerant JSON parse (strips ```json fences if present)."""
    for attempt in range(max_retries):
        raw = generate(prompt, model, temperature=temperature, json_output=True)
        txt = raw.strip()
        if txt.startswith("```"):
            txt = txt.split("```", 2)[1]
            if txt.startswith("json"):
                txt = txt[4:]
            txt = txt.strip().rstrip("`").strip()
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            if attempt == max_retries - 1:
                raise RuntimeError(f"could not parse JSON:\n{raw[:1000]}")
            time.sleep(1)
