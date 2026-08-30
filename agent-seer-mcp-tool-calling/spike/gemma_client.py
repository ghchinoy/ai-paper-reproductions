"""Vertex AI Model Garden & OpenAI-compatible client for Gemma 24B / Gemma out-of-family judging.

Supports:
1. Vertex AI Model Garden endpoints (via REST :predict / :generateContent with gcloud bearer token).
2. OpenAI-compatible endpoints (vLLM / Ollama / llama.cpp / Model Garden MaaS).
3. Standard JSON output extraction and retry backoff.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "ghchinoy-genai-sa")
LOCATION = os.environ.get("GEMMA_LOCATION", "us-central1")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL_ID", "gemma-2-27b-it")
GEMMA_ENDPOINT_URL = os.environ.get("GEMMA_ENDPOINT_URL", "")

_token_cache = {"tok": None, "ts": 0.0}


def _access_token():
    now = time.time()
    if _token_cache["tok"] and now - _token_cache["ts"] < 1800:
        return _token_cache["tok"]
    try:
        tok = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"], text=True
        ).strip()
        _token_cache.update(tok=tok, ts=now)
        return tok
    except Exception as e:
        return os.environ.get("GCP_ACCESS_TOKEN", "")


def generate(prompt, model=None, temperature=0.0, max_retries=3):
    """Generate text from Gemma via configured Model Garden or OpenAI endpoint."""
    model_name = model or GEMMA_MODEL
    last_err = None

    # Case A: Custom Endpoint URL (Model Garden Endpoint or OpenAI-compatible)
    if GEMMA_ENDPOINT_URL:
        url = GEMMA_ENDPOINT_URL
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get("GEMMA_API_KEY", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            token = _access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        # Determine payload style based on URL or standard OpenAI vs Vertex predict
        if "/chat/completions" in url or "/v1/" in url:
            body = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": 4096,
            }
        else:
            body = {
                "instances": [{"prompt": prompt}],
                "parameters": {"temperature": temperature, "maxOutputTokens": 4096},
            }
    else:
        # Case B: Vertex Model Garden Publisher / Endpoint fallback
        url = (
            f"https://{LOCATION}-aiplatform.googleapis.com/v1"
            f"/projects/{PROJECT}/locations/{LOCATION}"
            f"/publishers/google/models/{model_name}:predict"
        )
        token = _access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {
            "instances": [{"prompt": prompt}],
            "parameters": {"temperature": temperature, "maxOutputTokens": 4096},
        }

    data = json.dumps(body).encode()

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url, data=data, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read())

            # Parse response across different hosting schemas
            if "choices" in payload:  # OpenAI / vLLM style
                return payload["choices"][0]["message"]["content"]
            elif "predictions" in payload:  # Vertex AI :predict style
                pred = payload["predictions"][0]
                if isinstance(pred, dict):
                    return pred.get("content", "") or pred.get("text", "") or str(pred)
                return str(pred)
            elif "candidates" in payload:  # Vertex AI :generateContent style
                cand = payload["candidates"][0]
                parts = cand.get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts)
            else:
                return str(payload)

        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError) as e:
            last_err = e
            if isinstance(e, urllib.error.HTTPError):
                detail = e.read().decode(errors="replace")[:300]
                last_err = f"HTTP {e.code}: {detail}"
            time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"Gemma generate failed after {max_retries} tries: {last_err}")


def generate_json(prompt, model=None, temperature=0.0, max_retries=3):
    """generate() + tolerant JSON parser for Gemma structured judging."""
    model_name = model or GEMMA_MODEL
    for attempt in range(max_retries):
        raw = generate(prompt, model=model_name, temperature=temperature)
        txt = raw.strip()
        if "```json" in txt:
            txt = txt.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in txt:
            txt = txt.split("```", 1)[1].split("```", 1)[0]
        txt = txt.strip()
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Gemma could not parse JSON:\n{raw[:1000]}")
            time.sleep(1)
