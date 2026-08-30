"""LLM Client Abstraction Layer for Agent Seer (arXiv:2608.26133).

Provides zero-external-dependency clients for Vertex AI Gemini, Model Garden Gemma,
OpenAI-compatible inference servers, and comprehensive offline MockClient.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import logging
import math
import os
import random
import re
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Pattern, Sequence, Union
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger("agent_seer.clients")


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class LLMClientError(Exception):
    """Base exception for all Agent Seer LLM client operations."""

    def __init__(
        self,
        message: str,
        raw_error: Optional[Exception] = None,
        status_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.raw_error = raw_error
        self.status_code = status_code


class LLMAuthError(LLMClientError):
    """Raised when authentication fails (missing credentials, expired token, 401/403)."""
    pass


class LLMRateLimitError(LLMClientError):
    """Raised when rate limits or quotas are exceeded (HTTP 429 / RESOURCE_EXHAUSTED)."""
    pass


class LLMTimeoutError(LLMClientError):
    """Raised when request times out."""
    pass


class LLMResponseFormatError(LLMClientError, ValueError):
    """Raised when the model output cannot be parsed into the expected JSON format."""
    pass


class LLMModelNotFoundError(LLMClientError):
    """Raised when the specified model or endpoint is not found (HTTP 404)."""
    pass


class LLMConnectionError(LLMClientError):
    """Raised when network connection fails (DNS resolution, connection refused)."""
    pass


# --------------------------------------------------------------------------
# Data Models
# --------------------------------------------------------------------------

@dataclass
class TokenUsage:
    """Token usage metadata for an LLM generation call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TokenUsage:
        prompt = int(data.get("prompt_tokens") or data.get("promptTokenCount") or 0)
        completion = int(data.get("completion_tokens") or data.get("candidatesTokenCount") or 0)
        total = int(data.get("total_tokens") or data.get("totalTokenCount") or (prompt + completion))
        cached = data.get("cached_tokens") or data.get("cachedContentTokenCount")
        return cls(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cached_tokens=int(cached) if cached is not None else None,
        )


@dataclass
class LLMResponse:
    """Standardized response object from any LLM client."""

    text: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    finish_reason: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def content(self) -> str:
        """Alias for text for OpenAI / LangChain compatibility."""
        return self.text

    def json(self) -> Dict[str, Any]:
        """Extracts and parses JSON from response text, stripping code fences."""
        return extract_json_payload(self.text)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "usage": self.usage.to_dict(),
            "latency_ms": round(self.latency_ms, 3),
            "finish_reason": self.finish_reason,
            "raw_response": self.raw_response,
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        return self.text


def extract_json_payload(text: str) -> Dict[str, Any]:
    """Robust helper to extract JSON dictionary from raw model text."""
    if not isinstance(text, str):
        if isinstance(text, dict):
            return text
        if isinstance(text, list):
            return {"items": text}
        return {"data": text}

    cleaned = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if m:
        cleaned = m.group(1).strip()
    elif "```" in cleaned:
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        if isinstance(parsed, (int, bool)) or (isinstance(parsed, float) and not math.isnan(parsed) and not math.isinf(parsed)):
            return {"data": parsed}
    except json.JSONDecodeError:
        pass

    # Search for outer { ... }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        sub = cleaned[start : end + 1]
        try:
            parsed = json.loads(sub)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            # Attempt to strip trailing commas
            fixed = re.sub(r",\s*([\]}])", r"\1", sub)
            try:
                parsed = json.loads(fixed)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

    # Search for outer [ ... ]
    start_arr = cleaned.find("[")
    end_arr = cleaned.rfind("]")
    if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
        sub_arr = cleaned[start_arr : end_arr + 1]
        try:
            parsed_arr = json.loads(sub_arr)
            if isinstance(parsed_arr, list):
                return {"items": parsed_arr}
        except json.JSONDecodeError:
            fixed_arr = re.sub(r",\s*([\]}])", r"\1", sub_arr)
            try:
                parsed_arr = json.loads(fixed_arr)
                if isinstance(parsed_arr, list):
                    return {"items": parsed_arr}
            except json.JSONDecodeError:
                pass

    raise LLMResponseFormatError(f"Failed to parse JSON payload from response text:\n{text[:500]}")


# --------------------------------------------------------------------------
# Base Client Interface
# --------------------------------------------------------------------------

class BaseLLMClient(ABC):
    """Abstract base class / Protocol for all LLM clients in Agent Seer."""

    def __init__(
        self,
        default_model: str = "",
        temperature: float = 0.0,
        max_retries: int = 3,
        timeout: float = 120.0,
        backoff_factor: float = 2.0,
    ):
        self.default_model = default_model
        self.temperature = temperature
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_factor = backoff_factor

    @abstractmethod
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_output: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a text response for the given prompt."""
        raise NotImplementedError

    def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate structured JSON response, parsing the model output."""
        response = self.generate(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_output=True,
            **kwargs,
        )
        return response.json()


# --------------------------------------------------------------------------
# VertexGeminiClient
# --------------------------------------------------------------------------

class VertexGeminiClient(BaseLLMClient):
    """Production client for Vertex AI Gemini models with zero external dependencies."""

    DEFAULT_GENERATOR_MODEL = "gemini-2.5-flash-lite"
    DEFAULT_JUDGE_MODEL = "gemini-2.5-flash"
    DEFAULT_PRO_MODEL = "gemini-2.5-pro"

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: str = "global",
        default_model: str = "gemini-2.5-flash",
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        temperature: float = 0.0,
        max_retries: int = 3,
        timeout: float = 120.0,
        backoff_factor: float = 2.0,
        custom_endpoint: Optional[str] = None,
    ):
        super().__init__(
            default_model=default_model,
            temperature=temperature,
            max_retries=max_retries,
            timeout=timeout,
            backoff_factor=backoff_factor,
        )
        self.project_id = self._resolve_project(project_id)
        self.location = os.environ.get("VERTEX_LOCATION") or os.environ.get("GOOGLE_CLOUD_REGION") or location
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("VERTEX_API_KEY")
        self.access_token = access_token or os.environ.get("GCP_ACCESS_TOKEN")
        self.custom_endpoint = custom_endpoint
        self._token_cache: Dict[str, Any] = {
            "token": self.access_token,
            "timestamp": time.time() if self.access_token else 0.0,
        }

    def _resolve_project(self, explicit_project: Optional[str]) -> str:
        if explicit_project:
            return explicit_project
        for env_key in ("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT", "PROJECT_ID"):
            val = os.environ.get(env_key)
            if val:
                return val
        try:
            val = subprocess.check_output(
                ["gcloud", "config", "get-value", "project"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if val and val != "(unset)":
                return val
        except Exception:
            pass
        return "ghchinoy-genai-sa"

    def _get_bearer_token(self) -> str:
        now = time.time()
        if self._token_cache["token"] and (now - self._token_cache["timestamp"] < 1800):
            return self._token_cache["token"]
        try:
            tok = subprocess.check_output(
                ["gcloud", "auth", "print-access-token"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            self._token_cache = {"token": tok, "timestamp": now}
            return tok
        except Exception as e:
            if self.access_token:
                return self.access_token
            raise LLMAuthError(
                "Failed to acquire GCP access token. Set GEMINI_API_KEY, GCP_ACCESS_TOKEN, or run gcloud auth login.",
                raw_error=e,
            )

    def _build_url(self, model: str) -> str:
        if self.custom_endpoint:
            return self.custom_endpoint
        if self.api_key:
            return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        if self.location == "global":
            return (
                f"https://aiplatform.googleapis.com/v1/projects/{self.project_id}"
                f"/locations/global/publishers/google/models/{model}:generateContent"
            )
        return (
            f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/{self.location}/publishers/google/models/{model}:generateContent"
        )

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_output: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        model_name = model or self.default_model
        temp = self.temperature if temperature is None else temperature
        max_tok = max_tokens or 8192

        url = self._build_url(model_name)
        gen_config: Dict[str, Any] = {"temperature": temp, "maxOutputTokens": max_tok}
        if json_output:
            gen_config["responseMimeType"] = "application/json"

        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        data = json.dumps(body).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if not self.api_key:
            token = self._get_bearer_token()
            headers["Authorization"] = f"Bearer {token}"

        last_error = None
        for attempt in range(self.max_retries):
            start_t = time.perf_counter()
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw_bytes = resp.read()
                    status_code = getattr(resp, "status", getattr(resp, "code", 200))
                latency_ms = (time.perf_counter() - start_t) * 1000.0

                payload = json.loads(raw_bytes.decode("utf-8"))
                candidates = payload.get("candidates", [])
                if not candidates:
                    finish_reason = payload.get("promptFeedback", {}).get("blockReason")
                    raise LLMResponseFormatError(
                        f"No candidates returned in Gemini response (blockReason: {finish_reason}): {payload}"
                    )

                cand = candidates[0]
                parts = cand.get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                finish_reason = cand.get("finishReason")

                usage_meta = payload.get("usageMetadata", {})
                usage = TokenUsage.from_dict(usage_meta)

                return LLMResponse(
                    text=text,
                    model=model_name,
                    usage=usage,
                    latency_ms=latency_ms,
                    finish_reason=finish_reason,
                    raw_response=payload,
                    metadata={"attempt": attempt + 1, "status_code": status_code},
                )

            except urllib.error.HTTPError as e:
                latency_ms = (time.perf_counter() - start_t) * 1000.0
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    detail = str(e)
                status = e.code

                if status in (401, 403):
                    raise LLMAuthError(
                        f"Vertex Gemini Authentication failed (HTTP {status}): {detail}",
                        raw_error=e,
                        status_code=status,
                    )
                elif status == 404:
                    raise LLMModelNotFoundError(
                        f"Vertex Gemini model '{model_name}' not found (HTTP 404): {detail}",
                        raw_error=e,
                        status_code=status,
                    )
                elif status == 429:
                    last_error = LLMRateLimitError(
                        f"Vertex Gemini Rate limit exceeded (HTTP 429): {detail}",
                        raw_error=e,
                        status_code=status,
                    )
                elif status in (500, 502, 503, 504):
                    last_error = LLMClientError(
                        f"Vertex Gemini Server error (HTTP {status}): {detail}",
                        raw_error=e,
                        status_code=status,
                    )
                else:
                    raise LLMClientError(
                        f"Vertex Gemini HTTP {status} error: {detail}",
                        raw_error=e,
                        status_code=status,
                    )

            except urllib.error.URLError as e:
                last_error = LLMConnectionError(f"Vertex Gemini connection failed: {e}", raw_error=e)
            except LLMResponseFormatError:
                raise
            except Exception as e:
                last_error = e

            if attempt < self.max_retries - 1:
                sleep_sec = (self.backoff_factor ** attempt) + random.uniform(0.1, 0.5)
                time.sleep(sleep_sec)

        raise last_error or LLMClientError(f"Vertex Gemini generation failed after {self.max_retries} attempts.")


# --------------------------------------------------------------------------
# ModelGardenGemmaClient
# --------------------------------------------------------------------------

class ModelGardenGemmaClient(BaseLLMClient):
    """Production client for Gemma & OpenAI-compatible endpoints with zero third-party dependencies."""

    DEFAULT_GEMMA_MODEL = "gemma-2-27b-it"

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        project_id: Optional[str] = None,
        location: str = "us-central1",
        default_model: str = "gemma-2-27b-it",
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        temperature: float = 0.0,
        max_retries: int = 3,
        timeout: float = 120.0,
        backoff_factor: float = 2.0,
    ):
        super().__init__(
            default_model=default_model,
            temperature=temperature,
            max_retries=max_retries,
            timeout=timeout,
            backoff_factor=backoff_factor,
        )
        self.endpoint_url = endpoint_url or os.environ.get("GEMMA_ENDPOINT_URL") or os.environ.get("OPENAI_BASE_URL")
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "ghchinoy-genai-sa")
        self.location = os.environ.get("GEMMA_LOCATION") or os.environ.get("GOOGLE_CLOUD_REGION") or location
        self.api_key = api_key or os.environ.get("GEMMA_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.access_token = access_token or os.environ.get("GCP_ACCESS_TOKEN")
        self._token_cache: Dict[str, Any] = {
            "token": self.access_token,
            "timestamp": time.time() if self.access_token else 0.0,
        }

    def _get_auth_header(self) -> Dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        now = time.time()
        if self._token_cache["token"] and (now - self._token_cache["timestamp"] < 1800):
            return {"Authorization": f"Bearer {self._token_cache['token']}"}
        try:
            tok = subprocess.check_output(
                ["gcloud", "auth", "print-access-token"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            self._token_cache = {"token": tok, "timestamp": now}
            return {"Authorization": f"Bearer {tok}"}
        except Exception:
            if self.access_token:
                return {"Authorization": f"Bearer {self.access_token}"}
            return {}

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_output: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        model_name = model or self.default_model
        temp = self.temperature if temperature is None else temperature
        max_tok = max_tokens or 4096

        headers = {"Content-Type": "application/json"}
        headers.update(self._get_auth_header())

        if self.endpoint_url:
            url = self.endpoint_url
            if "/chat/completions" in url or "/v1/" in url:
                # OpenAI / vLLM / Ollama schema
                body: Dict[str, Any] = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temp,
                    "max_tokens": max_tok,
                }
                if json_output:
                    body["response_format"] = {"type": "json_object"}
            else:
                # Custom :predict endpoint schema
                body = {
                    "instances": [{"prompt": prompt}],
                    "parameters": {"temperature": temp, "maxOutputTokens": max_tok},
                }
        else:
            # Vertex Model Garden :predict default URL
            url = (
                f"https://{self.location}-aiplatform.googleapis.com/v1"
                f"/projects/{self.project_id}/locations/{self.location}"
                f"/publishers/google/models/{model_name}:predict"
            )
            body = {
                "instances": [{"prompt": prompt}],
                "parameters": {"temperature": temp, "maxOutputTokens": max_tok},
            }

        data = json.dumps(body).encode("utf-8")
        last_error = None

        for attempt in range(self.max_retries):
            start_t = time.perf_counter()
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw_bytes = resp.read()
                    status_code = getattr(resp, "status", getattr(resp, "code", 200))
                latency_ms = (time.perf_counter() - start_t) * 1000.0

                payload = json.loads(raw_bytes.decode("utf-8"))
                text = ""
                finish_reason = None
                usage = TokenUsage()

                # Multi-schema extraction
                if "choices" in payload and payload["choices"]:
                    choice = payload["choices"][0]
                    text = choice.get("message", {}).get("content", "")
                    finish_reason = choice.get("finish_reason")
                    if "usage" in payload:
                        usage = TokenUsage.from_dict(payload["usage"])
                elif "predictions" in payload and payload["predictions"]:
                    pred = payload["predictions"][0]
                    if isinstance(pred, dict):
                        text = pred.get("content") or pred.get("text") or json.dumps(pred)
                    else:
                        text = str(pred)
                elif "candidates" in payload and payload["candidates"]:
                    cand = payload["candidates"][0]
                    parts = cand.get("content", {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts)
                    finish_reason = cand.get("finishReason")
                    if "usageMetadata" in payload:
                        usage = TokenUsage.from_dict(payload["usageMetadata"])
                else:
                    text = str(payload)

                return LLMResponse(
                    text=text,
                    model=model_name,
                    usage=usage,
                    latency_ms=latency_ms,
                    finish_reason=finish_reason,
                    raw_response=payload,
                    metadata={"attempt": attempt + 1, "status_code": status_code},
                )

            except urllib.error.HTTPError as e:
                latency_ms = (time.perf_counter() - start_t) * 1000.0
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    detail = str(e)
                status = e.code

                if status in (401, 403):
                    raise LLMAuthError(
                        f"Gemma Authentication failed (HTTP {status}): {detail}",
                        raw_error=e,
                        status_code=status,
                    )
                elif status == 404:
                    raise LLMModelNotFoundError(
                        f"Gemma endpoint or model not found (HTTP 404): {detail}",
                        raw_error=e,
                        status_code=status,
                    )
                elif status == 429:
                    last_error = LLMRateLimitError(
                        f"Gemma rate limit exceeded (HTTP 429): {detail}",
                        raw_error=e,
                        status_code=status,
                    )
                elif status in (500, 502, 503, 504):
                    last_error = LLMClientError(
                        f"Gemma server error (HTTP {status}): {detail}",
                        raw_error=e,
                        status_code=status,
                    )
                else:
                    raise LLMClientError(
                        f"Gemma HTTP {status} error: {detail}",
                        raw_error=e,
                        status_code=status,
                    )

            except urllib.error.URLError as e:
                last_error = LLMConnectionError(f"Gemma connection failed: {e}", raw_error=e)
            except Exception as e:
                last_error = e

            if attempt < self.max_retries - 1:
                sleep_sec = (self.backoff_factor ** attempt) + random.uniform(0.1, 0.5)
                time.sleep(sleep_sec)

        raise last_error or LLMClientError(f"Gemma generation failed after {self.max_retries} attempts.")


# --------------------------------------------------------------------------
# MockClient
# --------------------------------------------------------------------------

class MockClient(BaseLLMClient):
    """Deterministic offline mock LLM client for testing, CI/CD, and offline benchmarking."""

    def __init__(
        self,
        canned_responses: Optional[Union[Dict[str, Any], List[Any], str]] = None,
        canned_response: Optional[Union[Dict[str, Any], List[Any], str]] = None,
        response_sequence: Optional[List[Any]] = None,
        pattern_responses: Optional[Dict[str, Any]] = None,
        routes: Optional[Dict[str, Any]] = None,
        response_generator: Optional[Callable[..., Any]] = None,
        default_model: str = "mock-seer-model",
        simulated_latency_ms: float = 0.0,
        injected_errors: Optional[Union[Exception, List[Optional[Exception]], Dict[int, Exception]]] = None,
        error_to_raise: Optional[Exception] = None,
    ):
        super().__init__(default_model=default_model)

        raw_canned = canned_response if canned_response is not None else canned_responses
        seq = response_sequence if response_sequence is not None else (raw_canned if isinstance(raw_canned, list) else None)

        if seq is not None:
            self._queue = list(seq)
            self._canned = None
        else:
            self._queue = []
            self._canned = raw_canned

        self.pattern_responses = pattern_responses or routes or {}
        self.response_generator = response_generator
        self.simulated_latency_ms = simulated_latency_ms
        self.injected_errors = error_to_raise if error_to_raise is not None else injected_errors
        self.call_history: List[Dict[str, Any]] = []
        self._invocation_count: int = 0

    @property
    def last_prompt(self) -> Optional[str]:
        return self.call_history[-1]["prompt"] if self.call_history else None

    @property
    def last_call(self) -> Optional[Dict[str, Any]]:
        return self.call_history[-1] if self.call_history else None

    @property
    def call_count(self) -> int:
        return len(self.call_history)

    def reset(self) -> None:
        self.call_history.clear()
        self._invocation_count = 0

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_output: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        call_idx = self._invocation_count
        self._invocation_count += 1

        # Check injected error conditions
        if self.injected_errors is not None:
            if isinstance(self.injected_errors, dict) and call_idx in self.injected_errors:
                raise self.injected_errors[call_idx]
            elif isinstance(self.injected_errors, list) and call_idx < len(self.injected_errors):
                err = self.injected_errors[call_idx]
                if err:
                    raise err
            elif isinstance(self.injected_errors, Exception):
                raise self.injected_errors

        if self.simulated_latency_ms > 0:
            time.sleep(self.simulated_latency_ms / 1000.0)

        raw_payload = None

        # 1. Check response_generator callback
        if self.response_generator is not None:
            raw_payload = self.response_generator(prompt, model=model, temperature=temperature, **kwargs)
        # 2. Check pattern matches
        elif self.pattern_responses:
            for pattern, val in self.pattern_responses.items():
                if pattern in prompt or re.search(pattern, prompt):
                    raw_payload = val
                    break
        # 3. Check response queue
        if raw_payload is None and self._queue:
            raw_payload = self._queue.pop(0)
        # 4. Check static canned response
        if raw_payload is None and self._canned is not None:
            raw_payload = self._canned
        # 5. Default auto-generator based on prompt signature
        if raw_payload is None:
            raw_payload = self._auto_generate_mock(prompt)

        # Format output text
        if isinstance(raw_payload, (dict, list)):
            text = json.dumps(raw_payload)
        else:
            text = str(raw_payload)

        # Approximate token usage
        prompt_tokens = max(1, len(prompt.split()))
        completion_tokens = max(1, len(text.split()))
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

        response = LLMResponse(
            text=text,
            model=model or self.default_model,
            usage=usage,
            latency_ms=self.simulated_latency_ms,
            finish_reason="stop",
            raw_response=raw_payload if isinstance(raw_payload, dict) else None,
            metadata={"call_index": call_idx},
        )

        self.call_history.append({
            "prompt": prompt,
            "model": model or self.default_model,
            "temperature": temperature,
            "json_output": json_output,
            "kwargs": kwargs,
            "response": response,
            "timestamp": time.time(),
        })

        return response

    def _auto_generate_mock(self, prompt: str) -> Dict[str, Any]:
        """Auto-generates conformant structured mock responses matching Agent Seer prompts."""
        p_lower = prompt.lower()
        if "usage" in p_lower and "selection" in p_lower and "arguments" in p_lower:
            # TC Judge prompt
            return {
                "usage": {"necessity": 10, "overuse_detection": 10},
                "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
                "ordering": {"not_applicable": True},
                "arguments": {
                    "completeness": 10,
                    "name_accuracy": 10,
                    "value_accuracy": 10,
                    "type_compliance": 10,
                    "format_compliance": 10,
                    "relevancy": 10,
                },
                "failures": [],
                "rationale": "Mock evaluated: fully conformant tool execution.",
            }
        elif "logical_flow" in p_lower and "topic_relevance" in p_lower:
            # Coherence Judge prompt
            return {
                "logical_flow": 3,
                "completeness": 3,
                "conciseness": 3,
                "topic_relevance": 3,
                "context_retention": {"not_applicable": True, "score": None},
                "manifestations": [],
                "rationale": "Mock evaluated: coherent transcript.",
            }
        elif "what_it_does" in p_lower and "enterprise_context" in p_lower:
            # Stage 1 Interpretation prompt
            m_name = re.search(r'"(?:name|tool_name)":\s*"([^"]+)"', prompt)
            tool_name = m_name.group(1) if m_name else "mock_tool"
            return {
                "tool_name": tool_name,
                "what_it_does": f"Executes {tool_name} functionality for enterprise workflows.",
                "what_it_needs": "Structured parameters adhering to input schema.",
                "why_its_used": f"Automating enterprise tool calling evaluation for {tool_name}.",
                "enterprise_context": ["Media Production", "Automation", "Content Creation"],
            }
        elif "novel, and complex" in p_lower or "straightforward, and commonplace" in p_lower or "boundary" in p_lower:
            # Stage 2 Scenario generation prompt
            tier = "complex" if "novel, and complex" in p_lower else ("boundary" if "boundary" in p_lower else "simple")
            return {
                "categories": [
                    {
                        "category": "Standard Operations",
                        "scenarios": [
                            {
                                "title": "Basic Tool Invocation Scenario",
                                "prompt": "Run the tool to process media inputs.",
                                "agent_workflow": [
                                    {
                                        "function_name": "mock_tool",
                                        "parameters": {"action": "run"},
                                        "quick_explanation": "Executes primary action",
                                    }
                                ],
                                "novelty_reason": f"Validates baseline {tier} tool calling.",
                                "agent_followup": "Should I export the generated output?",
                            }
                        ],
                    }
                ]
            }
        elif "mock_workflow" in p_lower or "confidence level guidelines" in p_lower:
            # Stage 3 Mock Output generation prompt
            return {
                "mock_workflow": [
                    {
                        "function_name": "mock_tool",
                        "parameters": {"action": "run"},
                        "quick_explanation": "Executes primary action",
                        "mock_output": {
                            "content": [
                                {"type": "text", "text": "Successfully generated artifact."},
                                {"type": "resource_link", "uri": "gs://bucket/sample_output.mp4"},
                            ]
                        },
                        "confidence": "high",
                    }
                ],
                "expected_response": {
                    "status": "success",
                    "output_uri": "gs://bucket/sample_output.mp4",
                },
            }
        elif "multi-turn" in p_lower or "state chaining" in p_lower:
            # Stage 4 Multi-turn transcript prompt
            return {
                "scenario_title": "Mock Multi-Turn Scenario",
                "turns": [
                    {
                        "turn_index": 1,
                        "user_message": "Run initial tool invocation.",
                        "agent_tool_calls": [{"name": "mock_tool", "arguments": {"action": "run"}}],
                        "tool_responses": [{"tool_name": "mock_tool", "output": {"uri": "gs://bucket/out1.mp4"}}],
                        "agent_response": "I have created the initial asset at gs://bucket/out1.mp4.",
                    },
                    {
                        "turn_index": 2,
                        "user_message": "Can you extend that video?",
                        "agent_tool_calls": [{"name": "mock_tool", "arguments": {"action": "extend", "input_uri": "gs://bucket/out1.mp4"}}],
                        "tool_responses": [{"tool_name": "mock_tool", "output": {"uri": "gs://bucket/out2.mp4"}}],
                        "agent_response": "The extended video is ready at gs://bucket/out2.mp4.",
                    },
                ],
            }
        return {"status": "success", "content": "Mock response"}

    # Factory methods for specialized test cases
    @classmethod
    def for_tc_judge(
        cls,
        overall_score: float = 1.0,
        failures: Optional[List[str]] = None,
        rationale: str = "Mock evaluation",
    ) -> MockClient:
        score_10 = int(round(overall_score * 10))
        canned = {
            "usage": {"necessity": score_10, "overuse_detection": score_10},
            "selection": {"correctness": score_10, "specificity": score_10, "completeness": score_10},
            "ordering": {"not_applicable": True},
            "arguments": {
                "completeness": score_10,
                "name_accuracy": score_10,
                "value_accuracy": score_10,
                "type_compliance": score_10,
                "format_compliance": score_10,
                "relevancy": score_10,
            },
            "failures": failures or ([] if overall_score >= 0.85 else ["argument_value"]),
            "rationale": rationale,
        }
        return cls(canned_responses=canned)

    @classmethod
    def for_coherence_judge(
        cls,
        score_3: int = 3,
        manifestations: Optional[List[str]] = None,
    ) -> MockClient:
        canned = {
            "logical_flow": score_3,
            "completeness": score_3,
            "conciseness": score_3,
            "topic_relevance": score_3,
            "context_retention": {"not_applicable": True, "score": None},
            "manifestations": manifestations or [],
            "rationale": "Mock coherence evaluation",
        }
        return cls(canned_responses=canned)

    @classmethod
    def for_pipeline_stage1(cls, tool_name: str = "sample_tool") -> MockClient:
        return cls(canned_responses={
            "tool_name": tool_name,
            "what_it_does": f"Processes data using {tool_name}.",
            "what_it_needs": "Required and optional parameters per schema.",
            "why_its_used": "Automating enterprise operations.",
            "enterprise_context": ["Automation", "Media Production"],
        })

    @classmethod
    def for_pipeline_stage2(cls, tool_name: str = "sample_tool") -> MockClient:
        return cls(canned_responses={
            "categories": [{
                "category": "Standard Operations",
                "scenarios": [{
                    "title": f"Execute {tool_name}",
                    "prompt": f"Please run {tool_name} with sample parameters.",
                    "agent_workflow": [{
                        "function_name": tool_name,
                        "parameters": {"prompt": "sample"},
                        "quick_explanation": "Execute tool",
                    }],
                    "novelty_reason": "Single tool execution test",
                    "agent_followup": "Would you like me to adjust settings?",
                }],
            }]
        })

    @classmethod
    def for_pipeline_stage3(cls, tool_name: str = "sample_tool") -> MockClient:
        return cls(canned_responses={
            "mock_workflow": [{
                "function_name": tool_name,
                "parameters": {"prompt": "sample"},
                "quick_explanation": "Execute tool",
                "mock_output": {
                    "content": [
                        {"type": "text", "text": "Generated artifact successfully."},
                        {"type": "resource_link", "uri": "gs://bucket/sample.mp4"},
                    ]
                },
                "confidence": "high",
            }],
            "expected_response": {"status": "success", "uri": "gs://bucket/sample.mp4"},
        })

    @classmethod
    def for_pipeline_stage4(cls) -> MockClient:
        return cls(canned_responses={
            "scenario_title": "Multi-Turn Scenario",
            "turns": [
                {
                    "turn_index": 1,
                    "user_message": "Generate initial video.",
                    "agent_tool_calls": [{"name": "sample_tool", "arguments": {"prompt": "test"}}],
                    "tool_responses": [{"tool_name": "sample_tool", "output": {"uri": "gs://bucket/1.mp4"}}],
                    "agent_response": "Initial video is ready at gs://bucket/1.mp4.",
                },
                {
                    "turn_index": 2,
                    "user_message": "Extend the video duration.",
                    "agent_tool_calls": [{"name": "sample_tool", "arguments": {"uri": "gs://bucket/1.mp4"}}],
                    "tool_responses": [{"tool_name": "sample_tool", "output": {"uri": "gs://bucket/2.mp4"}}],
                    "agent_response": "Extended video is ready at gs://bucket/2.mp4.",
                },
            ],
        })

    # Test assertion helpers
    def assert_called(self, count: Optional[int] = None) -> None:
        if count is not None and len(self.call_history) != count:
            raise AssertionError(
                f"Expected MockClient to be called {count} times, but was called {len(self.call_history)} times."
            )
        if not self.call_history:
            raise AssertionError("Expected MockClient to have been called at least once, but call history is empty.")

    def assert_called_with_prompt_containing(self, substring: str) -> None:
        matched = any(substring in call["prompt"] for call in self.call_history)
        if not matched:
            raise AssertionError(
                f"Substring '{substring}' not found in any of the {len(self.call_history)} prompts sent to MockClient."
            )


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def create_client(
    client_type: str = "auto",
    model: Optional[str] = None,
    **kwargs: Any,
) -> BaseLLMClient:
    """Factory function to construct the appropriate BaseLLMClient instance.

    Args:
        client_type: One of 'auto', 'vertex', 'gemini', 'gemma', 'openai', 'mock'.
        model: Optional default model name.
        **kwargs: Additional client-specific configuration.
    """
    c_type = client_type.lower()

    if c_type == "mock" or os.environ.get("MOCK_LLM", "").lower() in ("1", "true", "yes"):
        return MockClient(default_model=model or "mock-seer-model", **kwargs)

    if c_type in ("vertex", "gemini"):
        return VertexGeminiClient(default_model=model or VertexGeminiClient.DEFAULT_JUDGE_MODEL, **kwargs)

    if c_type in ("gemma", "openai"):
        return ModelGardenGemmaClient(default_model=model or ModelGardenGemmaClient.DEFAULT_GEMMA_MODEL, **kwargs)

    if c_type == "auto":
        # Auto-detect from environment
        if (
            os.environ.get("GEMMA_ENDPOINT_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or (model and "gemma" in model.lower())
        ):
            return ModelGardenGemmaClient(default_model=model or ModelGardenGemmaClient.DEFAULT_GEMMA_MODEL, **kwargs)
        if (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("VERTEX_API_KEY")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GCP_ACCESS_TOKEN")
        ):
            return VertexGeminiClient(default_model=model or VertexGeminiClient.DEFAULT_JUDGE_MODEL, **kwargs)
        # Default offline fallback
        return MockClient(default_model=model or "mock-seer-model", **kwargs)

    raise ValueError(
        f"Unknown client_type: '{client_type}'. Must be one of 'auto', 'vertex', 'gemini', 'gemma', 'openai', 'mock'."
    )


# Aliases
get_client = create_client
ModelClient = BaseLLMClient
GeminiClient = VertexGeminiClient
GemmaClient = ModelGardenGemmaClient
