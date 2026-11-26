# -*- coding: utf-8 -*-
"""Windows named-event transport for graceful application shutdown."""

from __future__ import annotations

import os
import signal
import sys
import threading


_EVENT_MODIFY_STATE = 0x0002
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0x00000000
_EVENT_NAME_PREFIX = "Local\\QwenPawGracefulShutdown-"
_handlers_installed_pid: int | None = None


def _event_name(pid: int) -> str:
    return f"{_EVENT_NAME_PREFIX}{pid}"


def _sigbreak_to_sigint(_signum: int, _frame: object) -> None:
    """Route Windows CTRL_BREAK_EVENT through Uvicorn's graceful exit."""
    signal.raise_signal(signal.SIGINT)


def _wait_and_raise_sigint(handle: int) -> None:
    """Forward the named shutdown event to Uvicorn's SIGINT handler."""
    if wait_for_shutdown_event(handle):
        signal.raise_signal(signal.SIGINT)


def install_shutdown_handlers() -> None:
    """Install graceful shutdown handlers once in the current process."""
    global _handlers_installed_pid  # pylint: disable=global-statement

    if sys.platform != "win32":
        return

    pid = os.getpid()
    if _handlers_installed_pid == pid:
        return

    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, _sigbreak_to_sigint)

    handle = create_shutdown_event()
    if handle is not None:
        threading.Thread(
            target=_wait_and_raise_sigint,
            args=(handle,),
            daemon=True,
        ).start()
    _handlers_installed_pid = pid


def create_shutdown_event() -> int | None:
    """Create this process's named graceful-shutdown event."""
    if sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes

    create_event = ctypes.windll.kernel32.CreateEventW
    create_event.argtypes = (
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    create_event.restype = wintypes.HANDLE
    handle = create_event(None, True, False, _event_name(os.getpid()))
    return int(handle) if handle else None


def wait_for_shutdown_event(handle: int) -> bool:
    """Wait for a named event and close its handle."""
    import ctypes
    from ctypes import wintypes

    wait = ctypes.windll.kernel32.WaitForSingleObject
    wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait.restype = wintypes.DWORD
    close = ctypes.windll.kernel32.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    try:
        return wait(handle, _INFINITE) == _WAIT_OBJECT_0
    finally:
        close(handle)


def signal_shutdown_event(pid: int) -> bool:
    """Signal a QwenPaw process's named graceful-shutdown event."""
    if sys.platform != "win32":
        return False

    import ctypes
    from ctypes import wintypes

    open_event = ctypes.windll.kernel32.OpenEventW
    open_event.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    open_event.restype = wintypes.HANDLE
    set_event = ctypes.windll.kernel32.SetEvent
    set_event.argtypes = (wintypes.HANDLE,)
    set_event.restype = wintypes.BOOL
    close = ctypes.windll.kernel32.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL

    handle = open_event(_EVENT_MODIFY_STATE, False, _event_name(pid))
    if not handle:
        return False
    try:
        return bool(set_event(handle))
    finally:
        close(handle)
