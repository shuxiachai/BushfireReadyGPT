import json
import math
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
import yaml

import src.rag.index as index_module
import src.rag.service as service_module
from src.rag.errors import RagError
from src.rag.index import build_rag_index, index_file_lock
from src.rag.service import RagService, format_retrieved_context, inspect_rag_index
from src.rag.settings import RagSettings


class KeywordEmbedder:
    def embed(self, texts):
        vectors = []
        for text in texts:
            lowered = str(text).lower()
            vector = [
                sum(lowered.count(term) for term in ("queensland", "household", "leave", "property")),
                sum(lowered.count(term) for term in ("route", "pets", "assembly")),
            ]
            if not any(vector):
                vector[1] = 1
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


def _settings(tmp_path):
    rag_dir = tmp_path / "rag"
    raw_dir = rag_dir / "raw"
    raw_dir.mkdir(parents=True)
    source_path = raw_dir / "guide.md"
    source_path.write_text(
        (
            "Queensland household bushfire planning should decide when to leave, where to go, "
            "how pets will travel, and how property access and backup routes will be checked. "
        )
        * 20,
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
        ],
    }
    sources_path = rag_dir / "sources.yml"
    sources_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")
    return (
        RagSettings(
            rag_dir=rag_dir,
            sources_path=sources_path,
            raw_dir=raw_dir,
            index_dir=rag_dir / "index",
            embedding_base_url="http://127.0.0.1:11434",
            embedding_model="keyword-test-model",
            embedding_timeout_seconds=5,
            embedding_batch_size=8,
            top_k=4,
            score_threshold=0.1,
        ),
        source_path,
    )


def _build(settings):
    return build_rag_index(settings, KeywordEmbedder(), max_words=50, overlap_words=10)


def _retrieve(settings, embedder=None):
    return RagService(settings, embedder=embedder or KeywordEmbedder()).retrieve(
        "Queensland household leave early property route plan",
        jurisdiction="Queensland",
    )


def test_disabled_rag_does_not_touch_an_unusable_index_parent(tmp_path):
    settings, _source_path = _settings(tmp_path)
    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("this path must never be used as a directory", encoding="utf-8")
    disabled = replace(
        settings,
        enabled=False,
        rag_dir=blocked_root,
        raw_dir=blocked_root / "raw",
        sources_path=blocked_root / "sources.yml",
        index_dir=blocked_root / "index",
    )

    status = inspect_rag_index(disabled)
    result = _retrieve(disabled)
    not_installed_status = inspect_rag_index(replace(disabled, enabled=True))
    not_installed_result = _retrieve(replace(disabled, enabled=True))

    assert status["state"] == "disabled"
    assert result["status"] == "disabled"
    assert not_installed_status["state"] == "not_installed"
    assert not_installed_result["status"] == "not_installed"
    assert blocked_root.is_file()


def test_index_lock_filesystem_errors_are_normalised_and_degraded(tmp_path):
    settings, _source_path = _settings(tmp_path)
    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("this cannot contain the index lock", encoding="utf-8")
    unusable = replace(
        settings,
        rag_dir=blocked_root,
        index_dir=blocked_root / "index",
    )

    status = inspect_rag_index(unusable)
    result = _retrieve(unusable)

    assert status["state"] == "invalid"
    assert status["error_code"] == "rag_index_lock_failed"
    assert result["status"] == "unavailable"
    assert result["error_code"] == "rag_index_lock_failed"


def test_old_lock_owned_by_a_running_process_is_not_reclaimed(tmp_path):
    settings, _source_path = _settings(tmp_path)
    lock_path = settings.rag_dir / ".index.lock"
    owner = {"pid": os.getpid(), "token": "still-active"}
    lock_path.write_text(json.dumps(owner), encoding="ascii")
    old_timestamp = time.time() - index_module._STALE_INDEX_LOCK_SECONDS - 60
    os.utime(lock_path, (old_timestamp, old_timestamp))

    with pytest.raises(RagError) as captured:
        with index_file_lock(settings, timeout_seconds=0):
            pass

    assert captured.value.code == "rag_index_locked"
    assert json.loads(lock_path.read_text(encoding="ascii")) == owner
    lock_path.unlink()


def test_index_lock_release_only_removes_its_own_token(tmp_path):
    settings, _source_path = _settings(tmp_path)
    lock_path = settings.rag_dir / ".index.lock"
    successor = {"pid": os.getpid(), "token": "successor-owner"}

    with index_file_lock(settings):
        current = json.loads(lock_path.read_text(encoding="ascii"))
        assert current["token"] != successor["token"]
        lock_path.write_text(json.dumps(successor), encoding="ascii")

    assert json.loads(lock_path.read_text(encoding="ascii")) == successor
    lock_path.unlink()


def test_old_lock_is_reclaimed_only_after_its_owner_is_confirmed_dead(tmp_path, monkeypatch):
    settings, _source_path = _settings(tmp_path)
    lock_path = settings.rag_dir / ".index.lock"
    lock_path.write_text(json.dumps({"pid": 424242, "token": "dead-owner"}), encoding="ascii")
    old_timestamp = time.time() - index_module._STALE_INDEX_LOCK_SECONDS - 60
    os.utime(lock_path, (old_timestamp, old_timestamp))
    monkeypatch.setattr(index_module, "_process_is_running", lambda _pid: False)

    with index_file_lock(settings, timeout_seconds=0):
        owner = json.loads(lock_path.read_text(encoding="ascii"))
        assert owner["token"] != "dead-owner"

    assert not lock_path.exists()


def test_failed_lock_initialisation_does_not_leave_a_permanent_lock(tmp_path, monkeypatch):
    settings, _source_path = _settings(tmp_path)
    lock_path = settings.rag_dir / ".index.lock"
    original_write = index_module.os.write

    monkeypatch.setattr(
        index_module.os,
        "write",
        lambda *_args: (_ for _ in ()).throw(OSError("simulated lock write failure")),
    )
    with pytest.raises(RagError) as captured:
        with index_file_lock(settings):
            pass

    assert captured.value.code == "rag_index_lock_failed"
    assert not lock_path.exists()

    monkeypatch.setattr(index_module.os, "write", original_write)
    with index_file_lock(settings):
        assert lock_path.is_file()
    assert not lock_path.exists()


def test_young_incomplete_index_lock_is_not_reclaimed(tmp_path):
    settings, _source_path = _settings(tmp_path)
    lock_path = settings.rag_dir / ".index.lock"
    lock_path.write_bytes(b"")

    with pytest.raises(RagError) as captured:
        with index_file_lock(settings, timeout_seconds=0):
            pass

    assert captured.value.code == "rag_index_locked"
    assert lock_path.exists()


def test_old_empty_index_lock_left_by_a_crashed_process_is_reclaimed(tmp_path):
    settings, _source_path = _settings(tmp_path)
    lock_path = settings.rag_dir / ".index.lock"
    script = (
        "import os, sys; descriptor = os.open(sys.argv[1], os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.close(descriptor)"
    )
    subprocess.run([sys.executable, "-c", script, str(lock_path)], check=True)
    old_timestamp = time.time() - index_module._STALE_INDEX_LOCK_SECONDS - 60
    os.utime(lock_path, (old_timestamp, old_timestamp))

    with index_file_lock(settings, timeout_seconds=0):
        owner = json.loads(lock_path.read_text(encoding="ascii"))
        assert owner["pid"] == os.getpid()
        assert owner["token"]

    assert not lock_path.exists()


def test_build_aborts_if_a_source_changes_during_embedding_without_publishing(tmp_path):
    settings, source_path = _settings(tmp_path)
    original_manifest = _build(settings)
    manifest_path = settings.index_dir / "manifest.json"
    original_manifest_bytes = manifest_path.read_bytes()

    class MutatingEmbedder(KeywordEmbedder):
        def embed(self, texts):
            vectors = super().embed(texts)
            source_path.write_text("CHANGED WHILE EMBEDDING " * 80, encoding="utf-8")
            return vectors

    with pytest.raises(RagError) as captured:
        build_rag_index(settings, MutatingEmbedder(), max_words=50, overlap_words=10)

    assert captured.value.code == "rag_source_changed"
    assert manifest_path.read_bytes() == original_manifest_bytes
    assert original_manifest["manifest_sha256"] in original_manifest_bytes.decode("utf-8")
    assert inspect_rag_index(settings)["state"] == "invalid"
    assert not list(settings.rag_dir.glob(".index.*.stage"))


def test_concurrent_queries_share_one_embedded_qdrant_client_slot(tmp_path, monkeypatch):
    settings, _source_path = _settings(tmp_path)
    _build(settings)
    original_query_index = RagService._query_index
    counter_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def observed_query_index(self, *args, **kwargs):
        nonlocal active, maximum_active
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.1)
            return original_query_index(self, *args, **kwargs)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(RagService, "_query_index", observed_query_index)
    start = threading.Barrier(3)

    def run_query():
        start.wait()
        return _retrieve(settings)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_query) for _ in range(2)]
        start.wait()
        results = [future.result(timeout=10) for future in futures]

    assert maximum_active == 1
    assert all(result["status"] == "ready" for result in results)


def test_query_waits_for_same_process_index_build(tmp_path):
    settings, _source_path = _settings(tmp_path)
    _build(settings)
    build_entered = threading.Event()
    release_build = threading.Event()
    query_worker_entered = threading.Event()
    query_embedding_called = threading.Event()

    class BlockingBuildEmbedder(KeywordEmbedder):
        def embed(self, texts):
            build_entered.set()
            if not release_build.wait(timeout=10):
                raise AssertionError("test did not release the blocked index build")
            return super().embed(texts)

    class ObservedQueryEmbedder(KeywordEmbedder):
        def embed(self, texts):
            query_embedding_called.set()
            return super().embed(texts)

    def run_build():
        return build_rag_index(settings, BlockingBuildEmbedder(), max_words=50, overlap_words=10)

    def run_query():
        query_worker_entered.set()
        return _retrieve(settings, ObservedQueryEmbedder())

    with ThreadPoolExecutor(max_workers=2) as executor:
        build_future = executor.submit(run_build)
        assert build_entered.wait(timeout=5)
        query_future = executor.submit(run_query)
        assert query_worker_entered.wait(timeout=5)
        try:
            assert not query_embedding_called.wait(timeout=0.2)
        finally:
            release_build.set()
        build_future.result(timeout=10)
        result = query_future.result(timeout=10)

    assert query_embedding_called.is_set()
    assert result["status"] == "ready"


def test_query_waits_for_cross_process_file_lock(tmp_path):
    settings, _source_path = _settings(tmp_path)
    _build(settings)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with index_file_lock(settings):
            query_future = executor.submit(_retrieve, settings)
            time.sleep(0.2)
            assert not query_future.done()
        result = query_future.result(timeout=10)

    assert result["status"] == "ready"


def test_publish_rolls_back_if_sources_change_in_commit_window(tmp_path, monkeypatch):
    settings, source_path = _settings(tmp_path)
    _build(settings)
    manifest_path = settings.index_dir / "manifest.json"
    original_manifest_bytes = manifest_path.read_bytes()
    original_changed = index_module._source_generation_changed
    checks = 0

    def change_at_publish(*args, **kwargs):
        nonlocal checks
        checks += 1
        if checks == 4:
            source_path.write_text("CHANGED DURING PUBLICATION " * 80, encoding="utf-8")
        return original_changed(*args, **kwargs)

    monkeypatch.setattr(index_module, "_source_generation_changed", change_at_publish)

    with pytest.raises(RagError) as captured:
        _build(settings)

    assert captured.value.code == "rag_source_changed"
    assert manifest_path.read_bytes() == original_manifest_bytes
    assert not (settings.rag_dir / ".index.backup").exists()


def test_interrupted_publish_preserves_backup_until_old_index_can_be_restored(tmp_path, monkeypatch):
    target = tmp_path / "index"
    staging = tmp_path / ".index.test.stage"
    backup = tmp_path / ".index.backup"
    target.mkdir()
    staging.mkdir()
    (target / "generation.txt").write_text("old", encoding="utf-8")
    (staging / "generation.txt").write_text("new", encoding="utf-8")
    original_remove = index_module._remove_index_path

    def fail_new_target_removal(path):
        if path == target:
            raise PermissionError("simulated interrupted rollback")
        return original_remove(path)

    monkeypatch.setattr(index_module, "_remove_index_path", fail_new_target_removal)
    with pytest.raises(PermissionError, match="interrupted rollback"):
        index_module._publish_index(staging, target, validate_published=lambda: False)

    assert (backup / "generation.txt").read_text(encoding="utf-8") == "old"
    assert (target / "generation.txt").read_text(encoding="utf-8") == "new"

    monkeypatch.setattr(index_module, "_remove_index_path", original_remove)
    index_module._recover_index_publish(target)

    assert (target / "generation.txt").read_text(encoding="utf-8") == "old"
    assert not backup.exists()


def test_committed_publish_never_reinterprets_a_partial_retired_cleanup_as_backup(tmp_path, monkeypatch):
    target = tmp_path / "index"
    staging = tmp_path / ".index.test.stage"
    target.mkdir()
    staging.mkdir()
    (target / "generation.txt").write_text("old", encoding="utf-8")
    (staging / "generation.txt").write_text("new", encoding="utf-8")
    original_rmtree = index_module.shutil.rmtree

    def interrupt_retired_cleanup(path, *args, **kwargs):
        if str(path).endswith(".retired"):
            raise PermissionError("simulated retired cleanup interruption")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(index_module.shutil, "rmtree", interrupt_retired_cleanup)
    with pytest.raises(PermissionError, match="retired cleanup interruption"):
        index_module._publish_index(staging, target, validate_published=lambda: True)

    assert (target / "generation.txt").read_text(encoding="utf-8") == "new"
    assert not (tmp_path / ".index.backup").exists()
    assert len(list(tmp_path.glob(".index.*.retired"))) == 1

    monkeypatch.setattr(index_module.shutil, "rmtree", original_rmtree)
    index_module._recover_index_publish(target)

    assert (target / "generation.txt").read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".index.*.retired"))


def test_manifest_schema_and_filesystem_failures_degrade_without_raw_exceptions(tmp_path, monkeypatch):
    settings, _source_path = _settings(tmp_path)
    _build(settings)
    manifest_path = settings.index_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("source_count")
    manifest["manifest_sha256"] = index_module._canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    status = inspect_rag_index(settings)
    result = _retrieve(settings)

    assert status["state"] == "invalid"
    assert status["error_code"] == "rag_index_invalid"
    assert result["status"] == "invalid"
    assert result["error_code"] == "rag_index_invalid"

    _build(settings)

    def deny_hash_read(_path):
        raise PermissionError("simulated index read denial")

    monkeypatch.setattr(index_module, "sha256_file", deny_hash_read)
    status = inspect_rag_index(settings)
    result = _retrieve(settings)

    assert status["state"] == "invalid"
    assert status["error_code"] == "rag_index_invalid"
    assert result["status"] == "invalid"
    assert result["error_code"] == "rag_index_invalid"


def test_retrieve_performs_exactly_two_full_index_validations(tmp_path, monkeypatch):
    settings, _source_path = _settings(tmp_path)
    _build(settings)
    original_validate = service_module.load_and_validate_index
    validation_calls = 0

    def counted_validate(active_settings):
        nonlocal validation_calls
        validation_calls += 1
        return original_validate(active_settings)

    monkeypatch.setattr(service_module, "load_and_validate_index", counted_validate)

    result = _retrieve(settings)

    assert result["status"] == "ready"
    assert validation_calls == 2


def test_retrieved_context_budget_counts_double_newline_separators():
    knowledge = {
        "retrieved_chunks": [
            {
                "source_id": "official-test",
                "chunk_id": "chunk-1",
                "page": 2,
                "score": 0.9,
                "chunk_sha256": "a" * 64,
                "title": "Official test",
                "agency": "Test agency",
                "url": "https://example.gov.au/test",
                "text": "bounded planning evidence " * 20,
            }
        ]
    }
    full_context = format_retrieved_context(knowledge, max_characters=10000, max_chunk_characters=300)
    exact_too_small_budget = len(full_context) - 1

    bounded_context = format_retrieved_context(
        knowledge,
        max_characters=exact_too_small_budget,
        max_chunk_characters=300,
    )

    assert len(bounded_context) <= exact_too_small_budget
    assert "chunk=chunk-1" not in bounded_context
