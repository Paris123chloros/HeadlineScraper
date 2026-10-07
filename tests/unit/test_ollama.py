import httpx
import pytest

from motorsport_research.config import Settings
from motorsport_research.extraction.ollama import MAX_TAG_RESPONSE_BYTES, check_ollama


@pytest.mark.parametrize(
    ("payload", "status", "available"),
    [
        ({"models": [{"name": "qwen3.5-instruct:4b"}]}, "ready", True),
        ({"models": [{"model": "qwen3.5-instruct:4b"}]}, "ready", True),
        ({"models": [{"name": "other:4b"}]}, "model_missing", False),
        ({"models": []}, "model_missing", False),
        ({"models": "not-a-list"}, "invalid_response", None),
        ({"models": [{}]}, "invalid_response", None),
        ({"models": [1]}, "invalid_response", None),
        ({}, "invalid_response", None),
        ([], "invalid_response", None),
    ],
)
def test_model_listing_validation(payload, status, available):
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json=payload)

    result = check_ollama(Settings(), transport=httpx.MockTransport(handler))
    assert result.status == status
    assert result.reachable is True
    assert result.model_available is available
    assert requests == [("GET", "/api/tags")]


@pytest.mark.parametrize("status_code", [301, 401, 404, 500])
def test_http_errors_are_not_model_absence(status_code):
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code))
    result = check_ollama(Settings(), transport=transport)
    assert result.status == "unavailable"
    assert result.reachable is True
    assert result.model_available is None


@pytest.mark.parametrize("body", [b"invalid-json", b"x" * (MAX_TAG_RESPONSE_BYTES + 1)])
def test_invalid_or_oversized_response(body):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    assert check_ollama(Settings(), transport=transport).status == "invalid_response"


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_connectivity_and_timeout_failure(error_type):
    def handler(request):
        raise error_type("fixture failure", request=request)

    result = check_ollama(Settings(), transport=httpx.MockTransport(handler))
    assert result.status == "unavailable"
    assert result.reachable is False
    assert result.model_available is None
