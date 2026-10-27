"""Runtime paths and child processes shared by installed and development builds."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def mcp_command() -> tuple[str, list[str]]:
    executable = str(Path(sys.executable).resolve())
    return (executable, ["--mcp"] if getattr(sys, "frozen", False)
            else ["-m", "studyforge.mcp_server"])


def background_process_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


_job_handle = None


def manage_desktop_lifetime() -> None:
    """Keep backend descendants in a Windows job and stop when the GUI exits."""
    parent = os.environ.get("STUDYFORGE_PARENT_PID")
    if os.name != "nt" or not parent:
        return
    import ctypes
    import threading
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, int(parent))
    if not handle:
        raise RuntimeError("桌面应用已退出，停止后台服务")

    def watch_parent():
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)
        os._exit(0)

    threading.Thread(target=watch_parent, daemon=True, name="desktop-parent").start()

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
    if job and kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) \
            and kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        global _job_handle
        _job_handle = job  # Retain until process exit so children are stopped together.
    elif job:
        kernel.CloseHandle(job)
