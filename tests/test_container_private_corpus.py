import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from src import container_runtime as runtime
from src.corpus_bundle import create_test_corpus_bundle


@pytest.fixture(autouse=True)
def isolated_container(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith(("BUSHFIRE_", "RAILWAY_")) or name == "PORT":
            monkeypatch.delenv(name)
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", str(tmp_path / "volume"))
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_PROVIDER", "fastembed")
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_CACHE_DIR", str(tmp_path / "image-models"))
    for name in ("BUSHFIRE_RAG_DIR", "BUSHFIRE_RAG_RAW_DIR", "BUSHFIRE_RAG_INDEX_DIR", "BUSHFIRE_RAG_SOURCES_PATH"):
        monkeypatch.setenv(name, "")


@pytest.fixture
def fake_cpu(monkeypatch):
    import httpx
    import requests

    import src.rag.embeddings as embeddings
    import src.rag.index as index
    import src.rag.service as service

    identity = {
        "provider": "fastembed",
        "model": "BAAI/bge-small-en-v1.5",
        "dimension": 2,
        "digest": "a" * 64,
    }
    calls = []

    def embed(texts):
        calls.append(list(texts))
        return [[1.0, 0.0] for _text in texts]

    client = SimpleNamespace(identity=lambda: copy.deepcopy(identity), embed=embed)
    for module in (embeddings, index, service):
        monkeypatch.setattr(module, "create_embedding_client", lambda _settings: client)
    monkeypatch.setattr(requests.Session, "request", lambda *_args, **_kwargs: pytest.fail("Startup must stay offline"))
    monkeypatch.setattr(httpx.Client, "send", lambda *_args, **_kwargs: pytest.fail("Startup must stay offline"))
    return SimpleNamespace(client=client, identity=identity, calls=calls)


def _bundle(tmp_path, *, fixture=False):
    bundle = tmp_path / "image-corpus"
    manifest = create_test_corpus_bundle(bundle)
    if not fixture:
        # This test has no real official text. Model a private, approved bundle's metadata explicitly.
        manifest.update(
            fixture_only=False,
            usage_intent="private_research_noncommercial",
            source_terms_acknowledged=True,
            source_index_manifest_sha256="b" * 64,
        )
        payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
        (bundle / "bundle-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return bundle, manifest


def test_first_start_builds_cpu_index_and_preserves_original_catalog_and_source_bytes(tmp_path, fake_cpu):
    bundle, manifest = _bundle(tmp_path)
    original_catalog = (bundle / "sources.yml").read_bytes()
    target = runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert target == tmp_path / "volume" / "private-rag" / manifest["manifest_sha256"]
    assert (target / "sources.yml").read_bytes() == original_catalog
    for row in manifest["files"]:
        assert (target / row["path"]).read_bytes() == (bundle / row["path"]).read_bytes()
    built = json.loads((target / "index" / "manifest.json").read_text())
    assert built["embedding_provider"] == "fastembed"
    assert built["embedding_identity"] == fake_cpu.identity
    assert list((target / "index" / "qdrant").rglob("storage.sqlite"))
    assert not list(target.parent.glob(".corpus-*"))


def test_restart_reuses_verified_version_without_rebuilding_or_image_bundle(tmp_path, fake_cpu, monkeypatch):
    import src.rag.index as index

    bundle, manifest = _bundle(tmp_path)
    target = runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    original_index = (target / "index" / "manifest.json").read_bytes()
    monkeypatch.setattr(index, "build_rag_index", lambda *_: pytest.fail("Existing index must not be rebuilt"))
    assert (
        runtime.install_private_rag_corpus(tmp_path / "image-no-longer-has-corpus", manifest["manifest_sha256"])
        == target
    )
    assert (target / "index" / "manifest.json").read_bytes() == original_index


@pytest.mark.parametrize("corrupted", ["raw/synthetic_qld_test.txt", "sources.yml", "index/manifest.json"])
def test_corrupt_existing_version_is_not_repaired_or_overwritten(tmp_path, fake_cpu, monkeypatch, corrupted):
    import src.rag.index as index

    bundle, manifest = _bundle(tmp_path)
    target = runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    damaged = target / corrupted
    damaged.write_bytes(b"operator state must not be overwritten")
    monkeypatch.setattr(index, "build_rag_index", lambda *_: pytest.fail("Existing index must not be rebuilt"))
    with pytest.raises(ValueError, match="failed integrity"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert damaged.read_bytes() == b"operator state must not be overwritten"


def test_existing_index_bound_to_different_cpu_model_fails_closed(tmp_path, fake_cpu):
    bundle, manifest = _bundle(tmp_path)
    target = runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    index_before = (target / "index" / "manifest.json").read_bytes()
    fake_cpu.identity["digest"] = "c" * 64
    with pytest.raises(ValueError, match="CPU-model validation"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert (target / "index" / "manifest.json").read_bytes() == index_before


@pytest.mark.parametrize("smoke", [None, "false", "yes", "1"])
def test_fixture_bundle_is_rejected_outside_explicit_smoke_mode(tmp_path, smoke, fake_cpu, monkeypatch):
    if smoke is not None:
        monkeypatch.setenv("BUSHFIRE_CONTAINER_SMOKE", smoke)
    bundle, manifest = _bundle(tmp_path, fixture=True)
    with pytest.raises(ValueError, match="Synthetic test-only"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert not (tmp_path / "volume").exists()


def test_fixture_bundle_requires_smoke_permission_again_on_restart(tmp_path, fake_cpu, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_CONTAINER_SMOKE", "true")
    bundle, manifest = _bundle(tmp_path, fixture=True)
    target = runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert target.is_dir()
    monkeypatch.delenv("BUSHFIRE_CONTAINER_SMOKE")
    with pytest.raises(ValueError, match="Synthetic test-only"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])


@pytest.mark.parametrize("identity", ["", "a" * 63, "A" * 64, "../outside", None])
def test_bad_expected_identity_cannot_fall_back_or_create_a_version(tmp_path, identity):
    with pytest.raises(ValueError, match="BUSHFIRE_RAG_CORPUS_SHA256"):
        runtime.install_private_rag_corpus(tmp_path / "missing", identity)
    assert not (tmp_path / "volume").exists()


def test_expected_hash_mismatch_is_rejected_before_persistent_mutation(tmp_path, fake_cpu):
    bundle, _manifest = _bundle(tmp_path)
    with pytest.raises(ValueError, match="does not match BUSHFIRE_RAG_CORPUS_SHA256"):
        runtime.install_private_rag_corpus(bundle, "e" * 64)
    assert not (tmp_path / "volume").exists()


def test_tampered_bundle_hash_fails_closed(tmp_path, fake_cpu):
    bundle, manifest = _bundle(tmp_path)
    (bundle / "sources.yml").write_bytes(b"tampered source terms")
    with pytest.raises(ValueError, match="failed integrity"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert not (tmp_path / "volume").exists()


@pytest.mark.parametrize(
    "override", [("BUSHFIRE_RAG_EMBED_PROVIDER", "ollama"), ("BUSHFIRE_RAG_EMBED_LOCAL_FILES_ONLY", "false")]
)
def test_private_index_build_cannot_download_models_or_use_network_embeddings(
    tmp_path, fake_cpu, monkeypatch, override
):
    bundle, manifest = _bundle(tmp_path)
    monkeypatch.setenv(*override)
    with pytest.raises(ValueError, match="offline-only"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert not fake_cpu.calls
    assert not (tmp_path / "volume").exists()


def test_failed_first_build_never_publishes_partial_index_or_raw_exception_path(tmp_path, fake_cpu, monkeypatch):
    import src.rag.index as index

    bundle, manifest = _bundle(tmp_path)

    def fail_build(_settings):
        raise OSError("Private filesystem error at /data/secret-owner/private-key")

    monkeypatch.setattr(index, "build_rag_index", fail_build)
    with pytest.raises(ValueError) as failure:
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert "/data" not in str(failure.value)
    parent = tmp_path / "volume" / "private-rag"
    assert not (parent / manifest["manifest_sha256"]).exists()
    assert not list(parent.glob(".corpus-*"))


def test_existing_target_file_is_preserved(tmp_path, fake_cpu):
    bundle, manifest = _bundle(tmp_path)
    target = tmp_path / "volume" / "private-rag" / manifest["manifest_sha256"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing data")
    with pytest.raises(ValueError, match="must be a directory"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert target.read_bytes() == b"existing data"


def test_target_appearing_during_build_is_not_overwritten(tmp_path, fake_cpu, monkeypatch):
    import src.rag.index as index

    bundle, manifest = _bundle(tmp_path)
    target = tmp_path / "volume" / "private-rag" / manifest["manifest_sha256"]
    original_build = index.build_rag_index

    def conflicting_build(settings):
        result = original_build(settings)
        target.mkdir()
        return result

    monkeypatch.setattr(index, "build_rag_index", conflicting_build)
    with pytest.raises(ValueError, match="appeared during initialization"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_atomic_publisher_never_overwrites_racing_empty_directory(tmp_path, monkeypatch):
    staged, target = tmp_path / "staged", tmp_path / "target"
    staged.mkdir()
    (staged / "payload").write_bytes(b"new index")
    target.mkdir()
    original_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: False if path == target else original_exists(path))
    with pytest.raises(OSError):
        runtime._publish_private_rag(staged, target)
    assert target.is_dir() and list(target.iterdir()) == []
    assert (staged / "payload").read_bytes() == b"new index"


@pytest.mark.parametrize("location", ["bundle", "parent", "target"])
def test_symbolic_directory_links_are_rejected_before_copy(tmp_path, fake_cpu, monkeypatch, location):
    bundle, manifest = _bundle(tmp_path)
    parent = tmp_path / "volume" / "private-rag"
    linked = {"bundle": bundle, "parent": parent, "target": parent / manifest["manifest_sha256"]}[location]
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == linked or original(path))
    with pytest.raises(ValueError, match="symbolic links"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    assert not fake_cpu.calls


def test_prepare_runtime_selects_installed_private_catalog_and_keeps_expected_identity(tmp_path, fake_cpu, monkeypatch):
    bundle, manifest = _bundle(tmp_path)
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", "container-test-access-12345")
    monkeypatch.setenv("BUSHFIRE_RAG_ENABLED", "true")
    monkeypatch.setenv("BUSHFIRE_RAG_CORPUS_SHA256", manifest["manifest_sha256"])
    monkeypatch.setenv("BUSHFIRE_RAG_CORPUS_BUNDLE", str(bundle))
    monkeypatch.setattr(runtime, "validate_data_manifest", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        runtime, "install_rag_seed", lambda *_args, **_kwargs: pytest.fail("Legacy seed must not be used")
    )
    config = ModuleType("src.config")
    config.EXTERNAL_MODEL_ALLOWED = True
    config.MODEL_ENDPOINT_IS_LOCAL = False
    config.LLM_PROVIDER = "deepseek"
    config.model = "test-cloud-model"
    monkeypatch.setitem(sys.modules, "src.config", config)

    result = runtime.prepare_runtime()

    target = tmp_path / "volume" / "private-rag" / manifest["manifest_sha256"]
    assert os.environ["BUSHFIRE_RAG_SOURCES_PATH"] == str(target / "sources.yml")
    assert os.environ["BUSHFIRE_RAG_DIR"] == str(target)
    assert result["rag"]["corpus_manifest_sha256"] == manifest["manifest_sha256"]
    assert result["rag"]["status"] == "ready"


def test_empty_configured_corpus_identity_cannot_silently_use_legacy_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", "container-test-access-12345")
    monkeypatch.setenv("BUSHFIRE_RAG_ENABLED", "true")
    monkeypatch.setenv("BUSHFIRE_RAG_CORPUS_SHA256", "")
    monkeypatch.setattr(runtime, "validate_data_manifest", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        runtime, "install_rag_seed", lambda *_args, **_kwargs: pytest.fail("Empty hash must not use seed")
    )
    with pytest.raises(ValueError, match="BUSHFIRE_RAG_CORPUS_SHA256"):
        runtime.prepare_runtime(seed_dir=tmp_path / "available-seed")


def test_disappearing_existing_version_is_not_silently_rebuilt(tmp_path, fake_cpu, monkeypatch):
    import src.rag.index as index

    bundle, manifest = _bundle(tmp_path)
    target = runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])
    original_exists = Path.exists
    checks = []

    def disappearing(path):
        if path == target:
            checks.append(path)
            return len(checks) == 1
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", disappearing)
    monkeypatch.setattr(index, "build_rag_index", lambda *_: pytest.fail("Existing index must not be rebuilt"))
    with pytest.raises(ValueError, match="disappeared during initialization"):
        runtime.install_private_rag_corpus(bundle, manifest["manifest_sha256"])


def test_unconfigured_image_explains_required_private_corpus_configuration(monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", "container-test-access-12345")
    monkeypatch.setenv("BUSHFIRE_RAG_ENABLED", "true")
    monkeypatch.setattr(runtime, "validate_data_manifest", lambda *args, **kwargs: {})

    def missing_default_seed(_seed):
        raise ValueError("The image does not contain a valid RAG seed manifest.")

    monkeypatch.setattr(runtime, "install_rag_seed", missing_default_seed)
    with pytest.raises(ValueError, match="Include a private corpus bundle and set BUSHFIRE_RAG_CORPUS_SHA256"):
        runtime.prepare_runtime()
