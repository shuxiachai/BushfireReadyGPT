"""Small cross-platform helpers for PID-owned local file locks."""

import errno
import json
import math
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

MAX_LOCK_RECORD_BYTES = 4096
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_PROC_ROOT = Path("/proc")
_KERNEL_GUARD = "flock-v1"
_WINDOWS_KERNEL_GUARD = "windows-byte-lock-v1"


class LockGuardTimeout(TimeoutError):
    """The kernel guard is still held by another critical section."""


class LockGuardError(OSError):
    """The filesystem cannot provide the required kernel guard."""


def _linux_process_incarnation(pid):
    """Identify a Linux process without reading command lines or environment."""

    if not sys.platform.startswith("linux"):
        return None
    try:
        boot_id = (_PROC_ROOT / "sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        namespace = os.readlink(_PROC_ROOT / str(pid) / "ns/pid")
        stat = (_PROC_ROOT / str(pid) / "stat").read_text(encoding="ascii")
        # comm (field 2) may itself contain spaces and closing parentheses.
        fields = stat.rsplit(")", 1)[1].split()
        start_ticks = int(fields[19])  # starttime is field 22; fields starts at 3.
    except (OSError, UnicodeError, ValueError, IndexError):
        return None
    if not boot_id or not namespace or start_ticks < 0:
        return None
    return {"boot_id": boot_id, "pid_namespace": namespace, "start_ticks": start_ticks}


def make_lock_owner(token, *, kernel_guarded=False):
    """Create a backwards-readable owner with optional Linux incarnation proof."""

    owner = {"pid": os.getpid(), "token": token}
    incarnation = _linux_process_incarnation(owner["pid"])
    if incarnation is not None:
        owner["incarnation"] = incarnation
    if kernel_guarded:
        owner["kernel_guard"] = _kernel_guard_protocol()
    return owner


def _kernel_guard_protocol():
    if sys.platform.startswith("linux"):
        return _KERNEL_GUARD
    if os.name == "nt":
        return _WINDOWS_KERNEL_GUARD
    return None


@contextmanager
def kernel_lock_guard(lock_path, timeout_seconds):
    """Hold a stable native lock for recovery and the entire critical section.

    The sidecar inode must never be unlinked: a fixed inode serialises recovery
    and ownership across PID namespaces, including overlapping container starts.
    Kernel locks are released on process exit, even after an unclean shutdown.
    Windows locks byte zero of the same persistent sidecar. Never unlink this
    file: doing so would let contenders lock different filesystem objects.
    """

    protocol = _kernel_guard_protocol()
    if protocol is None:
        yield False
        return
    try:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError
        timeout_seconds = float(timeout_seconds)
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError
    except (ValueError, OverflowError) as error:
        raise LockGuardError("The kernel lock timeout must be finite and non-negative.") from error
    if protocol == _KERNEL_GUARD:
        import fcntl

        def acquire(descriptor):
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    else:
        import msvcrt

        def acquire(descriptor):
            # Windows supports locking ranges beyond EOF; no sidecar rewrite
            # is needed, including for a newly created empty file.
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)

    guard_path = Path(str(lock_path) + ".guard")
    deadline = time.monotonic() + timeout_seconds
    try:
        descriptor = os.open(guard_path, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError as error:
        raise LockGuardError("The kernel lock sidecar could not be opened.") from error
    try:
        while True:
            try:
                acquire(descriptor)
                break
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise LockGuardError("The filesystem could not acquire the kernel file lock.") from error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LockGuardTimeout("Timed out waiting for the kernel file lock.") from error
                time.sleep(min(0.05, remaining))
        yield True
    finally:
        os.close(descriptor)


def read_lock_owner(lock_path):
    """Return a validated ``pid``/``token`` lock record, or ``None``."""

    lock_path = Path(lock_path)
    try:
        if lock_path.stat().st_size > MAX_LOCK_RECORD_BYTES:
            return None
        # The record may grow or be replaced after stat; never read it unbounded.
        with lock_path.open("rb") as file:
            raw = file.read(MAX_LOCK_RECORD_BYTES + 1)
        if len(raw) > MAX_LOCK_RECORD_BYTES:
            return None
        payload = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        return None
    if (
        not isinstance(payload, dict)
        or type(payload.get("pid")) is not int
        or payload["pid"] < 1
        or not isinstance(payload.get("token"), str)
        or not payload["token"]
    ):
        return None
    owner = {"pid": payload["pid"], "token": payload["token"]}
    for field in ("incarnation", "kernel_guard"):
        if field in payload:
            owner[field] = payload[field]
    return owner


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


def lock_can_be_reclaimed(lock_path, stale_seconds, *, is_process_running=process_is_running, kernel_guarded=False):
    """Allow recovery only after the initialisation window has safely elapsed.

    A held kernel guard proves a prior guarded owner released its critical
    section, independent of PID reuse and container PID namespaces. Unguarded
    records require the original conservative age and process checks. Unknown
    namespaces must never be checked against an unrelated local process ID.
    """

    lock_path = Path(lock_path)
    owner = read_lock_owner(lock_path)
    if (
        owner is not None
        and owner.get("kernel_guard") is not None
        and owner.get("kernel_guard") == _kernel_guard_protocol()
    ):
        # A different namespace can still contain a live owner. Only acquiring
        # the same kernel guard proves its critical section has ended.
        return kernel_guarded
    if owner is not None and "kernel_guard" in owner:
        return False
    try:
        old_enough = time.time() - lock_path.stat().st_mtime > stale_seconds
    except OSError:
        return False
    if not old_enough:
        return False
    if owner is None:
        return True
    if "incarnation" not in owner:
        return not is_process_running(owner["pid"])
    return _incarnation_confirmed_dead(owner, is_process_running)


def _incarnation_confirmed_dead(owner, is_process_running):
    recorded = owner["incarnation"]
    current = _linux_process_incarnation(os.getpid())
    if (
        not isinstance(recorded, dict)
        or not isinstance(recorded.get("boot_id"), str)
        or not recorded.get("boot_id")
        or not isinstance(recorded.get("pid_namespace"), str)
        or not recorded.get("pid_namespace")
        or type(recorded.get("start_ticks")) is not int
        or recorded["start_ticks"] < 0
        or current is None
    ):
        return False
    if recorded["boot_id"] != current["boot_id"]:
        # Without the shared guard, a different host may still own this volume.
        return False
    if recorded["pid_namespace"] != current["pid_namespace"]:
        return False
    observed = _linux_process_incarnation(owner["pid"])
    if observed is not None:
        return observed != recorded
    return not is_process_running(owner["pid"])
