"""Configured model destinations must not forward payloads through redirects."""

import json
import runpy
from pathlib import Path

import dotenv
import httpx
import openai
import pytest
import requests

from src.rag.embeddings import OllamaEmbeddingClient
from src.rag.errors import RagError


@pytest.fixture
def model_config(monkeypatch):
    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
    for provider, endpoint in (
        ("OLLAMA", "http://127.0.0.1:11434/v1"),
        ("OPENAI", "https://models.example.test/v1"),
        ("OPENROUTER", "https://models.example.test/v1"),
        ("DEEPSEEK", "https://models.example.test/v1"),
    ):
        monkeypatch.setenv(f"{provider}_BASE_URL", endpoint)
        monkeypatch.setenv(f"{provider}_API_KEY", "synthetic-test-key")
        monkeypatch.setenv(f"{provider}_MODEL", "synthetic-model")
    monkeypatch.setenv("BUSHFIRE_MODEL_MAX_RETRIES", "0")

    def load(provider):
        monkeypatch.setenv("LLM_PROVIDER", provider)
        return runpy.run_path(str(Path(__file__).resolve().parents[1] / "src/config.py"))

    return load


def _completion(request):
    return httpx.Response(
        200,
        request=request,
        json={
            "id": "synthetic-completion",
            "created": 0,
            "model": "synthetic-model",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Draft."}, "finish_reason": "stop"}],
        },
    )


@pytest.mark.parametrize("provider", ["ollama", "openai", "openrouter", "deepseek"])
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_report_client_never_follows_redirects(monkeypatch, model_config, provider, status):
    seen = []

    def transport(_transport, request):
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(status, headers={"location": "https://outside.example.test/collect"}, request=request)
        return _completion(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    config = model_config(provider)
    try:
        with pytest.raises(openai.APIStatusError):
            config["client"].chat.completions.create(
                model="synthetic-model", messages=[{"role": "user", "content": "Synthetic private planning input."}]
            )
    finally:
        config["client"].close()
    assert len(seen) == 1
    assert "outside.example.test" not in seen[0]


@pytest.mark.parametrize("provider", ["ollama", "openai", "openrouter", "deepseek"])
def test_report_client_keeps_normal_configured_requests(monkeypatch, model_config, provider):
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _transport, request: _completion(request))
    config = model_config(provider)
    try:
        response = config["client"].chat.completions.create(
            model="synthetic-model", messages=[{"role": "user", "content": "Synthetic input."}]
        )
        assert response.choices[0].message.content == "Draft."
    finally:
        config["client"].close()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_embedding_client_never_follows_redirects(monkeypatch, status):
    seen = []

    def transport(_adapter, request, **_kwargs):
        seen.append(request.url)
        response = requests.Response()
        response.request, response.url = request, request.url
        response.status_code = status if len(seen) == 1 else 200
        response.headers["Location"] = "https://outside.example.test/collect"
        response._content = json.dumps({"embeddings": [[1.0, 0.0]]}).encode()
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", transport)
    with pytest.raises(RagError, match="redirect"):
        OllamaEmbeddingClient("http://127.0.0.1:11434", "synthetic-model").embed(["Synthetic private query."])
    assert seen == ["http://127.0.0.1:11434/api/embed"]
