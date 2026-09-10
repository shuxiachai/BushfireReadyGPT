import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src import file_lock
from src.file_lock import _windows_wait_result_is_running


def test_windows_process_wait_results_are_interpreted_conservatively():
    assert _windows_wait_result_is_running(0) is False
    assert _windows_wait_result_is_running(258) is True
    assert _windows_wait_result_is_running(0xFFFFFFFF) is True
    assert _windows_wait_result_is_running(12345) is True


def _old_record(tmp_path, owner):
    path = tmp_path / "test.lock"
    path.write_text(json.dumps(owner), encoding="ascii")
    os.utime(path, (time.time() - 600, time.time() - 600))
    return path


def _incarnation(namespace="pid:[100]", start=100, boot="boot-a"):
    return {"boot_id": boot, "pid_namespace": namespace, "start_ticks": start}


def test_linux_proc_identity_handles_spaces_and_parentheses_in_process_name(tmp_path, monkeypatch):
    monkeypatch.setattr(file_lock.sys, "platform", "linux")
    monkeypatch.setattr(file_lock, "_PROC_ROOT", tmp_path)
    boot_path = tmp_path / "sys/kernel/random/boot_id"
    boot_path.parent.mkdir(parents=True)
    boot_path.write_text("boot-a\n", encoding="ascii")
    process_path = tmp_path / "42"
    process_path.mkdir()
    fields = ["S"] + ["0"] * 18 + ["123456", "999"]
    (process_path / "stat").write_text("42 (a b) c)) " + " ".join(fields), encoding="ascii")
    monkeypatch.setattr(file_lock.os, "readlink", lambda _path: "pid:[100]")

    assert file_lock._linux_process_incarnation(42) == _incarnation(start=123456)


@pytest.mark.parametrize(
    ("recorded", "observed", "expected"),
    [
        (_incarnation(), _incarnation(), False),
        (_incarnation(start=50), _incarnation(), True),
        (_incarnation(namespace="pid:[200]"), _incarnation(), False),
        (_incarnation(boot="other-host"), _incarnation(), False),
        ({"boot_id": "boot-a"}, _incarnation(), False),
        (_incarnation(), None, False),
    ],
)
def test_incarnation_checks_never_confuse_another_namespace_with_a_dead_pid(
    tmp_path, monkeypatch, recorded, observed, expected
):
    lock = _old_record(tmp_path, {"pid": 42, "token": "original", "incarnation": recorded})
    monkeypatch.setattr(file_lock, "_linux_process_incarnation", lambda _pid: observed)

    assert file_lock.lock_can_be_reclaimed(lock, 300, is_process_running=lambda _pid: True) is expected


def test_guarded_record_requires_shared_kernel_guard_even_when_local_pid_is_dead(tmp_path):
    lock = _old_record(
        tmp_path,
        {"pid": 42, "token": "original", "kernel_guard": "flock-v1", "incarnation": _incarnation()},
    )

    assert not file_lock.lock_can_be_reclaimed(lock, 300, is_process_running=lambda _pid: False)
    assert file_lock.lock_can_be_reclaimed(lock, 300, kernel_guarded=True)


def test_guarded_crash_record_recovers_immediately_despite_pid_reuse(tmp_path):
    lock = tmp_path / "test.lock"
    lock.write_text(
        json.dumps({"pid": os.getpid(), "token": "old-container", "kernel_guard": "flock-v1"}), encoding="ascii"
    )

    assert file_lock.lock_can_be_reclaimed(lock, 3600, kernel_guarded=True)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux kernel flock")
def test_kernel_guard_serialises_same_process_independent_descriptors(tmp_path):
    lock_path = tmp_path / "test.lock"
    with file_lock.kernel_lock_guard(lock_path, 0) as guarded:
        assert guarded
        with pytest.raises(file_lock.LockGuardTimeout):
            with file_lock.kernel_lock_guard(lock_path, 0):
                pytest.fail("a second critical section acquired the live owner's kernel guard")
    assert Path(str(lock_path) + ".guard").is_file()
    with file_lock.kernel_lock_guard(lock_path, 0):
        pass


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux kernel flock")
def test_real_crashed_process_guard_is_released_and_record_can_be_recovered(tmp_path):
    lock_path = tmp_path / "test.lock"
    script = """
import json, os, sys
from pathlib import Path
from src.file_lock import kernel_lock_guard, make_lock_owner
lock_path = Path(sys.argv[1])
with kernel_lock_guard(lock_path, 0) as guarded:
    lock_path.write_text(json.dumps(make_lock_owner('crashed', kernel_guarded=guarded)), encoding='ascii')
    os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(lock_path)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        timeout=10,
    )
    with file_lock.kernel_lock_guard(lock_path, 0) as guarded:
        assert file_lock.lock_can_be_reclaimed(lock_path, 3600, kernel_guarded=guarded)
