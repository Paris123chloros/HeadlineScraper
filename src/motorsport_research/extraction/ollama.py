"""Read-only Ollama model diagnostics; never download or run a model here."""

import json

import httpx
from pydantic import BaseModel

from motorsport_research.config import Settings

MAX_TAG_RESPONSE_BYTES = 1024 * 1024


class OllamaStatus(BaseModel):
    status: str
    reachable: bool
    model_available: bool | None
    model: str
    detail: str


def check_ollama(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> OllamaStatus:
    def result(status: str, reachable: bool, available: bool | None, detail: str) -> OllamaStatus:
        return OllamaStatus(
            status=status,
            reachable=reachable,
            model_available=available,
            model=settings.ollama_model,
            detail=detail,
        )

    url = f"{str(settings.ollama_base_url).rstrip('/')}/api/tags"
    # Container-to-container and localhost requests should not use a host HTTP proxy.
    with httpx.Client(
        timeout=settings.ollama_timeout_seconds,
        trust_env=False,
        follow_redirects=False,
        transport=transport,
    ) as client:
        try:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return result(
                        "unavailable",
                        True,
                        None,
                        f"Ollama /api/tags returned HTTP {response.status_code}; "
                        "check the endpoint.",
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_TAG_RESPONSE_BYTES:
                        return result("invalid_response", True, None, "Model listing is too large.")
        except httpx.RequestError:
            return result(
                "unavailable",
                False,
                None,
                "Cannot reach Ollama; check OLLAMA_BASE_URL, its Docker network, and timeout.",
            )

    try:
        payload = json.loads(body)
        models = payload["models"]
        if not isinstance(models, list):
            raise ValueError("models must be a list")
        names = []
        for model in models:
            name = model.get("name") or model.get("model")
            if not isinstance(name, str) or not name:
                raise ValueError("model tag is missing")
            names.append(name)
    except (ValueError, KeyError, TypeError, AttributeError):
        return result("invalid_response", True, None, "Ollama returned an invalid model listing.")

    if settings.ollama_model not in names:
        return result(
            "model_missing",
            True,
            False,
            "Configured model is absent; set OLLAMA_MODEL to an installed tag. Nothing was pulled.",
        )
    return result(
        "ready", True, True, "Configured model is installed; inference was not exercised."
    )
