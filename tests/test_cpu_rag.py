import json
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
import yaml

import src.rag.embeddings as embeddings
from scripts.evaluate_rag import build_run_metadata
from src.data_artifacts import atomic_write_json
from src.data_paths import DataPaths
from src.rag.errors import RagError
from src.rag.index import _manifest_with_hash, build_rag_index, load_and_validate_index
from src.rag.service import RagService
from src.rag.settings import RagSettings


@pytest.fixture
def cpu_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_PROVIDER", "fastembed")
    monkeypatch.setenv("BUSHFIRE_RAG_ENABLED", "true")
    monkeypatch.delenv("BUSHFIRE_RAG_EMBED_MODEL", raising=False)
    monkeypatch.delenv("BUSHFIRE_RAG_SEMANTIC_SCORE_THRESHOLD", raising=False)
    monkeypatch.setattr(embeddings, "version", lambda name: "test-runtime-1")
    settings = RagSettings.from_env(DataPaths.from_env(tmp_path))
    settings.raw_dir.mkdir(parents=True)
    text = (
        "Queensland household bushfire preparedness requires a written plan. Decide what to take and discuss pets. " * 8
    )
    (settings.raw_dir / "guide.md").write_text(text, encoding="utf-8")
    source = {
        "source_id": "qld_fixture",
        "title": "Queensland preparedness fixture",
        "agency": "Test agency",
        "url": "https://example.gov.au/preparedness",
        "format": "markdown",
        "local_path": "raw/guide.md",
        "jurisdictions": ["Queensland"],
        "audiences": ["community"],
        "scenarios": ["preparedness"],
        "document_date": "2026-01-01",
        "licence": "Test fixture",
        "licence_url": "https://example.gov.au/copyright",
        "reuse_status": "test_only",
        "last_verified_date": "2026-01-01",
    }
    settings.sources_path.write_text(yaml.safe_dump({"schema_version": 1, "sources": [source]}), encoding="utf-8")
    directory = embeddings._model_directory(settings)
    directory.mkdir(parents=True)
    for name in embeddings._MODEL_FILES:
        (directory / name).write_bytes(f"fixture {name}".encode())
    atomic_write_json(directory / "identity.json", embeddings._model_identity(directory))
    return settings


@pytest.fixture
def fake_model(monkeypatch):
    calls = []

    class Model:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def embed(self, values, **kwargs):
            assert kwargs["parallel"] is None
            for _value in values:
                yield SimpleNamespace(tolist=lambda: [1.0] + [0.0] * 383)

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=Model))
    return calls


def test_cpu_default_is_offline_and_ollama_is_still_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_RAG_EMBED_PROVIDER", raising=False)
    # Windows launcher preflight may have populated the local Ollama model setting.
    monkeypatch.delenv("BUSHFIRE_RAG_EMBED_MODEL", raising=False)
    monkeypatch.delenv("BUSHFIRE_RAG_SEMANTIC_SCORE_THRESHOLD", raising=False)
    assert RagSettings.from_env(DataPaths.from_env(tmp_path)).embedding_provider == "ollama"
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_PROVIDER", "fastembed")
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_BASE_URL", "https://unused.example")
    settings = RagSettings.from_env(DataPaths.from_env(tmp_path))
    assert settings.embedding_model == embeddings.FASTEMBED_MODEL
    assert settings.embedding_local_files_only is True
    assert settings.semantic_score_threshold == 0.70


@pytest.mark.parametrize(
    "name,value",
    [
        ("BUSHFIRE_RAG_EMBED_PROVIDER", "remote"),
        ("BUSHFIRE_RAG_EMBED_MODEL", "unreviewed/model"),
        ("BUSHFIRE_RAG_EMBED_THREADS", "0"),
        ("BUSHFIRE_RAG_EMBED_LOCAL_FILES_ONLY", "invalid"),
    ],
)
def test_cpu_invalid_configuration_fails_closed(tmp_path, monkeypatch, name, value):
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_PROVIDER", "fastembed")
    monkeypatch.setenv(name, value)
    with pytest.raises(RagError):
        RagSettings.from_env(DataPaths.from_env(tmp_path))


def test_cpu_model_is_reused_offline_and_forced_to_cpu(cpu_settings, fake_model):
    first = embeddings.create_embedding_client(cpu_settings)
    second = embeddings.create_embedding_client(cpu_settings)
    assert first is second
    assert len(first.embed(["planning"])[0]) == 384
    second.embed(["another plan"])
    assert len(fake_model) == 1
    assert fake_model[0]["local_files_only"] is True
    assert fake_model[0]["providers"] == ["CPUExecutionProvider"]
    assert fake_model[0]["threads"] == 2


def test_cpu_missing_model_never_attempts_inference(cpu_settings, fake_model):
    (embeddings._model_directory(cpu_settings) / "identity.json").unlink()
    with pytest.raises(RagError, match="cache is missing"):
        embeddings.create_embedding_client(cpu_settings).embed(["planning"])
    assert not fake_model


def test_cpu_model_tampering_fails_before_reusing_cached_inference(cpu_settings, fake_model):
    client = embeddings.create_embedding_client(cpu_settings)
    client.embed(["planning"])
    (client.directory / "tokenizer.json").write_bytes(b"different tokenizer")
    with pytest.raises(RagError, match="changed after preparation"):
        client.embed(["planning"])


def test_cpu_build_and_query_bind_model_files_and_dimension(cpu_settings, fake_model):
    manifest = build_rag_index(cpu_settings)
    assert manifest["schema"] == "bushfire-rag-index-v3"
    assert manifest["embedding_provider"] == "fastembed"
    assert len(manifest["embedding_identity"]["files"]) == 6
    assert manifest["embedding_dimension"] == 384
    assert load_and_validate_index(cpu_settings) == manifest
    result = RagService(cpu_settings).retrieve(
        "Queensland household bushfire preparedness written plan", jurisdiction="Queensland"
    )
    assert result["status"] == "ready"
    assert result["embedding_provider"] == "fastembed"
    assert len(fake_model) == 1
    with pytest.raises(RagError, match="different embedding provider"):
        load_and_validate_index(replace(cpu_settings, embedding_provider="ollama"))


def test_cpu_index_rejects_other_model_files_even_with_valid_manifest_hash(cpu_settings, fake_model):
    manifest = build_rag_index(cpu_settings)
    manifest["embedding_identity"]["digest"] = "f" * 64
    manifest.pop("manifest_sha256")
    atomic_write_json(cpu_settings.index_dir / "manifest.json", _manifest_with_hash(manifest))
    result = RagService(cpu_settings).retrieve("Queensland household preparedness")
    assert result["status"] == "invalid"
    assert not result["retrieved_chunks"]


def test_cpu_query_dimension_mismatch_is_reported_without_qdrant_query(cpu_settings, fake_model):
    build_rag_index(cpu_settings)
    bad_embedder = SimpleNamespace(
        embed=lambda _texts: [[1.0, 0.0]], identity=embeddings.create_embedding_client(cpu_settings).identity
    )
    result = RagService(cpu_settings, embedder=bad_embedder).retrieve("Queensland household preparedness")
    assert result["status"] == "unavailable"
    assert result["error_code"] == "rag_embedding_invalid"


def test_cpu_evaluation_records_local_files_without_calling_ollama(cpu_settings, fake_model, tmp_path, monkeypatch):
    import scripts.evaluate_rag as evaluation

    build_rag_index(cpu_settings)
    monkeypatch.setattr(evaluation, "ollama_model_identity", lambda *_args, **_kw: pytest.fail("Ollama was called"))
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    metadata = build_run_metadata({"schema_version": 1}, questions, RagService(cpu_settings))
    assert metadata["embedding_model"]["provider"] == "fastembed"
    assert metadata["embedding_model"]["digest"] == metadata["rag_index"]["embedding_identity"]["digest"]


def test_only_explicit_preparation_downloads_pinned_public_model(cpu_settings, monkeypatch):
    downloads = []
    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=lambda **kw: downloads.append(kw))
    )
    identity = embeddings.prepare_embedding_model(replace(cpu_settings, embedding_local_files_only=False))
    assert len(downloads) == 6
    assert all(item["revision"] == embeddings.FASTEMBED_REVISION and item["token"] is False for item in downloads)
    assert all(item["local_files_only"] is False for item in downloads)
    assert identity == embeddings.create_embedding_client(cpu_settings).identity()
