"""Isolated regressions for the external audit's lock/trace findings."""

import json
import multiprocessing
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import runtime_trace
from src.rag import index as index_module
from src.rag.errors import RagError


def _stale_recovery_worker(root, name, barrier, first_entered, second_entered, release, counts, results):
    """Force the actual legacy read/unlink interleaving in independent processes."""
    from src.file_lock import read_lock_owner

    settings = SimpleNamespace(rag_dir=Path(root), index_dir=Path(root) / "index")
    original = index_module._index_lock_can_be_reclaimed

    def checked_reclaim(path, *, kernel_guarded=False):
        reclaim = original(path, kernel_guarded=kernel_guarded)
        if reclaim and not kernel_guarded:
            # Both legacy contenders have read the same stale owner. The second
            # resumes its unlink only once the first has entered its section.
            barrier.wait(timeout=15)
            if name == "second" and not first_entered.wait(timeout=15):
                raise AssertionError("first contender did not acquire the record")
        return reclaim

    index_module._index_lock_can_be_reclaimed = checked_reclaim
    index_module._process_is_running = lambda _pid: False
    try:
        with index_module.index_file_lock(settings, timeout_seconds=15):
            with counts.get_lock():
                counts[0] += 1
                counts[1] = max(counts[0], counts[1])
            try:
                owner = read_lock_owner(settings.rag_dir / ".index.lock")
                results.put(("entered", name, bool(owner.get("kernel_guard"))))
                (first_entered if name == "first" else second_entered).set()
                if not release.wait(timeout=20):
                    raise AssertionError("test did not release the critical section")
            finally:
                with counts.get_lock():
                    counts[0] -= 1
    except BaseException as error:
        results.put(("error", name, type(error).__name__))
        raise


@pytest.mark.skipif(os.name != "nt", reason="real Windows stale-recovery race")
def test_windows_stale_recovery_never_admits_two_processes(tmp_path):
    lock_path = tmp_path / ".index.lock"
    lock_path.write_text(json.dumps({"pid": 424242, "token": "dead-owner"}), encoding="ascii")
    timestamp = time.time() - index_module._STALE_INDEX_LOCK_SECONDS - 60
    os.utime(lock_path, (timestamp, timestamp))
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    first_entered, second_entered, release = (context.Event() for _ in range(3))
    counts = context.Array("i", [0, 0])
    results = context.Queue()
    processes = [
        context.Process(
            target=_stale_recovery_worker,
            args=(str(tmp_path), name, barrier, first_entered, second_entered, release, counts, results),
        )
        for name in ("first", "second")
    ]
    try:
        for process in processes:
            process.start()
        event, _name, guarded = results.get(timeout=20)
        assert event == "entered"
        if not guarded:
            # Legacy code must demonstrate the second admission while the first
            # is still active. Fixed code blocks it at the native stable guard.
            assert second_entered.wait(timeout=10)
        release.set()
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        assert counts[1] == 1
        assert guarded is True
        assert (tmp_path / ".index.lock.guard").is_file()
    finally:
        release.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(timeout=5)
        results.close()
        results.join_thread()


def test_thread_lock_wait_obeys_the_requested_acquisition_budget(tmp_path):
    settings = SimpleNamespace(rag_dir=tmp_path, index_dir=tmp_path / "index")
    entered, release = threading.Event(), threading.Event()

    def hold():
        with index_module.index_access_lock(settings):
            entered.set()
            assert release.wait(timeout=10)

    def acquire():
        with index_module.index_read_write_lock(settings, timeout_seconds=0.25):
            return "unexpected admission"

    with ThreadPoolExecutor(max_workers=2) as executor:
        holder = executor.submit(hold)
        assert entered.wait(timeout=5)
        contender = executor.submit(acquire)
        try:
            try:
                with pytest.raises(RagError) as captured:
                    contender.result(timeout=2)
            except FutureTimeout:
                pytest.fail("the process-local lock ignored the shared acquisition deadline")
            assert captured.value.code == "rag_index_locked"
        finally:
            release.set()
        holder.result(timeout=5)


def test_lock_registry_wait_is_also_bounded(tmp_path):
    settings = SimpleNamespace(rag_dir=tmp_path, index_dir=tmp_path / "index")
    with index_module._PROCESS_INDEX_LOCKS_GUARD:
        with pytest.raises(RagError) as captured:
            with index_module.index_read_write_lock(settings, timeout_seconds=0):
                pytest.fail("registry lock was ignored")
    assert captured.value.code == "rag_index_locked"


def test_zero_budget_still_permits_immediate_uncontended_acquisition(tmp_path):
    settings = SimpleNamespace(rag_dir=tmp_path, index_dir=tmp_path / "index")
    with index_module.index_read_write_lock(settings, timeout_seconds=0):
        assert (tmp_path / ".index.lock").is_file()


def test_process_kernel_and_record_waits_share_one_budget(tmp_path, monkeypatch):
    settings = SimpleNamespace(rag_dir=tmp_path, index_dir=tmp_path / "index")
    elapsed = [100.0]
    observed = []
    monkeypatch.setattr(index_module.time, "monotonic", lambda: elapsed[0])

    @contextmanager
    def process_lock(_settings, timeout_seconds):
        observed.append(("process", timeout_seconds))
        elapsed[0] += 3
        yield

    @contextmanager
    def kernel_lock(_path, timeout_seconds):
        observed.append(("kernel", timeout_seconds))
        elapsed[0] += 4
        yield True

    @contextmanager
    def record_lock(_path, timeout_seconds, *, kernel_guarded):
        assert kernel_guarded
        observed.append(("record", timeout_seconds))
        yield

    monkeypatch.setattr(index_module, "index_access_lock", process_lock)
    monkeypatch.setattr(index_module, "kernel_lock_guard", kernel_lock)
    monkeypatch.setattr(index_module, "_index_lock_record", record_lock)
    with index_module.index_read_write_lock(settings, timeout_seconds=10):
        pass
    assert observed == [("process", 10), ("kernel", 7), ("record", 3)]


@pytest.mark.parametrize("timeout", [-1, True, None, "1", float("inf"), float("nan"), 10**1000])
def test_invalid_lock_budgets_fail_with_a_controlled_error(tmp_path, timeout):
    settings = SimpleNamespace(rag_dir=tmp_path, index_dir=tmp_path / "index")
    with pytest.raises(RagError) as captured:
        with index_module.index_read_write_lock(settings, timeout_seconds=timeout):
            pytest.fail("invalid timeout was accepted")
    assert captured.value.code == "rag_config_invalid"


@pytest.mark.skipif(os.name != "nt", reason="Windows native guard recovery")
def test_windows_guard_recovers_record_after_release_failure_without_waiting_for_pid_exit(tmp_path, monkeypatch):
    settings = SimpleNamespace(rag_dir=tmp_path, index_dir=tmp_path / "index")
    original_release = index_module._release_index_file_lock

    def fail_release(*_args):
        raise RagError("rag_index_lock_failed", "simulated release failure")

    monkeypatch.setattr(index_module, "_release_index_file_lock", fail_release)
    with pytest.raises(RagError, match="simulated release failure"):
        with index_module.index_file_lock(settings, timeout_seconds=0):
            pass
    previous = json.loads((tmp_path / ".index.lock").read_text(encoding="ascii"))
    assert previous["pid"] == os.getpid()
    assert previous["kernel_guard"] == "windows-byte-lock-v1"
    monkeypatch.setattr(index_module, "_release_index_file_lock", original_release)
    with index_module.index_file_lock(settings, timeout_seconds=0):
        current = json.loads((tmp_path / ".index.lock").read_text(encoding="ascii"))
        assert current["token"] != previous["token"]
    assert not (tmp_path / ".index.lock").exists()
    assert (tmp_path / ".index.lock.guard").is_file()


@pytest.fixture
def valid_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path))
    with runtime_trace.RuntimeTrace("report.generate") as trace:
        with trace.stage("model_generation", attempt=1):
            pass
    path = Path(trace.path)
    return path, json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("privacy", [None, [], "invalid", 3, True])
def test_malformed_trace_privacy_is_counted_without_crashing(tmp_path, valid_trace, privacy):
    path, record = valid_trace
    record["privacy"] = privacy
    path.write_text(json.dumps(record), encoding="utf-8")
    summary = runtime_trace.load_trace_summary(trace_dir=tmp_path)
    assert summary["traces"] == 0
    assert summary["invalid_files"] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation", []),
        ("status", {}),
        ("trace_id", 123),
        ("duration_ms", True),
        ("duration_ms", 10**1000),
        ("duration_ms", float("nan")),
        ("duration_ms", float("inf")),
        ("started_at_utc", {}),
        ("completed_at_utc", "sensitive free text"),
        ("completed_at_utc", "2026-99-99T00:00:00.000Z"),
        ("error_code", []),
        ("metrics", None),
        ("metrics", {"support_rate": 10**1000}),
        ("metrics", {"support_rate": float("nan")}),
        ("stages", {}),
    ],
)
def test_invalid_trace_fields_do_not_break_valid_neighbour(tmp_path, valid_trace, field, value):
    _valid_path, record = valid_trace
    record[field] = value
    (tmp_path / "trace_bad.json").write_text(json.dumps(record), encoding="utf-8")
    summary = runtime_trace.load_trace_summary(trace_dir=tmp_path)
    assert summary["traces"] == 1
    assert summary["invalid_files"] == 1
    assert "sensitive free text" not in json.dumps(summary)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", []),
        ("status", {}),
        ("error_code", []),
        ("duration_ms", False),
        ("duration_ms", 10**1000),
        ("metrics", None),
        ("metrics", []),
        ("metrics", {"prompt": "private prompt"}),
    ],
)
def test_invalid_trace_stage_fields_are_isolated(tmp_path, valid_trace, field, value):
    path, record = valid_trace
    record["stages"][0][field] = value
    path.write_text(json.dumps(record), encoding="utf-8")
    summary = runtime_trace.load_trace_summary(trace_dir=tmp_path)
    assert summary["traces"] == 0
    assert summary["invalid_files"] == 1


def test_trace_stage_count_is_bounded(tmp_path, valid_trace):
    path, record = valid_trace
    record["stages"] *= 51
    path.write_text(json.dumps(record), encoding="utf-8")
    assert runtime_trace.load_trace_summary(trace_dir=tmp_path)["invalid_files"] == 1


def test_oversized_and_deep_trace_files_are_isolated(tmp_path, valid_trace):
    (tmp_path / "trace_large.json").write_bytes(b" " * (runtime_trace.MAX_TRACE_FILE_BYTES + 1))
    (tmp_path / "trace_nested.json").write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
    summary = runtime_trace.load_trace_summary(trace_dir=tmp_path)
    assert summary["traces"] == 1
    assert summary["invalid_files"] == 2


def test_trace_read_remains_bounded_if_file_grows_after_stat(tmp_path, valid_trace, monkeypatch):
    path, _record = valid_trace
    original_open = Path.open
    read_sizes = []

    class GrowingFile:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size=-1):
            read_sizes.append(size)
            assert size == runtime_trace.MAX_TRACE_FILE_BYTES + 1
            return b" " * size

    monkeypatch.setattr(
        Path, "open", lambda item, *args, **kw: GrowingFile() if item == path else original_open(item, *args, **kw)
    )
    summary = runtime_trace.load_trace_summary(trace_dir=tmp_path)
    assert summary["invalid_files"] == 1
    assert read_sizes == [runtime_trace.MAX_TRACE_FILE_BYTES + 1]


def test_scan_budget_reports_truncation_and_known_unread_files(tmp_path, valid_trace, monkeypatch):
    _path, record = valid_trace
    for index in range(4):
        (tmp_path / f"trace_copy{index}.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(runtime_trace, "MAX_TRACE_SCAN_ENTRIES", 3)
    summary = runtime_trace.load_trace_summary(trace_dir=tmp_path, limit=1)
    assert summary["traces"] == 1
    assert summary["scanned_entries"] == summary["scan_limit"] == 3
    assert summary["scan_truncated"] is True
    assert summary["candidate_files"] == 3
    assert summary["files_read"] == 1
    assert summary["unread_candidate_files"] == 2


def test_untruncated_scan_counts_known_files_excluded_by_summary_limit(tmp_path, valid_trace):
    _path, record = valid_trace
    (tmp_path / "trace_copy.json").write_text(json.dumps(record), encoding="utf-8")
    summary = runtime_trace.load_trace_summary(trace_dir=tmp_path, limit=1)
    assert summary["scan_truncated"] is False
    assert summary["candidate_files"] == 2
    assert summary["files_read"] == summary["unread_candidate_files"] == 1


def test_unreadable_directory_scan_is_observable_without_leaking_details(tmp_path, monkeypatch):
    def fail_scan(_directory):
        raise PermissionError("private server path")

    monkeypatch.setattr(runtime_trace.os, "scandir", fail_scan)
    summary = runtime_trace.load_trace_summary(trace_dir=tmp_path)
    assert summary["traces"] == 0
    assert summary["scan_errors"] == 1
    assert summary["scan_truncated"] is True
    assert "private server path" not in json.dumps(summary)


def test_trace_disappearing_during_scan_does_not_break_other_records(tmp_path, valid_trace, monkeypatch):
    original_scandir = runtime_trace.os.scandir

    class MissingEntry:
        name = "trace_disappeared.json"

        def stat(self, *, follow_symlinks):
            raise FileNotFoundError("private server path")

    @contextmanager
    def interrupted_scan(directory):
        with original_scandir(directory) as entries:
            yield iter([MissingEntry(), *entries])

    monkeypatch.setattr(runtime_trace.os, "scandir", interrupted_scan)
    summary = runtime_trace.load_trace_summary(trace_dir=tmp_path)
    assert summary["traces"] == 1
    assert summary["invalid_files"] == summary["scan_errors"] == 1
    assert "private server path" not in json.dumps(summary)
