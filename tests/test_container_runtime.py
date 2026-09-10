import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from src import container_runtime as runtime
from src.deployment_access import DeploymentConfigurationError
from src.rag.index import build_rag_index
from src.rag.settings import RagSettings


@pytest.fixture(autouse=True)
def _clean_container_configuration(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith(("BUSHFIRE_", "RAILWAY_")) or name == "PORT":
            monkeypatch.delenv(name)
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", str(tmp_path / "volume"))
    monkeypatch.setenv("BUSHFIRE_RAG_SOURCES_PATH", str(tmp_path / "sources.yml"))
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_MODEL", "container-test-model")
    # prepare_runtime sets these directly; register them for fixture teardown so
    # a startup test cannot leave a deleted temporary index in later tests.
    for name in ("BUSHFIRE_RAG_DIR", "BUSHFIRE_RAG_INDEX_DIR", "BUSHFIRE_RAG_RAW_DIR"):
        monkeypatch.setenv(name, "")


def _seed(tmp_path, *, label="first"):
    seed = tmp_path / f"seed-{label}"
    (seed / "raw").mkdir(parents=True)
    (seed / "raw" / "source.html").write_text(
        f"Preparedness guidance: {label}. "
        + "Queensland households should check official advice and plan property access and pet transport. " * 10,
        encoding="utf-8",
    )
    catalog = {
        "schema_version": 1,
        "sources": [
            {
                "source_id": "qld_test",
                "title": "Queensland preparedness test guide",
                "agency": "Queensland Test Agency",
                "url": "https://example.gov.au/qld-guide",
                "format": "markdown",
                "local_path": "raw/source.html",
                "jurisdictions": ["Queensland"],
                "audiences": ["community"],
                "scenarios": ["preparedness"],
                "document_date": "2026-01-01",
                "licence": "Test fixture",
                "licence_url": "https://example.gov.au/copyright",
                "reuse_status": "test_only",
                "last_verified_date": "2026-01-01",
            }
        ],
    }
    sources = tmp_path / "sources.yml"
    sources.write_text(json.dumps(catalog), encoding="utf-8")
    settings = replace(RagSettings.from_env(), rag_dir=seed, raw_dir=seed / "raw", index_dir=seed / "index")
    embedder = SimpleNamespace(embed=lambda texts: [[1.0, 0.0] for _text in texts])
    manifest = build_rag_index(settings, embedder)
    return seed, manifest["manifest_sha256"]


def _cloud_configuration(monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", "container-test-access-12345")
    monkeypatch.setenv("BUSHFIRE_RAG_ENABLED", "true")
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_PROVIDER", "fastembed")
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_MODEL", "BAAI/bge-small-en-v1.5")


@pytest.mark.parametrize("value", ["1", "8501", "65535", " 3000 "])
def test_port_accepts_valid_network_port(value):
    assert runtime.server_port(value) == int(value)


@pytest.mark.parametrize("value", ["", "zero", "1.5", "0", "-1", "65536"])
def test_port_rejects_invalid_network_port(value):
    with pytest.raises(ValueError, match="PORT must"):
        runtime.server_port(value)


def test_port_honors_railway_environment_and_has_local_default(monkeypatch):
    assert runtime.server_port() == 8501
    monkeypatch.setenv("PORT", "9123")
    assert runtime.server_port() == 9123
    assert "--server.port=9123" in runtime.streamlit_command(runtime.server_port())
    assert "--server.address=0.0.0.0" in runtime.streamlit_command(9123)


def test_seed_copies_raw_and_index_into_manifest_version_directory(tmp_path):
    seed, identity = _seed(tmp_path)
    target_root = tmp_path / "persistent" / "rag"

    target = runtime.install_rag_seed(seed, target_root=target_root)

    assert target == target_root / identity
    assert (target / "raw" / "source.html").read_bytes() == (seed / "raw" / "source.html").read_bytes()
    database = next((target / "index" / "qdrant").rglob("storage.sqlite"))
    assert database.read_bytes().startswith(b"SQLite format 3")
    assert not list(target_root.glob(".seed-*"))


def test_seed_version_upgrade_preserves_previous_version_and_existing_runtime_state(tmp_path):
    first, first_id = _seed(tmp_path, label="first")
    second, second_id = _seed(tmp_path, label="second")
    target_root = tmp_path / "persistent" / "rag"
    first_target = runtime.install_rag_seed(first, target_root=target_root)
    sentinel = first_target / "operator-record.txt"
    sentinel.write_text("existing persistent state", encoding="utf-8")

    assert runtime.install_rag_seed(first, target_root=target_root) == first_target
    second_target = runtime.install_rag_seed(second, target_root=target_root)

    assert first_target.name == first_id
    assert second_target.name == second_id
    assert first_target != second_target
    assert sentinel.read_text(encoding="utf-8") == "existing persistent state"


def test_seed_reuse_does_not_silently_overwrite_changed_existing_files(tmp_path):
    seed, _identity = _seed(tmp_path)
    root = tmp_path / "persistent"
    target = runtime.install_rag_seed(seed, target_root=root)
    modified = target / "raw" / "source.html"
    modified.write_text("changed persistent source", encoding="utf-8")

    assert runtime.install_rag_seed(seed, target_root=root) == target
    assert modified.read_text(encoding="utf-8") == "changed persistent source"


@pytest.mark.parametrize("manifest", ["not json", "[]", "{}", '{"manifest_sha256":"../../outside"}'])
def test_bad_seed_identity_fails_before_publishing_any_runtime_version(tmp_path, manifest):
    seed, _identity = _seed(tmp_path)
    (seed / "index" / "manifest.json").write_text(manifest, encoding="utf-8")
    target_root = tmp_path / "persistent"

    with pytest.raises(ValueError, match="seed"):
        runtime.install_rag_seed(seed, target_root=target_root)

    assert not target_root.exists() or not list(target_root.iterdir())


def test_seed_self_hash_mismatch_does_not_poison_persistent_version(tmp_path):
    seed, _identity = _seed(tmp_path)
    manifest_path = seed / "index" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["chunk_count"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    root = tmp_path / "persistent"

    with pytest.raises(ValueError, match="hash"):
        runtime.install_rag_seed(seed, target_root=root)

    assert not root.exists() or not list(root.iterdir())


def test_seed_copies_data_without_build_time_locks_and_temporary_files(tmp_path):
    seed, _identity = _seed(tmp_path)
    (seed / ".index.lock.guard").write_bytes(b"")
    (seed / ".index.lock").write_text('{"pid":1,"token":"build-process"}', encoding="ascii")
    (seed / ".index.abandoned.stage").mkdir()
    (seed / ".index.abandoned.stage" / "partial.bin").write_bytes(b"incomplete")
    (seed / "index" / "qdrant" / ".lock").write_bytes(b"")

    target = runtime.install_rag_seed(seed, target_root=tmp_path / "persistent")

    assert not (target / ".index.lock.guard").exists()
    assert not (target / ".index.lock").exists()
    assert not (target / ".index.abandoned.stage").exists()
    assert not (target / "index" / "qdrant" / ".lock").exists()
    assert list((target / "index" / "qdrant").rglob("storage.sqlite"))


def test_partial_seed_copy_does_not_publish_a_version(tmp_path, monkeypatch):
    seed, identity = _seed(tmp_path)
    target_root = tmp_path / "persistent"

    def failed_copy(source, destination, *args, **kwargs):
        Path(destination).mkdir(parents=True)
        (Path(destination) / "partial.bin").write_bytes(b"partial")
        raise OSError("simulated full volume")

    monkeypatch.setattr(runtime.shutil, "copytree", failed_copy)
    with pytest.raises(OSError, match="full volume"):
        runtime.install_rag_seed(seed, target_root=target_root)

    assert not (target_root / identity).exists()
    assert not list(target_root.glob(".seed-*"))


def test_existing_version_file_is_rejected_without_overwriting_it(tmp_path):
    seed, identity = _seed(tmp_path)
    root = tmp_path / "persistent"
    root.mkdir()
    target = root / identity
    target.write_bytes(b"existing operator data")

    with pytest.raises(ValueError, match="directory"):
        runtime.install_rag_seed(seed, target_root=root)

    assert target.read_bytes() == b"existing operator data"


def test_root_volume_initialization_changes_only_root_ownership_then_drops_privileges(tmp_path, monkeypatch):
    directory = tmp_path / "volume"
    directory.mkdir()
    old_data = directory / "existing.txt"
    old_data.write_bytes(b"do not modify")
    account = SimpleNamespace(pw_uid=10001, pw_gid=10001, pw_dir="/home/bushfire")
    calls = []
    fake_os = SimpleNamespace(
        name="posix",
        getuid=lambda: 0,
        chown=lambda path, uid, gid: calls.append(("chown", path, uid, gid)),
        setgroups=lambda groups: calls.append(("groups", groups)),
        setgid=lambda gid: calls.append(("gid", gid)),
        setuid=lambda uid: calls.append(("uid", uid)),
        environ={},
    )
    monkeypatch.setattr(runtime, "os", fake_os)
    monkeypatch.setattr(runtime, "runtime_path", lambda: directory)
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwnam=lambda name: account))

    runtime.initialize_volume_permissions()

    assert calls == [("chown", directory, 10001, 10001), ("groups", []), ("gid", 10001), ("uid", 10001)]
    assert fake_os.environ["HOME"] == "/home/bushfire"
    assert old_data.read_bytes() == b"do not modify"


def test_nonroot_volume_initialization_does_not_attempt_privilege_changes(tmp_path, monkeypatch):
    directory = tmp_path / "volume"
    monkeypatch.setattr(runtime, "runtime_path", lambda: directory)
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name="posix", getuid=lambda: 10001))

    runtime.initialize_volume_permissions()

    assert directory.is_dir()


def test_cloud_configuration_is_validated_before_seed_or_data_access(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setattr(runtime, "get_data_paths", lambda: pytest.fail("data loaded before access validation"))

    with pytest.raises(DeploymentConfigurationError, match="Cloud access requires"):
        runtime.prepare_runtime(seed_dir=tmp_path / "seed")


def test_invalid_port_stops_startup_before_data_access(monkeypatch):
    _cloud_configuration(monkeypatch)
    monkeypatch.setenv("PORT", "65536")
    monkeypatch.setattr(runtime, "get_data_paths", lambda: pytest.fail("data loaded with invalid PORT"))

    with pytest.raises(ValueError, match="PORT"):
        runtime.prepare_runtime()


def test_cloud_cannot_start_with_rag_disabled(monkeypatch, tmp_path):
    _cloud_configuration(monkeypatch)
    monkeypatch.setenv("BUSHFIRE_RAG_ENABLED", "false")
    monkeypatch.setattr(
        runtime, "get_data_paths", lambda: SimpleNamespace(manifest=tmp_path / "manifest.json", data_dir=tmp_path)
    )
    monkeypatch.setattr(runtime, "validate_data_manifest", lambda *args, **kwargs: {})

    with pytest.raises(ValueError, match="BUSHFIRE_RAG_ENABLED=true"):
        runtime.prepare_runtime(seed_dir=tmp_path / "missing-seed")


def _stub_prepared_cloud(monkeypatch, tmp_path, *, warmup_status="ready"):
    import src.rag.index as index_module
    import src.rag.service as service_module

    _cloud_configuration(monkeypatch)
    target = tmp_path / "volume" / "rag" / ("a" * 64)
    (target / "index").mkdir(parents=True)
    (target / "raw").mkdir()
    monkeypatch.setattr(runtime, "install_rag_seed", lambda _seed: target)
    monkeypatch.setattr(runtime, "validate_data_manifest", lambda *args, **kwargs: {})
    monkeypatch.setattr(index_module, "load_and_validate_index", lambda _settings: {"manifest_sha256": "a" * 64})
    calls = []

    def service(settings):
        def retrieve(query, **kwargs):
            calls.append((settings, query, kwargs))
            return {"status": warmup_status}

        return SimpleNamespace(retrieve=retrieve)

    monkeypatch.setattr(service_module, "RagService", service)
    config = ModuleType("src.config")
    config.EXTERNAL_MODEL_ALLOWED = True
    config.MODEL_ENDPOINT_IS_LOCAL = False
    config.LLM_PROVIDER = "deepseek"
    config.model = "test-cloud-model"
    monkeypatch.setitem(sys.modules, "src.config", config)
    return target, calls, config


@pytest.mark.parametrize("warmup_status", ["ready", "no_match"])
def test_cloud_startup_warms_retrieval_and_uses_versioned_volume_paths(monkeypatch, tmp_path, warmup_status):
    target, calls, _config = _stub_prepared_cloud(monkeypatch, tmp_path, warmup_status=warmup_status)
    monkeypatch.setenv("PORT", "9999")

    result = runtime.prepare_runtime(seed_dir=tmp_path / "image-seed")

    assert result == {
        "port": 9999,
        "provider": "deepseek",
        "model": "test-cloud-model",
        "rag": {"status": "ready", "manifest_sha256": "a" * 64},
    }
    assert len(calls) == 1
    settings, query, kwargs = calls[0]
    assert settings.rag_dir == target
    assert settings.raw_dir == target / "raw"
    assert settings.index_dir == target / "index"
    assert settings.sources_path == tmp_path / "sources.yml"
    assert settings.embedding_provider == "fastembed"
    assert query == "Bushfire preparedness planning"
    assert kwargs == {"trusted_planning_scope": True}


@pytest.mark.parametrize("warmup_status", ["invalid", "unavailable", "not_built", "disabled", "out_of_scope"])
def test_failed_retrieval_warmup_cannot_report_container_ready(monkeypatch, tmp_path, warmup_status):
    _stub_prepared_cloud(monkeypatch, tmp_path, warmup_status=warmup_status)

    with pytest.raises(ValueError, match="verified retrieval"):
        runtime.prepare_runtime(seed_dir=tmp_path / "image-seed")


@pytest.mark.parametrize(
    ("endpoint_is_local", "external_allowed"),
    [(True, True), (False, False)],
)
def test_cloud_cannot_use_local_or_unacknowledged_external_model(
    monkeypatch, tmp_path, endpoint_is_local, external_allowed
):
    _target, _calls, config = _stub_prepared_cloud(monkeypatch, tmp_path)
    config.MODEL_ENDPOINT_IS_LOCAL = endpoint_is_local
    config.EXTERNAL_MODEL_ALLOWED = external_allowed

    with pytest.raises(ValueError, match="allowed HTTPS external model"):
        runtime.prepare_runtime(seed_dir=tmp_path / "image-seed")


def test_startup_fails_when_persistent_volume_is_not_writable(monkeypatch, tmp_path):
    _stub_prepared_cloud(monkeypatch, tmp_path)

    def denied_probe(*args, **kwargs):
        raise PermissionError("volume is not writable")

    monkeypatch.setattr(runtime.tempfile, "TemporaryFile", denied_probe)

    with pytest.raises(PermissionError, match="volume is not writable"):
        runtime.prepare_runtime(seed_dir=tmp_path / "image-seed")
