import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src import audit


def _lock_path(audit_dir, report_id="lock-test"):
    return audit_dir / f".lock_{audit._slugify(report_id)}.lock"


def _make_old(lock_path):
    old_timestamp = time.time() - audit.AUDIT_LOCK_STALE_SECONDS - 60
    os.utime(lock_path, (old_timestamp, old_timestamp))


def test_old_audit_lock_owned_by_a_running_process_is_not_reclaimed(tmp_path):
    lock_path = _lock_path(tmp_path)
    owner = {"pid": os.getpid(), "token": "still-active"}
    lock_path.write_text(json.dumps(owner), encoding="ascii")
    _make_old(lock_path)

    with pytest.raises(audit.AuditIntegrityError, match="Timed out"):
        with audit._report_lock(tmp_path, "lock-test", timeout_seconds=0):
            pass

    assert json.loads(lock_path.read_text(encoding="ascii")) == owner


def test_audit_lock_release_only_removes_its_own_token(tmp_path):
    lock_path = _lock_path(tmp_path)
    successor = {"pid": os.getpid(), "token": "successor-owner"}

    with audit._report_lock(tmp_path, "lock-test"):
        current = json.loads(lock_path.read_text(encoding="ascii"))
        assert current["token"] != successor["token"]
        lock_path.write_text(json.dumps(successor), encoding="ascii")

    assert json.loads(lock_path.read_text(encoding="ascii")) == successor


def test_audit_lock_release_retries_transient_windows_style_unlink_failure(tmp_path, monkeypatch):
    lock_path = _lock_path(tmp_path)
    original_unlink = Path.unlink
    attempts = 0

    def flaky_unlink(path, *args, **kwargs):
        nonlocal attempts
        if path == lock_path:
            attempts += 1
            if attempts < 3:
                raise PermissionError("simulated transient scanner hold")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    monkeypatch.setattr(audit.time, "sleep", lambda _seconds: None)

    with audit._report_lock(tmp_path, "lock-test"):
        assert lock_path.exists()

    assert attempts == 3
    assert not lock_path.exists()


def test_audit_lock_release_failure_is_not_silently_ignored(tmp_path, monkeypatch):
    lock_path = _lock_path(tmp_path)
    original_unlink = Path.unlink

    def blocked_unlink(path, *args, **kwargs):
        if path == lock_path:
            raise PermissionError("simulated persistent scanner hold")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked_unlink)
    monkeypatch.setattr(audit.time, "sleep", lambda _seconds: None)

    with pytest.raises(audit.AuditIntegrityError, match="could not be released"):
        with audit._report_lock(tmp_path, "lock-test"):
            pass

    assert lock_path.exists()


def test_old_audit_lock_is_reclaimed_only_after_owner_is_confirmed_dead(tmp_path, monkeypatch):
    lock_path = _lock_path(tmp_path)
    lock_path.write_text(json.dumps({"pid": 424242, "token": "dead-owner"}), encoding="ascii")
    _make_old(lock_path)
    monkeypatch.setattr(audit, "_process_is_running", lambda _pid: False)

    with audit._report_lock(tmp_path, "lock-test", timeout_seconds=0):
        owner = json.loads(lock_path.read_text(encoding="ascii"))
        assert owner["token"] != "dead-owner"

    assert not lock_path.exists()


def test_real_subprocess_keeps_its_old_audit_lock(tmp_path):
    report_id = "real-process"
    lock_path = _lock_path(tmp_path, report_id)
    ready_path = tmp_path / "owner.ready"
    release_path = tmp_path / "owner.release"
    project_root = Path(__file__).resolve().parents[1]
    script = """
import sys
import time
from pathlib import Path
from src import audit

audit_dir = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
release_path = Path(sys.argv[3])
with audit._report_lock(audit_dir, "real-process", timeout_seconds=2):
    ready_path.write_text("ready", encoding="ascii")
    while not release_path.exists():
        time.sleep(0.02)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), str(ready_path), str(release_path)],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    error = None
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not ready_path.exists():
            stdout, stderr = process.communicate(timeout=2)
            pytest.fail(f"lock owner process did not become ready: {stdout} {stderr}")

        owner = json.loads(lock_path.read_text(encoding="ascii"))
        # A Windows virtual-environment launcher may wait on a different runtime PID.
        assert audit._process_is_running(owner["pid"])
        _make_old(lock_path)

        with pytest.raises(audit.AuditIntegrityError, match="Timed out"):
            with audit._report_lock(tmp_path, report_id, timeout_seconds=0):
                pass
        assert json.loads(lock_path.read_text(encoding="ascii"))["token"] == owner["token"]
    except BaseException as captured:
        error = captured
    finally:
        release_path.touch()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            if error is None:
                error = AssertionError(f"lock owner process did not stop: {stdout} {stderr}")
    if error is not None:
        raise error
    assert process.returncode == 0, stderr
    assert not lock_path.exists()


def test_audit_directory_uses_runtime_root_with_explicit_override_precedence(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_DIR", audit._DEFAULT_AUDIT_DIR)
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    assert audit._audit_dir() == (tmp_path / "runtime" / "audit").resolve()

    monkeypatch.setenv("BUSHFIRE_AUDIT_DIR", str(tmp_path / "explicit"))
    assert audit._audit_dir() == (tmp_path / "explicit").resolve()


def test_audit_directory_keeps_test_override_compatible(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path / "overridden")
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    assert audit._audit_dir() == (tmp_path / "overridden").resolve()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux kernel flock")
def test_audit_recovers_fresh_lock_after_process_crash_without_waiting_for_staleness(tmp_path):
    script = """
import os, sys
from src import audit
with audit._report_lock(sys.argv[1], 'crashed-report', timeout_seconds=0):
    os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        timeout=10,
    )
    lock_path = _lock_path(tmp_path, "crashed-report")
    previous = json.loads(lock_path.read_text(encoding="ascii"))
    assert previous["kernel_guard"] == "flock-v1"
    # Simulate the PID 1 reuse seen on restart; the shared guard remains the
    # authority because the old namespace may no longer be visible locally.
    previous["pid"] = os.getpid()
    lock_path.write_text(json.dumps(previous), encoding="ascii")

    with audit._report_lock(tmp_path, "crashed-report", timeout_seconds=0):
        replacement = json.loads(lock_path.read_text(encoding="ascii"))
        assert replacement["token"] != previous["token"]
    assert not lock_path.exists()


def test_audit_lock_does_not_relabel_timeout_from_critical_section(tmp_path):
    with pytest.raises(TimeoutError, match="report operation failed"):
        with audit._report_lock(tmp_path, "body-error", timeout_seconds=0):
            raise TimeoutError("report operation failed")
    assert not _lock_path(tmp_path, "body-error").exists()
