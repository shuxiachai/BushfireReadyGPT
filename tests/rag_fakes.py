"""Explicit synthetic embedding identities; never used by application code."""

from types import SimpleNamespace


def ollama_identity(model="keyword-test-model", digest="a" * 64):
    return {
        "provider": "ollama",
        "model": model,
        "resolved_model": model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest",
        "digest": digest,
        "encoding": "ollama-api-embed-v1",
    }


def identity_client(settings):
    return SimpleNamespace(identity=lambda: ollama_identity(settings.embedding_model))
