"""Small cross-platform helpers for PID-owned local file locks."""

import json
import os
import time
from pathlib import Path

MAX_LOCK_RECORD_BYTES = 4096
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258


def read_lock_owner(lock_path):
    """Return a validated ``pid``/``token`` lock record, or ``None``."""

    lock_path = Path(lock_path)
    try:
        if lock_path.stat().st_size > MAX_LOCK_RECORD_BYTES:
            return None
        payload = json.loads(lock_path.read_text(encoding="ascii"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or type(payload.get("pid")) is not int
        or payload["pid"] < 1
        or not isinstance(payload.get("token"), str)
        or not payload["token"]
    ):
        return None
    return {"pid": payload["pid"], "token": payload["token"]}


def process_is_running(pid):
    """Conservatively report whether a process is still alive on Windows or POSIX."""

    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
            kernel32.WaitForSingleObject.restype = ctypes.c_ulong
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(0x00100000, False, pid)
            if not handle:
                # ERROR_INVALID_PARAMETER means that no process has this PID.
                return ctypes.get_last_error() != 87
            try:
                return _windows_wait_result_is_running(kernel32.WaitForSingleObject(handle, 0))
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError):
            # An inconclusive liveness check must never authorise lock deletion.
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _windows_wait_result_is_running(wait_result):
    """Treat only a signalled process handle as proof that the process exited."""

    if wait_result == _WAIT_OBJECT_0:
        return False
    # WAIT_TIMEOUT means alive; WAIT_FAILED and unknown values are inconclusive
    # and must conservatively retain the lock.
    return True


def lock_can_be_reclaimed(lock_path, stale_seconds, *, is_process_running=process_is_running):
    """Allow recovery only after the initialisation window has safely elapsed.

    A valid record is reclaimable only when its PID is confirmed dead. An invalid
    record can represent the tiny create-before-write window, so it is retained
    until it is older than the configured stale threshold.
    """

    lock_path = Path(lock_path)
    try:
        old_enough = time.time() - lock_path.stat().st_mtime > stale_seconds
    except OSError:
        return False
    if not old_enough:
        return False
    owner = read_lock_owner(lock_path)
    return owner is None or not is_process_running(owner["pid"])
