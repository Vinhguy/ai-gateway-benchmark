from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION = 15
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
_JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x00000004
_ACTIVE_HANDLES: list[int] = []


class _BasicLimitInformation(ctypes.Structure):
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


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _CpuRateControlInformation(ctypes.Structure):
    _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]


def cpu_rate_for_cores(cpu_cores: int, logical_processors: int | None = None) -> int:
    logical_processors = logical_processors or os.cpu_count() or 1
    if cpu_cores < 1:
        raise ValueError("cpu_cores must be positive")
    return min(10000, max(1, (10000 * cpu_cores) // logical_processors))


def apply_current_process_limits(memory_gb: int, cpu_cores: int) -> dict[str, int]:
    """Attach this process to a Windows Job Object with hard RAM and CPU caps."""
    if os.name != "nt":
        raise OSError("Windows Job Objects are available only on Windows")
    if memory_gb < 1:
        raise ValueError("memory_gb must be at least 1")
    if cpu_cores < 1:
        raise ValueError("cpu_cores must be positive")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle_type = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = handle_type
    kernel32.SetInformationJobObject.argtypes = [
        handle_type,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [handle_type, handle_type]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = handle_type
    kernel32.CloseHandle.argtypes = [handle_type]
    kernel32.CloseHandle.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())

    memory_bytes = memory_gb * 1024**3
    limits = _ExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = (
        _JOB_OBJECT_LIMIT_PROCESS_MEMORY | _JOB_OBJECT_LIMIT_JOB_MEMORY
    )
    limits.ProcessMemoryLimit = memory_bytes
    limits.JobMemoryLimit = memory_bytes
    if not kernel32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)

    cpu = _CpuRateControlInformation()
    cpu.ControlFlags = _JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | _JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
    cpu.CpuRate = cpu_rate_for_cores(cpu_cores)
    if not kernel32.SetInformationJobObject(
        job,
        _JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION,
        ctypes.byref(cpu),
        ctypes.sizeof(cpu),
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)

    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)

    _ACTIVE_HANDLES.append(job)
    return {"memory_limit_bytes": memory_bytes, "cpu_rate_per_10000": cpu.CpuRate}
