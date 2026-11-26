# -*- coding: utf-8 -*-
"""Blocking local I/O and bounded native process shutdown."""

import asyncio
import logging
import os
import signal
import subprocess
import sys

logger = logging.getLogger(__name__)

if sys.platform.startswith("linux"):
    import ctypes

    # Resolve prctl once, in the parent. Doing the attribute lookup inside the
    # child costs several times more under load: at 96 busy threads the
    # per-fork worst case went from 0.008s to 0.126s with the lookup and came
    # back to 0.016s when the pointer was taken up front.
    _LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
    _PRCTL = _LIBC.prctl
    _PR_SET_PDEATHSIG = 1

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _JobBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JobIoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JobExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobBasicLimitInformation),
            ("IoInfo", _JobIoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


# Keep the actual waits and the provider's enclosing deadline on one policy.
# Downloads stop their process before joining the monitor; server shutdown
# has a separate graceful-exit and forced-exit phase.
DOWNLOAD_PROCESS_WAIT_SECONDS = 2.0
DOWNLOAD_MONITOR_WAIT_SECONDS = 2.0
SERVER_GRACE_SECONDS = 5.0
SERVER_KILL_SECONDS = 3.0
DOWNLOAD_CLOSE_SECONDS = (
    2 * DOWNLOAD_PROCESS_WAIT_SECONDS + DOWNLOAD_MONITOR_WAIT_SECONDS
)
SERVER_CLOSE_SECONDS = SERVER_GRACE_SECONDS + SERVER_KILL_SECONDS
# Independent stops run concurrently. Reserve another 2s for executor handoff,
# log-task cancellation and final bookkeeping; slow I/O still hits this guard
# and leaves ownership intact for a retry rather than claiming quiescence.
PROVIDER_CLOSE_SECONDS = (
    max(DOWNLOAD_CLOSE_SECONDS, SERVER_CLOSE_SECONDS) + 2.0
)


async def finish(operation):
    """Wait for completion before propagating caller cancellation."""
    task = asyncio.ensure_future(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            if not cancelled:
                raise
            break
    if cancelled:
        try:
            task.result()
        except BaseException:
            pass
        raise asyncio.CancelledError
    return task.result()


async def run_io(operation, *args, **kwargs):
    return await finish(asyncio.to_thread(operation, *args, **kwargs))


class ServerJob:
    """Keep llama-server from outliving this process.

    The server is started with ``CREATE_NO_WINDOW`` alone — no new process
    group and no job — so a crash or a forced kill of the provider tells the
    server nothing: it keeps its port and its memory, and the next start
    launches another one. A few restarts are enough to exhaust RAM (#8830).

    A job with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` hands that decision to
    the kernel: when this process's last job handle goes away — on any exit
    path, ``TerminateProcess`` included — every member is terminated. One job
    per backend: the handle is released once a stop succeeds, and the next
    start creates a fresh one, so a start/reload cycle cannot pile them up.

    POSIX is a no-op here: ``start_new_session`` gives the server its own
    process group, ``stop_server`` signals that group, and on Linux the child
    also arms ``PR_SET_PDEATHSIG`` so a ``SIGKILL`` of the provider takes it
    down. macOS has neither, so a hard kill of the provider there still
    orphans the server.
    """

    def __init__(self) -> None:
        self._handle = None

    def assign(self, process: subprocess.Popen) -> None:
        """Put *process* in the job, creating the job on first use."""
        if os.name != "nt":
            return
        # A real Popen carries the handle; test doubles and exotic launchers
        # may not, and a missing handle is not worth failing a start over.
        handle = getattr(process, "_handle", None)
        if handle is None:
            logger.debug(
                "No process handle on %r; the server job is skipped",
                process,
            )
            return
        if self._handle is None and not self._create():
            return
        if not _KERNEL32.AssignProcessToJobObject(
            self._handle,
            wintypes.HANDLE(int(handle)),
        ):
            logger.warning(
                "Could not put llama-server (pid %s) in its job; it may outlive "
                "a crash: %s",
                process.pid,
                ctypes.get_last_error(),
            )

    def close(self) -> None:
        """Close the job. On Windows this terminates every member."""
        if self._handle is None:
            return
        _KERNEL32.CloseHandle(self._handle)
        self._handle = None

    def _create(self) -> bool:
        handle = _KERNEL32.CreateJobObjectW(None, None)
        if not handle:
            logger.warning(
                "Could not create a job for llama-server; it may outlive a "
                "crash: %s",
                ctypes.get_last_error(),
            )
            return False
        info = _JobExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not _KERNEL32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            logger.warning(
                "Could not make the llama-server job kill-on-close; it may "
                "outlive a crash: %s",
                ctypes.get_last_error(),
            )
            _KERNEL32.CloseHandle(handle)
            return False
        self._handle = handle
        return True


def create_server_job() -> ServerJob:
    """Return the job that binds llama-server's lifetime to this process."""
    return ServerJob()


if sys.platform.startswith("linux"):

    def _make_pdeathsig_hook(parent_pid: int):
        """Build the hook that binds this child's lifetime to *parent_pid*.

        Runs between fork and exec, so it stays to what cannot deadlock:
        threads that held locks at fork time are not in this process, and
        anything fancy here is how the documented ``preexec_fn`` deadlock
        starts. That is two kernel calls, not one — arm the signal, then read
        the parent — and the order matters. Arming first means a provider dying
        in between is still covered: the signal is already in place, and the
        pid read that follows sees the change and exits on the spot instead of
        running with a parent that will never be signalled.

        The pid compared against is the one captured before ``Popen``, not
        ``1``. ``1`` only means "orphaned" when the original parent died: a
        provider that is itself PID 1 (containers, some init setups) would make
        every child exit instantly, and a provider killed before the child
        armed its signal leaves the child adopted by some *other* supervisor,
        whose pid is not 1 — that child would run on unsupervised.
        """

        def _die_with_parent() -> None:
            _PRCTL(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
            if os.getppid() != parent_pid:
                os._exit(1)

        return _die_with_parent

    _PDEATHSIG_FACTORY = _make_pdeathsig_hook
else:
    _PDEATHSIG_FACTORY = None


def process_options():
    """Bind the child's lifetime to ours and hide consoles where needed.

    Windows: a kill-on-close job object (see ServerJob) plus no console.
    Linux: PR_SET_PDEATHSIG, since a SIGKILL of the provider skips every
    cleanup path we have. macOS has no such knob, so it stays a no-op there
    and relies on start_new_session + the process-group signal.
    """
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    options = {"start_new_session": True}
    if _PDEATHSIG_FACTORY is not None:
        # ``getpid`` here runs in the provider, before the fork, so the hook
        # compares against the pid the child is actually supposed to have.
        options["preexec_fn"] = _PDEATHSIG_FACTORY(os.getpid())
    return options


def stop_server(
    process,
    graceful_timeout=SERVER_GRACE_SECONDS,
    kill_timeout=SERVER_KILL_SECONDS,
):
    """Reap the server, retaining ownership if bounded shutdown fails."""
    for sig, timeout in (
        (signal.SIGTERM, graceful_timeout),
        (signal.SIGKILL if os.name != "nt" else None, kill_timeout),
    ):
        if process.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(process.pid), sig)
            elif sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass
    raise RuntimeError("llama.cpp did not exit")


def stop_download(
    process,
    graceful_timeout=DOWNLOAD_PROCESS_WAIT_SECONDS,
    kill_timeout=DOWNLOAD_PROCESS_WAIT_SECONDS,
):
    """Terminate and reap a multiprocessing download worker."""
    if process.is_alive():
        process.terminate()
        process.join(timeout=graceful_timeout)
    if process.is_alive():
        process.kill()
        process.join(timeout=kill_timeout)
    if process.is_alive():
        raise RuntimeError("Download worker did not exit")
    process.join(timeout=0)
