# -*- coding: utf-8 -*-
"""Small OS ownership primitives for plugin workers."""

from __future__ import annotations

import ctypes
import os
import signal
import threading
from contextlib import ExitStack
from ctypes import wintypes as w
from typing import Any


class _JobBasicLimits(ctypes.Structure):
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


class _JobExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _JobBasicLimits),
        ("io", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


class ProcessTree:
    """Own a POSIX session or a host-held Windows kill-on-close job."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._job: Any = None
        self._kernel: Any = None
        if os.name == "nt":
            self._create_job()

    def _create_job(self) -> None:
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
            (
                "IsProcessInJob",
                [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)],
                w.BOOL,
            ),
            ("TerminateJobObject", [w.HANDLE, w.UINT], w.BOOL),
            (
                "QueryInformationJobObject",
                [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID],
                w.BOOL,
            ),
            ("WaitForSingleObject", [w.HANDLE, w.DWORD], w.DWORD),
            ("CloseHandle", [w.HANDLE], w.BOOL),
        ):
            function = getattr(kernel, name)
            function.argtypes = args
            function.restype = result
        job = kernel.CreateJobObjectW(None, None)
        process = kernel.OpenProcess(0x0101, False, self.pid)
        try:
            if (
                not job
                or not process
                or not self._set_job_limits(kernel, job)
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

    @staticmethod
    def _set_job_limits(kernel, job, *, stop_admission: bool = False) -> bool:
        limits = _JobExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if stop_admission:
            limits.basic.flags |= 0x0008  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            limits.basic.active_limit = 0
        return bool(
            kernel.SetInformationJobObject(
                job,
                9,  # JobObjectExtendedLimitInformation
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ),
        )

    def _job_process_ids(self) -> list[int]:
        # JOBOBJECT_BASIC_PROCESS_ID_LIST: two DWORDs, then ULONG_PTR IDs.
        header_size = ctypes.sizeof(ctypes.c_uint32 * 2)
        capacity = 16
        while True:
            data = ctypes.create_string_buffer(
                header_size + capacity * ctypes.sizeof(ctypes.c_size_t),
            )
            if self._kernel.QueryInformationJobObject(
                self._job,
                3,  # JobObjectBasicProcessIdList
                data,
                ctypes.sizeof(data),
                None,
            ):
                assigned, count = (ctypes.c_uint32 * 2).from_buffer(data)
                if count >= assigned:
                    pid_array = ctypes.c_size_t * count
                    return list(pid_array.from_buffer(data, header_size))
            elif (error := ctypes.get_last_error()) != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(error)
            capacity *= 2

    def terminate_and_wait(self) -> None:
        """Stop a Windows job and confirm the exit of its processes."""
        kernel, job = self._kernel, self._job
        with ExitStack() as handles:
            owned = []
            try:
                # Block new members before taking the snapshot. Termination
                # can remove PIDs from the job before their handles signal.
                if not self._set_job_limits(kernel, job, stop_admission=True):
                    raise ctypes.WinError(ctypes.get_last_error())
                for pid in self._job_process_ids():
                    # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
                    process = kernel.OpenProcess(0x00101000, False, pid)
                    if not process:
                        error = ctypes.get_last_error()
                        if error == 87:  # ERROR_INVALID_PARAMETER: PID gone
                            continue
                        raise ctypes.WinError(error)
                    handles.callback(kernel.CloseHandle, process)
                    in_job = w.BOOL()
                    if not kernel.IsProcessInJob(
                        process,
                        job,
                        ctypes.byref(in_job),
                    ):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if in_job.value:
                        owned.append(process)
            finally:
                self.signal(force=True)
            for process in owned:
                if kernel.WaitForSingleObject(process, 0xFFFFFFFF) != 0:
                    raise ctypes.WinError(ctypes.get_last_error())

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
    if os.name == "nt":
        _watch_windows_parent(parent_pid)
        return

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


def _watch_windows_parent(parent_pid: int) -> None:
    """Watch the host process, which may sit above a venv redirector."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, args, result in (
        ("OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        ("WaitForSingleObject", [w.HANDLE, w.DWORD], w.DWORD),
        ("CloseHandle", [w.HANDLE], w.BOOL),
    ):
        function = getattr(kernel, name)
        function.argtypes = args
        function.restype = result
    process = kernel.OpenProcess(0x00100000, False, parent_pid)  # SYNCHRONIZE
    if not process:
        error = ctypes.get_last_error()
        os.write(2, f"PARENT_WATCH_UNAVAILABLE: winerror={error}\n".encode())
        raise ctypes.WinError(error)

    def watch() -> None:
        try:
            result = kernel.WaitForSingleObject(process, 0xFFFFFFFF)
            if result != 0:  # WAIT_OBJECT_0 is the only successful outcome.
                error = ctypes.get_last_error()
                os.write(
                    2,
                    (
                        f"PARENT_WATCH_FAILED: result={result} "
                        f"winerror={error}\n"
                    ).encode(),
                )
        finally:
            # Close before _exit: it does not run Python finally blocks.
            kernel.CloseHandle(process)
            os._exit(71)  # pylint: disable=protected-access

    try:
        threading.Thread(
            target=watch,
            daemon=True,
            name="plugin-parent-watch",
        ).start()
    except BaseException:
        kernel.CloseHandle(process)
        raise
