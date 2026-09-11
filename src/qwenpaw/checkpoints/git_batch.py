# -*- coding: utf-8 -*-
"""Scoped reader for Git's long-lived ``cat-file --batch`` protocol."""

from __future__ import annotations

import subprocess
import threading
from contextlib import contextmanager
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import IO

from .models import CheckpointError

_HEADER_LIMIT = 4096
_READ_CHUNK_SIZE = 1024 * 1024
_SHUTDOWN_TIMEOUT_SECONDS = 5


class _GitBlobStream:  # pylint: disable=protected-access
    """Bounded reader for one response in Git's batch protocol."""

    def __init__(self, batch: "GitBlobBatch", size: int) -> None:
        self._batch = batch
        self.size = size
        self._remaining = size
        self._closed = False

    def read(self, size: int = -1) -> bytes:
        """Read at most *size* bytes without crossing the blob boundary."""
        if self._closed or self._remaining == 0 or size == 0:
            return b""
        requested = self._remaining if size < 0 else min(size, self._remaining)
        chunk = self._batch._read_stdout(
            requested,
        )  # pylint: disable=protected-access
        if not chunk:
            self._batch._raise_early_exit()  # pylint: disable=protected-access
        self._remaining -= len(chunk)
        if self._remaining == 0:
            self._finish_response()
        return chunk

    def close(self) -> None:
        """Drain unread bytes so the next request remains protocol-aligned."""
        if self._closed:
            return
        while self._remaining:
            self.read(min(_READ_CHUNK_SIZE, self._remaining))
        if not self._closed:
            self._finish_response()

    def _finish_response(self) -> None:
        if self._closed:
            return
        separator = self._batch._read_stdout(
            1,
        )  # pylint: disable=protected-access
        self._closed = True
        self._batch._release_stream(self)  # pylint: disable=protected-access
        if separator != b"\n":
            raise CheckpointError(
                "Truncated git cat-file --batch response",
            )


class GitBlobBatch:
    """Read multiple blobs through one bounded-lifetime Git process."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
    ) -> None:
        self._command = tuple(command)
        self._cwd = cwd
        self._env = dict(env)
        self._timeout = timeout
        self._process: subprocess.Popen[bytes] | None = None
        self._watchdog: threading.Timer | None = None
        self._timed_out = threading.Event()
        self._active_stream: _GitBlobStream | None = None

    def __enter__(self) -> GitBlobBatch:
        try:
            self._process = subprocess.Popen(
                self._command,
                cwd=str(self._cwd),
                env=self._env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise CheckpointError(
                f"Failed to start git cat-file --batch: {exc}",
            ) from exc
        self._watchdog = threading.Timer(self._timeout, self._expire)
        self._watchdog.daemon = True
        self._watchdog.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        returncode, detail = self._close(abort=exc_type is not None)
        if exc_type is not None:
            return
        if self._timed_out.is_set():
            raise self._timeout_error()
        if returncode not in (None, 0):
            raise CheckpointError(
                f"git cat-file --batch exited with status {returncode}"
                + (f": {detail}" if detail else ""),
            )

    def read_blob(self, object_id: str, *, error_message: str) -> bytes:
        """Read one blob from the batch process."""
        with self.stream_blob(
            object_id,
            error_message=error_message,
        ) as stream:
            chunks: list[bytes] = []
            while chunk := stream.read(_READ_CHUNK_SIZE):
                chunks.append(chunk)
            return b"".join(chunks)

    @contextmanager
    def stream_blob(
        self,
        object_id: str,
        *,
        error_message: str,
    ) -> Iterator[_GitBlobStream]:
        """Yield a bounded stream for one blob and drain it on exit."""
        if self._active_stream is not None:
            raise RuntimeError("Previous git blob stream is still active")
        try:
            self._stdin.write(object_id.encode("ascii") + b"\n")
            self._stdin.flush()
            header = self._stdout.readline(_HEADER_LIMIT)
            if not header:
                self._raise_early_exit()
            if not header.endswith(b"\n"):
                raise CheckpointError(
                    "Malformed git cat-file --batch header",
                )
            fields = header[:-1].split()
            if len(fields) == 2 and fields[1] in {b"missing", b"ambiguous"}:
                raise CheckpointError(error_message)
            if len(fields) != 3 or fields[1] != b"blob":
                raise CheckpointError(
                    "Malformed git cat-file --batch header",
                )
            size = int(fields[2])
            if size < 0:
                raise ValueError("negative blob size")
            stream = _GitBlobStream(self, size)
            self._active_stream = stream
            try:
                yield stream
            finally:
                stream.close()
        except (BrokenPipeError, OSError, UnicodeError, ValueError) as exc:
            if self._timed_out.is_set():
                raise self._timeout_error() from exc
            raise CheckpointError(
                f"Failed to read git cat-file --batch response: {exc}",
            ) from exc

    @property
    def _stdin(self) -> IO[bytes]:
        process = self._require_process()
        if process.stdin is None:
            raise RuntimeError("git cat-file stdin is unavailable")
        return process.stdin

    @property
    def _stdout(self) -> IO[bytes]:
        process = self._require_process()
        if process.stdout is None:
            raise RuntimeError("git cat-file stdout is unavailable")
        return process.stdout

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise RuntimeError(
                "GitBlobBatch must be used as a context manager",
            )
        return self._process

    def _read_stdout(self, size: int) -> bytes:
        return self._stdout.read(size)

    def _release_stream(self, stream: _GitBlobStream) -> None:
        if self._active_stream is stream:
            self._active_stream = None

    def _raise_early_exit(self) -> None:
        if self._timed_out.is_set():
            raise self._timeout_error()
        detail = self._stderr_detail()
        raise CheckpointError(
            "git cat-file --batch exited before returning a blob"
            + (f": {detail}" if detail else ""),
        )

    def _timeout_error(self) -> CheckpointError:
        return CheckpointError(
            "git cat-file --batch timed out after "
            f"{self._timeout:g} seconds",
        )

    def _expire(self) -> None:
        self._timed_out.set()
        process = self._process
        if process is not None and process.poll() is None:
            self._kill(process)

    def _stderr_detail(self) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return ""
        try:
            return (
                process.stderr.read()
                .decode(
                    "utf-8",
                    errors="replace",
                )
                .strip()
            )
        except OSError:
            return ""

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            process.kill()
        except OSError:
            pass

    @staticmethod
    def _close_pipe(stream: IO[bytes] | None) -> None:
        if stream is None:
            return
        try:
            stream.close()
        except OSError:
            pass

    def _close(self, *, abort: bool) -> tuple[int | None, str]:
        watchdog = self._watchdog
        if watchdog is not None:
            watchdog.cancel()
            watchdog.join()
            self._watchdog = None

        process = self._process
        if process is None:
            return None, ""
        if abort and process.poll() is None:
            self._kill(process)
        else:
            self._close_pipe(process.stdin)
        try:
            process.wait(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self._kill(process)
            process.wait()
        detail = self._stderr_detail()
        returncode = process.returncode
        self._close_pipe(process.stdin)
        self._close_pipe(process.stdout)
        self._close_pipe(process.stderr)
        self._process = None
        return returncode, detail


__all__ = ["GitBlobBatch"]
