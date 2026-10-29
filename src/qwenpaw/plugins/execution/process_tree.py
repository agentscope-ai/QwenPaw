# -*- coding: utf-8 -*-
"""Small OS ownership primitives for plugin workers."""

from __future__ import annotations

import ctypes
import os
import signal
import threading
from typing import Any


class ProcessTree:
    """Own a POSIX session or a host-held Windows kill-on-close job."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._job: Any = None
        self._kernel: Any = None
        if os.name == "nt":
            self._create_job()

    def _create_job(self) -> None:
        from ctypes import (
            wintypes as w,
        )  # pylint: disable=import-outside-toplevel

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", w.DWORD),
                ("min_ws", ctypes.c_size_t),
                ("max_ws", ctypes.c_size_t),
                ("active_limit", w.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", w.DWORD),
                ("scheduling", w.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, args, result in (
            ("CreateJobObjectW", [w.LPVOID, w.LPCWSTR], w.HANDLE),
            ("OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            (
                "SetInformationJobObject",
                [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD],
                w.BOOL,
            ),
            ("AssignProcessToJobObject", [w.HANDLE, w.HANDLE], w.BOOL),
            ("TerminateJobObject", [w.HANDLE, w.UINT], w.BOOL),
            (
                "QueryInformationJobObject",
                [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID],
                w.BOOL,
            ),
            ("CloseHandle", [w.HANDLE], w.BOOL),
        ):
            function = getattr(kernel, name)
            function.argtypes = args
            function.restype = result
        job = kernel.CreateJobObjectW(None, None)
        process = kernel.OpenProcess(0x0101, False, self.pid)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if (
                not job
                or not process
                or not kernel.SetInformationJobObject(
                    job,
                    9,
                    ctypes.byref(limits),
                    ctypes.sizeof(limits),
                )
                or not kernel.AssignProcessToJobObject(job, process)
            ):
                raise OSError("PROCESS_TREE_UNAVAILABLE")
        except BaseException:
            if job:
                kernel.CloseHandle(job)
            raise
        finally:
            if process:
                kernel.CloseHandle(process)
        self._kernel, self._job = kernel, job

    def signal(self, *, force: bool) -> None:
        """Signal all owned members, including after the leader exits."""
        if self._job is not None:
            if not self._kernel.TerminateJobObject(self._job, 1):
                raise OSError("PROCESS_TREE_TERMINATE_FAILED")
        else:
            try:
                os.killpg(
                    self.pid,
                    signal.SIGKILL if force else signal.SIGTERM,
                )
            except ProcessLookupError:
                pass

    def alive(self) -> bool:
        """Return whether the owned tree still has members."""
        if self._job is not None:
            # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: four LARGE_INTEGERs,
            # then page faults, total processes, active processes, terminated.
            data = (ctypes.c_uint32 * 12)()
            if not self._kernel.QueryInformationJobObject(
                self._job,
                1,
                ctypes.byref(data),
                ctypes.sizeof(data),
                None,
            ):
                return True  # Unconfirmed cleanup must retain the Job.
            return bool(data[10])
        try:
            os.killpg(self.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def close(self) -> None:
        """Release a confirmed-empty Windows job."""
        if self._job is not None:
            self._kernel.CloseHandle(self._job)
            self._job = None


def watch_parent(parent_pid: int) -> None:
    """Arm a daemon before imports; Windows host job adds OS-backed death."""

    def watch() -> None:
        while True:
            if os.getppid() != parent_pid:
                if os.name != "nt":
                    os.killpg(os.getpid(), signal.SIGKILL)
                os._exit(71)  # pylint: disable=protected-access
            threading.Event().wait(0.1)

    threading.Thread(
        target=watch,
        daemon=True,
        name="plugin-parent-watch",
    ).start()
