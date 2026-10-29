# -*- coding: utf-8 -*-
"""Trusted stdlib-only worker bootstrap mechanics."""

from __future__ import annotations
import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import importlib
import os
from pathlib import Path
import re
import sys
import threading
from typing import Any

_THREAD_TERMINATE = 0x0001
_ERROR_NOT_FOUND = 1168
NETWORK_PROXY_ENVIRONMENT = frozenset(
    {
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    },
)
_STARTUP_ENVIRONMENT = (
    frozenset(
        {
            "COMSPEC",
            "PATH",
            "PATHEXT",
            "PROCESSOR_ARCHITECTURE",
            "PROCESSOR_ARCHITEW6432",
            "SSL_CERT_FILE",
            "SYSTEMDRIVE",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "TMPDIR",
            "USERPROFILE",
            "WINDIR",
            "QWENPAW_DEPENDENCY_MAINTENANCE",
            "QWENPAW_DEPENDENCY_STATE_DIR",
        },
    )
    | NETWORK_PROXY_ENVIRONMENT
)
_AMBIENT_IMPORT_ENVIRONMENT = frozenset({"PYTHONHOME", "PYTHONPATH"})
_PRIVATE_ENVIRONMENT_CONTROL = frozenset(
    name.upper() for name in _STARTUP_ENVIRONMENT
) | frozenset(
    {
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "__PYVENV_LAUNCHER__",
        "ENV",
        "BASH_ENV",
        "SHELLOPTS",
        "BASHOPTS",
        "CDPATH",
        "IFS",
        "NODE_OPTIONS",
        "NODE_PATH",
        "PERL5LIB",
        "PERL5OPT",
        "RUBYOPT",
        "RUBYLIB",
        "JAVA_TOOL_OPTIONS",
        "_JAVA_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "CLASSPATH",
        "GCONV_PATH",
        "GLIBC_TUNABLES",
        "LIBPATH",
        "SHLIB_PATH",
    },
)


def validate_private_environment(value: Any) -> dict[str, str]:
    """Detach bounded host launch data without authorizing import controls."""
    from collections.abc import Mapping

    def invalid():
        return BootstrapError(
            "LAUNCH_ENVIRONMENT_INVALID",
            "Invalid private launch environment",
        )

    if not isinstance(value, Mapping) or len(value) > 32:
        raise invalid() from None
    result = {}
    canonical = set()
    total = 0
    for name, item in value.items():
        if (
            not isinstance(name, str)
            or not isinstance(item, str)
            or len(name) > 128
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
            or "\0" in item
        ):
            raise invalid() from None
        key = name.upper()
        if (
            key in canonical
            or key in _PRIVATE_ENVIRONMENT_CONTROL
            or key.lstrip("_").startswith(
                (
                    "PYTHON",
                    "PYVENV",
                    "LD_",
                    "DYLD_",
                    "LDR_",
                    "QWENPAW_",
                    "COPAW_",
                    "CONDA_",
                ),
            )
        ):
            raise invalid() from None
        try:
            size = len(item.encode("utf-8"))
        except UnicodeError:
            raise invalid() from None
        total += len(name) + size + 2
        if size > 16 * 1024 or total > 64 * 1024:
            raise invalid() from None
        canonical.add(key)
        result[name] = item
    return result


class BootstrapError(RuntimeError):
    """Report a stable pre-import Runner bootstrap failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


class _ThreadPipeReader:
    """Feed a StreamReader from a blocking Windows stdin pipe."""

    def __init__(
        self,
        handle: Any,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.reader = asyncio.StreamReader()
        self._handle = handle
        self._loop = loop
        self._thread = threading.Thread(
            target=self._run,
            name="qwenpaw-protocol-reader",
            daemon=True,
        )
        self._thread.start()

    def _deliver(self, data: bytes) -> None:
        """Deliver one blocking read result on the asyncio loop."""
        if data:
            self.reader.feed_data(data)
        else:
            self.reader.feed_eof()

    def _run(self) -> None:
        """Read stdin until EOF without blocking the asyncio loop."""
        read = getattr(self._handle, "read1", None)
        if read is None:
            read = self._handle.read
        while True:
            try:
                data = read(64 * 1024)
                self._loop.call_soon_threadsafe(self._deliver, data)
            except (OSError, RuntimeError, ValueError):
                return
            if not data:
                return


class _WindowsThreadHandle:
    """Own one cancellable Win32 handle for the writer thread."""

    def __init__(self, kernel32: Any, handle: int) -> None:
        self._kernel32 = kernel32
        self._handle = handle
        self._closed = False

    def cancel(self) -> None:
        """Cancel synchronous I/O currently issued by the writer thread."""
        if self._closed:
            return
        if self._kernel32.CancelSynchronousIo(self._handle):
            return
        error = ctypes.get_last_error()
        if error != _ERROR_NOT_FOUND:
            raise OSError(error, "Unable to cancel protocol pipe write")

    def close(self) -> None:
        """Close the real Win32 thread handle exactly once."""
        if self._closed:
            return
        self._closed = True
        if not self._kernel32.CloseHandle(self._handle):
            error = ctypes.get_last_error()
            raise OSError(error, "Unable to close protocol writer thread")


def _open_windows_thread_handle() -> _WindowsThreadHandle:
    """Open the current writer thread for synchronous I/O cancellation."""
    win_dll = getattr(ctypes, "WinDLL")
    kernel32 = win_dll("kernel32", use_last_error=True)
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.OpenThread.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.CancelSynchronousIo.argtypes = [wintypes.HANDLE]
    kernel32.CancelSynchronousIo.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    thread_id = kernel32.GetCurrentThreadId()
    handle = kernel32.OpenThread(_THREAD_TERMINATE, False, thread_id)
    if not handle:
        error = ctypes.get_last_error()
        raise OSError(error, "Unable to open protocol writer thread")
    return _WindowsThreadHandle(kernel32, handle)


class _ThreadPipeWriter:
    """Adapt one synchronous pipe to the asyncio writer interface."""

    def __init__(
        self,
        handle: Any,
        *,
        thread_handle_factory: Any = None,
    ) -> None:
        self._thread_handle_factory = (
            thread_handle_factory or _open_windows_thread_handle
        )
        self._handle = handle
        self._condition = threading.Condition()
        self._request: (
            tuple[
                asyncio.AbstractEventLoop,
                asyncio.Future[None],
                bytes,
            ]
            | None
        ) = None
        self._pending_future: asyncio.Future[None] | None = None
        self._thread_handle: Any | None = None
        self._startup_error: OSError | None = None
        self._ready = threading.Event()
        self._exited = threading.Event()
        self._active = False
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="qwenpaw-protocol-writer",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()
        if self._startup_error is not None:
            self._exited.wait()
            raise self._startup_error

    @staticmethod
    def _consume_future_error(future: asyncio.Future[None]) -> None:
        """Mark an adapter failure observed even after drain cancellation."""
        if not future.cancelled():
            future.exception()

    @staticmethod
    def _complete(
        future: asyncio.Future[None],
        error: BaseException | None,
    ) -> None:
        """Complete one pipe write on its owning event loop."""
        if future.done():
            return
        if error is None:
            future.set_result(None)
        else:
            future.set_exception(error)

    def _write_all(self, data: bytes) -> None:
        """Write every byte through a possibly partial sync pipe."""
        view = memoryview(data)
        written = 0
        while written < len(view):
            with self._condition:
                if self._closed:
                    raise BrokenPipeError("protocol pipe is closed")
            count = self._handle.write(view[written:])
            if not isinstance(count, int) or count <= 0:
                raise OSError("protocol pipe write made no progress")
            if count > len(view) - written:
                raise OSError("protocol pipe write exceeded input length")
            written += count

    def _run(self) -> None:
        """Process one write at a time outside the asyncio event loop."""
        thread_handle: Any | None = None
        try:
            try:
                thread_handle = self._thread_handle_factory()
            except OSError as exc:
                self._startup_error = exc
                self._ready.set()
                return
            with self._condition:
                self._thread_handle = thread_handle
                self._ready.set()
            while True:
                with self._condition:
                    while self._request is None and not self._closed:
                        self._condition.wait()
                    if self._request is None:
                        return
                    loop, future, data = self._request
                    self._request = None
                    self._active = True
                error: BaseException | None = None
                try:
                    self._write_all(data)
                except (BrokenPipeError, ConnectionError, OSError) as exc:
                    error = exc
                with self._condition:
                    self._active = False
                try:
                    loop.call_soon_threadsafe(self._complete, future, error)
                except RuntimeError:
                    return
        finally:
            if not self._ready.is_set():
                self._ready.set()
            try:
                self._handle.close()
            finally:
                try:
                    if thread_handle is not None:
                        thread_handle.close()
                finally:
                    self._exited.set()

    def write(self, data: bytes) -> None:
        """Hand one complete frame to the dedicated writer thread."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.add_done_callback(self._consume_future_error)
        with self._condition:
            if self._closed:
                raise BrokenPipeError("protocol pipe is closed")
            if self._pending_future is not None:
                raise RuntimeError("protocol pipe write is already pending")
            self._pending_future = future
            self._request = (loop, future, bytes(data))
            self._condition.notify()

    async def wait_write_accepted(self) -> None:
        """Wait until the HANDLE accepts the complete pending frame."""
        future = self._pending_future
        if future is None:
            return
        try:
            await asyncio.shield(future)
            future.result()
        finally:
            if future.done() and self._pending_future is future:
                self._pending_future = None

    async def drain(self) -> None:
        """Wait until the dedicated thread completes the pending write."""
        await self.wait_write_accepted()

    def close(self) -> None:
        """Close the pipe and wake the dedicated writer thread."""
        queued: (
            tuple[
                asyncio.AbstractEventLoop,
                asyncio.Future[None],
                bytes,
            ]
            | None
        ) = None
        with self._condition:
            if self._closed:
                return
            self._closed = True
            queued = self._request
            self._request = None
            if self._active and self._thread_handle is not None:
                self._thread_handle.cancel()
            self._condition.notify()
        if queued is not None:
            loop, future, _ = queued
            loop.call_soon_threadsafe(
                self._complete,
                future,
                BrokenPipeError("protocol pipe is closed"),
            )

    async def wait_closed(self) -> None:
        """Wait asynchronously for the dedicated writer thread to stop."""
        await asyncio.to_thread(self._cancel_until_exited)

    def _cancel_until_exited(self) -> None:
        """Retry cancellation across the synchronous I/O startup race."""
        while not self._exited.wait(timeout=0.01):
            with self._condition:
                thread_handle = self._thread_handle
                active = self._active
            if active and thread_handle is not None:
                thread_handle.cancel()


def _fail(reason_code: str, message: str) -> BootstrapError:
    """Build one stable bootstrap error."""
    return BootstrapError(reason_code, message)


def _require_isolated_python() -> None:
    """Reject launchers that omit Python isolated mode."""
    flags = sys.flags
    if not (
        flags.isolated
        and flags.ignore_environment
        and flags.no_user_site
        and getattr(flags, "safe_path", True)
    ):
        raise _fail(
            "PYTHON_NOT_ISOLATED",
            "Runner bootstrap requires Python isolated mode",
        )


def _absolute_existing_file(value: str, name: str) -> Path:
    """Resolve a required absolute regular file without using cwd."""
    path = Path(value)
    if not path.is_absolute():
        raise _fail(
            "INVALID_BOOTSTRAP_ARGUMENT",
            f"{name} must be an absolute path",
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise _fail(
            "INVALID_BOOTSTRAP_ARGUMENT",
            f"{name} does not exist",
        ) from exc
    if not resolved.is_file():
        raise _fail(
            "INVALID_BOOTSTRAP_ARGUMENT",
            f"{name} must identify a regular file",
        )
    return resolved


def _absolute_existing_directory(value: str, name: str) -> Path:
    """Resolve a required absolute directory without using cwd."""
    path = Path(value)
    if not path.is_absolute():
        raise _fail(
            "INVALID_BOOTSTRAP_ARGUMENT",
            f"{name} must be an absolute path",
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise _fail(
            "INVALID_BOOTSTRAP_ARGUMENT",
            f"{name} does not exist",
        ) from exc
    if not resolved.is_dir():
        raise _fail(
            "INVALID_BOOTSTRAP_ARGUMENT",
            f"{name} must identify a directory",
        )
    return resolved


def _hash_code_root(code_root: Path) -> str:
    """Hash the trusted code artifact deterministically."""
    digest = hashlib.sha256()
    files = [
        path
        for path in code_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    ]
    for path in sorted(
        files,
        key=lambda item: item.relative_to(code_root).as_posix(),
    ):
        relative = path.relative_to(code_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _clean_environment(passthrough: tuple[str, ...]) -> None:
    """Keep startup variables and descriptor-declared passthrough only."""
    allowed = set(_STARTUP_ENVIRONMENT)
    allowed.update(passthrough)
    if os.name == "nt":
        allowed = {name.upper() for name in allowed}
    for name in tuple(os.environ):
        canonical_name = name.upper() if os.name == "nt" else name
        if (
            name.upper() in _AMBIENT_IMPORT_ENVIRONMENT
            or canonical_name not in allowed
        ):
            os.environ.pop(name, None)


def _capture_protocol_output() -> Any:
    """Duplicate initial stdout before ordinary output is redirected."""
    try:
        protocol_fd = os.dup(1)
        os.set_inheritable(protocol_fd, False)
        return os.fdopen(protocol_fd, "wb", buffering=0)
    except OSError as exc:
        raise _fail(
            "PROTOCOL_HANDLE_INVALID",
            "Unable to duplicate protocol stdout",
        ) from exc


def _redirect_ordinary_output() -> None:
    """Route inheritable ordinary stdout and native FD 1 to stderr."""
    try:
        os.dup2(2, 1, inheritable=True)
        redirected_stdout = open(  # pylint: disable=consider-using-with
            1,
            mode="w",
            encoding="utf-8",
            errors="backslashreplace",
            buffering=1,
            closefd=False,
        )
        sys.stdout = redirected_stdout
    except (OSError, ValueError) as exc:
        raise _fail(
            "STDOUT_REDIRECT_FAILED",
            "Unable to redirect ordinary stdout",
        ) from exc


def _entrypoint_source(code_root: Path, entrypoint: Any) -> Path:
    """Resolve the descriptor entrypoint source inside the trusted root."""
    module_path = code_root.joinpath(*entrypoint.module.split("."))
    candidates = (module_path.with_suffix(".py"), module_path / "__init__.py")
    for candidate in candidates:
        if candidate.is_file():
            resolved = candidate.resolve()
            if resolved.is_relative_to(code_root):
                return resolved
    raise _fail(
        "ENTRYPOINT_OUTSIDE_CODE_ROOT",
        "Descriptor entrypoint module is not inside code_root",
    )


def _load_driver_class(entrypoint: Any, expected_source: Path) -> Any:
    """Import and resolve only the descriptor-declared driver class."""
    try:
        module = importlib.import_module(entrypoint.module)
        module_file = getattr(module, "__file__", None)
        if (
            module_file is None
            or Path(module_file).resolve() != expected_source
        ):
            raise _fail(
                "ENTRYPOINT_OUTSIDE_CODE_ROOT",
                "Imported entrypoint did not originate from code_root",
            )
        value: Any = module
        for part in entrypoint.qualname.split("."):
            value = getattr(value, part)
        return value
    except (AttributeError, ImportError) as exc:
        raise _fail(
            "ENTRYPOINT_IMPORT_FAILED",
            "Unable to load declared component entrypoint",
        ) from exc


async def _open_protocol_transport(
    framed_transport_class: Any,
    protocol_handle: Any,
    *,
    input_handle: Any | None = None,
    limits: Any | None = None,
    payloads: Any = None,
    platform_name: str | None = None,
    writer_factory: Any = None,
) -> Any:
    """Connect the private pipe directly to CH-0-003 framing."""
    platform_name = platform_name or os.name
    writer_factory = writer_factory or _ThreadPipeWriter
    reader = asyncio.StreamReader()
    if input_handle is not None:
        loop = asyncio.get_running_loop()
        if platform_name == "nt":
            reader = _ThreadPipeReader(input_handle, loop).reader
        else:
            read_protocol = asyncio.StreamReaderProtocol(reader)
            try:
                await loop.connect_read_pipe(
                    lambda: read_protocol,
                    input_handle,
                )
            except (OSError, ValueError) as exc:
                protocol_handle.close()
                raise _fail(
                    "PROTOCOL_HANDLE_INVALID",
                    "Unable to connect protocol stdin",
                ) from exc
    if platform_name == "nt":
        try:
            writer: Any = writer_factory(protocol_handle)
        except OSError as exc:
            protocol_handle.close()
            raise _fail(
                "PROTOCOL_HANDLE_INVALID",
                "Unable to connect protocol stdout",
            ) from exc
    else:
        loop = asyncio.get_running_loop()

        def protocol_factory() -> asyncio.Protocol:
            return asyncio.streams.FlowControlMixin(loop=loop)

        try:
            write_transport, write_protocol = await loop.connect_write_pipe(
                protocol_factory,
                protocol_handle,
            )
        except (OSError, ValueError) as exc:
            protocol_handle.close()
            raise _fail(
                "PROTOCOL_HANDLE_INVALID",
                "Unable to connect protocol stdout",
            ) from exc
        writer = asyncio.StreamWriter(
            write_transport,
            write_protocol,
            None,
            loop,
        )
    options = {} if payloads is None else {"payloads": payloads}
    return framed_transport_class(
        reader,
        writer,
        limits=limits,
        **options,
    )
