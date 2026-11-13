"""Test-only Windows jobs owned by pytest, including parent-death cleanup."""

import ctypes
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", ctypes.c_ulonglong * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def kernel32():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "OpenJobObjectW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


@contextmanager
def owned_process(command, *, python, cwd, env):
    """Close the owned job before draining pipes, on normal exit or failure."""
    api = kernel32()
    name = "Local\\WildfireGPTLauncherTest-" + uuid.uuid4().hex
    # Pytest owns the only durable handle. NULL security attributes prevent
    # inheritance, so termination of pytest also closes the last job handle.
    job = api.CreateJobObjectW(None, name)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.get_last_error()
        api.CloseHandle(job)
        raise ctypes.WinError(error)
    process = None
    try:
        process = subprocess.Popen(
            [str(python), "-B", str(Path(__file__).resolve()), name, *command],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        yield process
    finally:
        # Never wait for inherited pipes while live children still hold them.
        # A supervisor not yet assigned cannot have spawned the launcher.
        try:
            api.TerminateJobObject(job, 86)
        finally:
            api.CloseHandle(job)
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=10)


def run_owned(command, *, python, cwd, env, timeout):
    with owned_process(command, python=python, cwd=cwd, env=env) as process:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def supervise(name, command):
    api = kernel32()
    # Join before executing production code, then relinquish the supervisor's
    # temporary handle. Only pytest can keep the job alive from this point.
    job = api.OpenJobObjectW(0x0001, False, name)  # JOB_OBJECT_ASSIGN_PROCESS
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not api.AssignProcessToJobObject(job, api.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if not api.CloseHandle(job):
            raise ctypes.WinError(ctypes.get_last_error())
    result = subprocess.run(command, check=False)
    os._exit(result.returncode)


if __name__ == "__main__":
    supervise(sys.argv[1], sys.argv[2:])
