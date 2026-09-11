"""Synthetic-only regressions for digest-bound Ollama indexes and v2 migration."""

import copy
import json
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
import requests

from scripts import build_rag_index as build_cli
from scripts import evaluation_artifacts as artifacts
from src.rag import embeddings, index
from src.rag.errors import RagError
from src.rag.service import RagService, inspect_rag_index
from tests.rag_fakes import identity_client, ollama_identity
from tests.test_rag_pipeline import KeywordEmbedder, _write_test_corpus


class MutableEmbedder(KeywordEmbedder):
    digest = "a" * 64

    def identity(self):
        return ollama_identity(self.model, self.digest)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(index, "create_embedding_client", identity_client)
    return _write_test_corpus(tmp_path)


def _response(payload, status=200):
    def raise_for_status():
        if status >= 400:
            raise requests.HTTPError("Synthetic error")

    return SimpleNamespace(status_code=status, json=lambda: payload, raise_for_status=raise_for_status)


def _tags(digest="a" * 64, model="embeddinggemma:latest"):
    return {"models": [{"name": model, "model": model, "digest": digest}]}


@pytest.mark.parametrize("model", ["embeddinggemma", "embeddinggemma:latest", "localhost:5000/example/model"])
def test_actual_tag_digest_and_canonical_model_are_observed_without_caching(monkeypatch, model):
    observed = []
    identity = ollama_identity(model)
    digests = iter(("a" * 64, "sha256:" + "B" * 64))

    def get(url, **kwargs):
        observed.append((url, kwargs))
        return _response(_tags(next(digests), identity["resolved_model"]))

    monkeypatch.setattr(embeddings.requests, "get", get)
    client = embeddings.OllamaEmbeddingClient("http://127.0.0.1:11434", model, timeout_seconds=7)
    assert client.identity() == identity
    assert client.identity() == {**identity, "digest": "b" * 64}
    assert observed == [("http://127.0.0.1:11434/api/tags", {"timeout": (5, 7), "allow_redirects": False})] * 2


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"models": None},
        _tags("not-a-digest"),
        _tags(None),
        {"models": []},
        {"models": [*_tags()["models"], *_tags("b" * 64)["models"]]},
    ],
)
def test_missing_malformed_and_ambiguous_model_identities_fail_closed(monkeypatch, payload):
    monkeypatch.setattr(embeddings.requests, "get", lambda *_a, **_kw: _response(payload))
    with pytest.raises(RagError):
        embeddings.OllamaEmbeddingClient("http://127.0.0.1:11434", "embeddinggemma").identity()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_identity_endpoint_cannot_redirect_or_send_embedding_text(monkeypatch, status):
    requests_seen = []

    def get(url, **kwargs):
        requests_seen.append((url, kwargs))
        return _response({}, status=status)

    monkeypatch.setattr(embeddings.requests, "get", get)
    monkeypatch.setattr(embeddings.requests, "post", lambda *_a, **_kw: pytest.fail("Embedding text was sent"))
    with pytest.raises(RagError, match="redirect"):
        embeddings.OllamaEmbeddingClient("http://127.0.0.1:11434", "embeddinggemma").embed(["Private test text"])
    assert len(requests_seen) == 1
    assert requests_seen[0][1]["allow_redirects"] is False
    assert "json" not in requests_seen[0][1]


@pytest.mark.parametrize("digests", [("a", "b"), ("a", "a", "b")])
def test_embedding_rejects_model_change_during_or_between_batches(monkeypatch, digests):
    observations = iter(digests)
    posts = []
    monkeypatch.setattr(embeddings.requests, "get", lambda *_a, **_kw: _response(_tags(next(observations) * 64)))

    def post(*_args, **kwargs):
        posts.append(kwargs["json"])
        return _response({"model": "embeddinggemma", "embeddings": [[1.0, 0.0]]})

    monkeypatch.setattr(embeddings.requests, "post", post)
    with pytest.raises(RagError) as captured:
        embeddings.OllamaEmbeddingClient("http://127.0.0.1:11434", "embeddinggemma", batch_size=1).embed(["one", "two"])
    assert captured.value.code == "rag_embedding_changed"
    assert len(posts) == 1


def test_embedding_checks_response_model_name(monkeypatch):
    monkeypatch.setattr(embeddings.requests, "get", lambda *_a, **_kw: _response(_tags()))
    monkeypatch.setattr(
        embeddings.requests, "post", lambda *_a, **_kw: _response({"model": "another-model", "embeddings": [[1.0]]})
    )
    with pytest.raises(RagError, match="unexpected model"):
        embeddings.OllamaEmbeddingClient("http://127.0.0.1:11434", "embeddinggemma").embed(["one"])


def test_embed_start_observation_is_bound_to_callers_index_not_an_independent_baseline(monkeypatch):
    observations = iter(("b" * 64, "a" * 64))
    monkeypatch.setattr(embeddings.requests, "get", lambda *_a, **_kw: _response(_tags(next(observations))))
    monkeypatch.setattr(embeddings.requests, "post", lambda *_a, **_kw: pytest.fail("Wrong-model vectors requested"))
    client = embeddings.OllamaEmbeddingClient("http://127.0.0.1:11434", "embeddinggemma")
    settings = SimpleNamespace(embedding_provider="ollama", embedding_model="embeddinggemma")
    with pytest.raises(RagError, match="bound index identity"):
        embeddings.embed_with_identity(settings, client, ["one"], ollama_identity("embeddinggemma"))
    # Restoration after the observed mismatch cannot make the rejected call successful.
    assert client.identity()["digest"] == "a" * 64


def test_new_index_binds_actual_model_digest_model_name_and_dimension(settings):
    embedder = MutableEmbedder()
    manifest = index.build_rag_index(settings, embedder)
    assert manifest["schema"] == index.RAG_OLLAMA_INDEX_SCHEMA
    assert manifest["embedding_identity"] == {**embedder.identity(), "dimension": 3}
    assert manifest["embedding_dimension"] == 3
    assert index.load_and_validate_index(settings, embedder) == manifest
    result = RagService(settings, embedder=embedder).retrieve("Queensland household written preparedness plan")
    assert result["status"] == "ready"


def test_same_name_and_dimension_but_new_weights_are_rejected_before_query(settings, monkeypatch):
    embedder = MutableEmbedder()
    index.build_rag_index(settings, embedder)
    embedder.digest = "b" * 64
    embedder.calls = 0
    service = RagService(settings, embedder=embedder)
    monkeypatch.setattr(service, "_query_index", lambda *_a, **_kw: pytest.fail("Qdrant must not be queried"))
    result = service.retrieve("Queensland household preparedness")
    assert result["error_code"] == "rag_index_stale"
    assert result["retrieved_chunks"] == []
    assert embedder.calls == 0


def test_changed_digest_during_query_never_returns_chunks(settings):
    index.build_rag_index(settings, MutableEmbedder())

    class DriftingQuery(MutableEmbedder):
        def embed(self, texts, *, expected_identity=None):
            vectors = super().embed(texts)
            self.digest = "b" * 64
            return vectors

    result = RagService(settings, embedder=DriftingQuery()).retrieve("Queensland household preparedness")
    assert result["error_code"] == "rag_index_stale"
    assert result["retrieved_chunks"] == []


def test_changed_digest_during_build_is_not_published(settings):
    class DriftingBuild(MutableEmbedder):
        def embed(self, texts, *, expected_identity=None):
            vectors = super().embed(texts)
            self.digest = "b" * 64
            return vectors

    with pytest.raises(RagError, match="changed while building"):
        index.build_rag_index(settings, DriftingBuild())
    assert not settings.index_dir.exists()
    assert not list(settings.rag_dir.glob(".index.*.stage"))


def test_changed_digest_during_publication_rolls_back_previous_index(settings, monkeypatch):
    embedder = MutableEmbedder()
    before = index.build_rag_index(settings, embedder)
    previous_bytes = (settings.index_dir / "manifest.json").read_bytes()
    original = index._publish_index

    def publish(staging, target, **kwargs):
        embedder.digest = "b" * 64
        return original(staging, target, **kwargs)

    monkeypatch.setattr(index, "_publish_index", publish)
    with pytest.raises(RagError, match="digest changed"):
        index.build_rag_index(settings, embedder)
    assert (settings.index_dir / "manifest.json").read_bytes() == previous_bytes
    assert index.load_and_validate_index(settings, MutableEmbedder()) == before


def _legacy_index(settings):
    manifest = index.build_rag_index(settings, MutableEmbedder())
    manifest["schema"] = index.RAG_INDEX_SCHEMA
    for key in ("embedding_provider", "embedding_identity", "manifest_sha256"):
        manifest.pop(key)
    manifest = index._manifest_with_hash(manifest)
    (settings.index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_legacy_index_is_read_only_history_not_retroactive_model_evidence(settings, monkeypatch):
    expected = _legacy_index(settings)
    original = (settings.index_dir / "manifest.json").read_bytes()
    monkeypatch.setattr(index, "create_embedding_client", lambda *_a: pytest.fail("Historical evidence needs no model"))
    assert index.load_and_validate_index(settings, historical=True) == expected
    assert "embedding_identity" not in expected
    with pytest.raises(RagError) as captured:
        index.load_and_validate_index(settings)
    assert captured.value.code == "rag_index_migration_required"
    status = inspect_rag_index(settings)
    assert status["error_code"] == "rag_index_migration_required"
    assert "--new-index-dir index-v4" in status["build_command"]
    assert "--download" not in status["build_command"]
    assert "--refresh" not in status["build_command"]
    assert "BUSHFIRE_RAG_INDEX_DIR" in status["error"]
    result = RagService(settings, embedder=MutableEmbedder()).retrieve("Queensland household preparedness")
    assert result["error_code"] == "rag_index_migration_required"
    assert result["retrieved_chunks"] == []
    with pytest.raises(RagError) as captured:
        index.build_rag_index(settings)
    assert captured.value.code == "rag_index_migration_required"
    assert (settings.index_dir / "manifest.json").read_bytes() == original
    assert not list(settings.rag_dir.glob(".index.*.stage"))


def test_legacy_index_cannot_be_upgraded_by_adding_todays_digest(settings):
    manifest = _legacy_index(settings)
    manifest["embedding_identity"] = {**MutableEmbedder().identity(), "dimension": 3}
    manifest.pop("manifest_sha256")
    (settings.index_dir / "manifest.json").write_text(json.dumps(index._manifest_with_hash(manifest)), encoding="utf-8")
    with pytest.raises(RagError, match="retrospective"):
        index.load_and_validate_index(settings, historical=True)


def test_missing_identity_contract_cannot_silently_create_unbound_vectors(settings):
    embedder = SimpleNamespace(embed=lambda _texts: pytest.fail("Unbound embedding must not run"))
    with pytest.raises(RagError, match="verifiable model identity"):
        index.build_rag_index(settings, embedder)
    assert not settings.index_dir.exists()


def test_cli_explicit_new_directory_migrates_without_overwriting_or_switching(settings, monkeypatch, capsys):
    _legacy_index(settings)
    previous = (settings.index_dir / "manifest.json").read_bytes()
    monkeypatch.setattr(build_cli.RagSettings, "from_env", lambda: settings)
    monkeypatch.setattr(build_cli, "create_embedding_client", lambda _settings: MutableEmbedder())
    monkeypatch.setattr(build_cli, "download_catalog_sources", lambda *_a, **_kw: pytest.fail("Unexpected download"))
    monkeypatch.setattr(sys, "argv", ["build_rag_index.py", "--new-index-dir", "index-v4"])
    assert build_cli.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["runtime_switch_required"] is True
    assert output["runtime_index_setting"] == "BUSHFIRE_RAG_INDEX_DIR"
    assert settings.index_dir.name == "index"
    assert (settings.index_dir / "manifest.json").read_bytes() == previous
    assert (
        index.load_and_validate_index(replace(settings, index_dir=settings.rag_dir / "index-v4"))["schema"]
        == index.RAG_OLLAMA_INDEX_SCHEMA
    )


@pytest.mark.parametrize("option", ["--download", "--refresh", "--prepare-embedding-model"])
def test_legacy_cli_refusal_precedes_any_download_or_model_preparation(settings, monkeypatch, option):
    _legacy_index(settings)
    original = (settings.index_dir / "manifest.json").read_bytes()
    monkeypatch.setattr(build_cli.RagSettings, "from_env", lambda: settings)
    monkeypatch.setattr(build_cli, "download_catalog_sources", lambda *_a, **_kw: pytest.fail("Corpus download"))
    monkeypatch.setattr(build_cli, "prepare_embedding_model", lambda *_a, **_kw: pytest.fail("Model download"))
    monkeypatch.setattr(build_cli, "create_embedding_client", lambda *_a, **_kw: pytest.fail("Model observation"))
    monkeypatch.setattr(sys, "argv", ["build_rag_index.py", option])
    assert build_cli.main() == 1
    assert (settings.index_dir / "manifest.json").read_bytes() == original


def test_new_target_is_rechecked_under_builder_lock(settings):
    settings.index_dir.mkdir()
    marker = settings.index_dir / "keep.txt"
    marker.write_text("Existing directory must not be overwritten", encoding="utf-8")
    with pytest.raises(RagError, match="already exists"):
        index.build_rag_index(settings, MutableEmbedder(), require_new=True)
    assert marker.read_text(encoding="utf-8") == "Existing directory must not be overwritten"


@pytest.mark.parametrize("target", ["index", "../outside", "raw/index-v4"])
def test_cli_new_target_must_be_a_nonexisting_sibling(settings, monkeypatch, target):
    settings.index_dir.mkdir()
    monkeypatch.setattr(build_cli.RagSettings, "from_env", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["build_rag_index.py", "--new-index-dir", target])
    assert build_cli.main() == 1


def test_new_evaluation_provenance_binds_digest_and_rejects_different_run_weights(settings):
    index.build_rag_index(settings, MutableEmbedder())
    provenance = artifacts.rag_index_provenance(settings)
    artifacts._validate_index_provenance(provenance)
    assert provenance["embedding_identity"]["digest"] == "a" * 64
    run = {
        "git": {"collection_status": "collected", "commit": "a" * 40, "working_tree_dirty": False},
        "rag_index": provenance,
        "embedding_model": {"name": settings.embedding_model, "digest": "a" * 64, "digest_status": "resolved"},
    }
    artifacts._validate_release_provenance(run, "embedding_model")
    changed = copy.deepcopy(run)
    changed["embedding_model"]["digest"] = "b" * 64
    with pytest.raises(artifacts.ArtifactValidationError, match="build-time index identities differ"):
        artifacts._validate_release_provenance(changed, "embedding_model")
    changed = copy.deepcopy(provenance)
    changed["embedding_identity"]["dimension"] = 2
    with pytest.raises(artifacts.ArtifactValidationError, match="dimension differs"):
        artifacts._validate_index_provenance(changed)


def test_historical_v2_evaluation_provenance_remains_verifiable_without_fabrication():
    legacy = {"status": "verified", "schema": "bushfire-rag-index-v2"}
    for key in ("manifest_sha256", "catalog_sha256", "corpus_sha256", "documents_sha256"):
        legacy[key] = "a" * 64
    artifacts._validate_index_provenance(legacy)
    assert "embedding_identity" not in legacy
