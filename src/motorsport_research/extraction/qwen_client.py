"""Local Ollama JSON-schema chat with model pinning and bounded response streams."""

import re
import time
from dataclasses import dataclass

import httpx

from motorsport_research.championships.json_data import decode
from motorsport_research.extraction.qwen_models import SYSTEM_PROMPT, ChunkExtraction

MAX_RESPONSE_BYTES = 256 * 1024


class InferenceError(ValueError):
    def __init__(self, outcome, detail, *, raw=b"", metrics=None):
        self.outcome = outcome
        self.raw = raw
        self.metrics = metrics or {}
        super().__init__(detail)


@dataclass(frozen=True)
class ChatResult:
    parsed: ChunkExtraction
    raw: bytes
    metrics: dict
    elapsed_seconds: float


class QwenClient:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.transport = transport
        self.base_url = str(settings.ollama_base_url).rstrip("/")

    def _request(self, method, path, *, payload=None, limit=MAX_RESPONSE_BYTES, timeout=None):
        timeout = timeout or self.settings.qwen_timeout_seconds
        started = time.monotonic()
        raw = bytearray()
        with httpx.Client(
            timeout=timeout, trust_env=False, follow_redirects=False, transport=self.transport
        ) as client:
            try:
                with client.stream(
                    method,
                    self.base_url + path,
                    json=payload,
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    if response.status_code != 200:
                        outcome = (
                            "unavailable"
                            if response.status_code in {404, 408, 429, 500, 502, 503, 504}
                            else "invalid_response"
                        )
                        raise InferenceError(
                            outcome, f"Ollama {path} returned HTTP {response.status_code}"
                        )
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise InferenceError(
                            "invalid_response", "Compressed Ollama response refused"
                        )
                    for chunk in response.iter_raw():
                        if time.monotonic() - started > timeout:
                            raise InferenceError(
                                "timeout", "Ollama response exceeded elapsed limit"
                            )
                        if len(raw) + len(chunk) > limit:
                            raise InferenceError(
                                "invalid_response",
                                "Ollama response exceeds byte limit",
                                raw=bytes(raw),
                            )
                        raw.extend(chunk)
            except httpx.TimeoutException as error:
                raise InferenceError("timeout", "Ollama timed out; work remains pending") from error
            except httpx.RequestError as error:
                raise InferenceError(
                    "unavailable", "Cannot reach Ollama; work remains pending"
                ) from error
        return bytes(raw), time.monotonic() - started

    def model_digest(self):
        raw, _ = self._request(
            "GET", "/api/tags", limit=1024 * 1024, timeout=self.settings.ollama_timeout_seconds
        )
        try:
            payload = decode(raw)
            models = payload["models"]
            if not isinstance(models, list):
                raise ValueError("invalid models")
            matches = [
                model
                for model in models
                if isinstance(model, dict)
                and (model.get("name") or model.get("model")) == self.settings.ollama_model
            ]
            if not matches:
                raise InferenceError(
                    "model_missing", "Configured model is absent; nothing was pulled"
                )
            if len(matches) != 1 or not re.fullmatch(
                r"(?:sha256:)?[a-f0-9]{64}", matches[0].get("digest", "")
            ):
                raise ValueError("invalid model digest")
            return matches[0]["digest"]
        except (ValueError, KeyError, TypeError, RecursionError) as error:
            if isinstance(error, InferenceError):
                raise
            raise InferenceError(
                "invalid_response", "Model listing lacks unambiguous version provenance", raw=raw
            ) from error

    def chat(self, payload):
        from pydantic import ValidationError

        if (
            not isinstance(payload, str)
            or len(payload.encode()) > self.settings.qwen_max_input_bytes
        ):
            raise InferenceError(
                "invalid_evidence", "Chat input exceeds its configured byte budget"
            )

        raw, elapsed = self._request(
            "POST",
            "/api/chat",
            payload={
                "model": self.settings.ollama_model,
                "stream": False,
                "think": False,
                "format": ChunkExtraction.model_json_schema(),
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": payload},
                ],
                "options": {
                    "temperature": 0,
                    "seed": 0,
                    "num_ctx": 8192,
                    "num_predict": self.settings.qwen_max_output_tokens,
                },
            },
        )
        metrics = {}
        try:
            response = decode(raw)
            if (
                response.get("model") != self.settings.ollama_model
                or response.get("done") is not True
            ):
                raise ValueError("model/completion mismatch")
            if response.get("done_reason") != "stop":
                raise ValueError("missing or truncated completion")
            message = response["message"]
            if message["role"] != "assistant" or message.get("tool_calls"):
                raise ValueError("not a plain assistant completion")
            for key in (
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "prompt_eval_duration",
                "eval_count",
                "eval_duration",
            ):
                value = response.get(key)
                if value is not None:
                    if type(value) is not int or value < 0:
                        raise ValueError("invalid timing/token metric")
                    metrics[key] = value
            parsed = ChunkExtraction.model_validate(decode(message["content"]))
            return ChatResult(parsed, raw, metrics, elapsed)
        except (
            ValueError,
            ValidationError,
            KeyError,
            TypeError,
            AttributeError,
            RecursionError,
        ) as error:
            raise InferenceError(
                "invalid_response",
                "Ollama completion failed strict schema validation",
                raw=raw,
                metrics=metrics,
            ) from error
