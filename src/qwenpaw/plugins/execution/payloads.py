# -*- coding: utf-8 -*-
"""Private per-run files for complete logical JSON messages, not locators."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict, dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time
from uuid import uuid4

from ...utils.io_utils import run_sync_io

from .errors import (
    FrameClosedError,
    FrameLimitError,
    FrameProtocolError,
    FrameTimeoutError,
    FrameWriteError,
)

_MARKER = "$qwenpaw_payload"
_REFERENCE_KEYS = {
    _MARKER,
    "run_id",
    "direction",
    "id",
    "byte_length",
    "sha256",
}


@dataclass(frozen=True)
class PayloadLimits:
    """Logical message and pending disk limits, independently per direction."""

    max_message_bytes: int = 128 * 1024 * 1024
    max_pending_bytes: int = 128 * 1024 * 1024
    max_pending_files: int = 64

    def __post_init__(self):
        for value in asdict(self).values():
            if type(value) is not int or value <= 0:
                raise ValueError("payload limits must be positive integers")


def _strict_json(value):
    def invalid(_value):
        raise ValueError("non-finite JSON")

    return json.loads(value, parse_constant=invalid)


def _hex(value, length):
    return (
        isinstance(value, str)
        and re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is not None
    )


class PayloadStore:
    """One side's outbox quota; only the creating host disposes the run root."""

    def __init__(self, root, run_id, limits, side, *, owner=False):
        self.root, self.run_id, self.limits = root, run_id, limits
        self.direction = "h2w" if side == "host" else "w2h"
        self._incoming = "w2h" if side == "host" else "h2w"
        self._owner, self._closed = owner, False
        self._disposed = False
        self._owned = {}
        self._writing = set()
        self._jobs = {}
        self._deleting = {}
        self._cleanup_job = None
        self._identities = {}
        self._directories = {}
        try:
            for name, path in (
                ("root", root),
                ("h2w", root / "h2w"),
                ("w2h", root / "w2h"),
            ):
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode) or self._reparse(info):
                    raise FrameProtocolError("invalid payload directory")
                self._identities[name] = (info.st_dev, info.st_ino)
                if os.name != "nt":
                    self._directories[name] = os.open(
                        path,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    )
        except BaseException:
            self._close_handles()
            raise

    @staticmethod
    def _reparse(info):
        return stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
        )

    @classmethod
    def create(cls, limits=None):
        limits = PayloadLimits() if limits is None else limits
        if not isinstance(limits, PayloadLimits):
            raise ValueError("PayloadLimits required")
        root = Path(tempfile.mkdtemp(prefix="qwenpaw-payload-"))
        try:
            root.chmod(0o700)
            for direction in ("h2w", "w2h"):
                (root / direction).mkdir(mode=0o700)
            return cls(root, uuid4().hex, limits, "host", owner=True)
        except BaseException:
            for direction in ("h2w", "w2h"):
                path = root / direction
                if path.exists():
                    path.rmdir()
            root.rmdir()
            raise

    @classmethod
    async def acreate(cls, limits=None):
        """Create off-loop; callers settle assignment before cancellation."""
        return await run_sync_io(cls.create, limits)

    def launch_context(self):
        return {
            "version": 1,
            "root": str(self.root),
            "run_id": self.run_id,
            "limits": asdict(self.limits),
        }

    @classmethod
    def attach(cls, context, *, side="worker"):
        if (
            not isinstance(context, Mapping)
            or set(context) != {"version", "root", "run_id", "limits"}
            or type(context["version"]) is not int
            or context["version"] != 1
            or side not in {"host", "worker"}
            or not _hex(context["run_id"], 32)
            or not isinstance(context["root"], str)
            or "\0" in context["root"]
            or not Path(context["root"]).is_absolute()
            or not isinstance(context["limits"], Mapping)
            or set(context["limits"]) != set(asdict(PayloadLimits()))
        ):
            raise FrameProtocolError("invalid payload context")
        try:
            limits = PayloadLimits(**context["limits"])
            return cls(Path(context["root"]), context["run_id"], limits, side)
        except (ValueError, OSError) as exc:
            raise FrameProtocolError("invalid payload context") from exc

    def _check_directories(self):
        for name, identity in self._identities.items():
            path = self.root if name == "root" else self.root / name
            info = path.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or self._reparse(info)
                or (info.st_dev, info.st_ino) != identity
            ):
                raise FrameProtocolError("payload directory changed")

    def _path(self, direction, name):
        return self.root / direction / name

    def _open(self, direction, name, *, create=False):
        self._check_directories()
        if os.name != "nt":
            flags = os.O_NOFOLLOW | (os.O_WRONLY if create else os.O_RDONLY)
            if create:
                flags |= os.O_CREAT | os.O_EXCL
            else:
                # Reject FIFOs/devices via fstat without blocking in open().
                flags |= os.O_NONBLOCK
            return os.open(
                name,
                flags,
                0o600,
                dir_fd=self._directories[direction],
            )
        if create:
            return os.open(
                self._path(direction, name),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY,
                0o600,
            )
        # Python has no Windows O_NOFOLLOW; open the reparse point itself.
        import ctypes
        from ctypes import wintypes
        import msvcrt

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.GetFileInformationByHandleEx.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        handle = kernel.CreateFileW(
            str(self._path(direction, name)),
            0x80000000,
            7,
            None,
            3,
            0x00200000,
            None,
        )
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = (wintypes.DWORD * 2)()
        if not kernel.GetFileInformationByHandleEx(
            handle,
            9,
            ctypes.byref(attributes),
            ctypes.sizeof(attributes),
        ):
            error = ctypes.get_last_error()
            kernel.CloseHandle(handle)
            raise ctypes.WinError(error)
        if attributes[0] & 0x400:
            kernel.CloseHandle(handle)
            raise FrameProtocolError("payload reparse point rejected")
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise

    def _unlink(self, direction, name):
        self._check_directories()
        if os.name == "nt":
            path = self._path(direction, name)
            info = path.lstat()
            if not self._reparse(info):
                path.chmod(0o600)
            path.unlink()
        else:
            os.unlink(name, dir_fd=self._directories[direction])

    async def _sweep(self, deadline):
        tokens = tuple(
            token
            for token in self._owned
            if token not in self._writing and token not in self._deleting
        )
        cutoff = self._cutoff(deadline)

        def inspect(abort):
            self._check_deadline(cutoff, abort)
            self._check_directories()
            missing = []
            for token in tokens:
                self._check_deadline(cutoff, abort)
                exists = False
                for suffix in (".json", ".part"):
                    try:
                        self._path(self.direction, token + suffix).lstat()
                        exists = True
                    except FileNotFoundError:
                        pass
                if not exists:
                    missing.append(token)
            return missing

        for token in await self._io(inspect, deadline):
            if token not in self._writing and token not in self._deleting:
                self._owned.pop(token, None)

    def pending_snapshot(self):
        return {
            "direction": self.direction,
            "pending_files": len(self._owned),
            "pending_bytes": sum(self._owned.values()),
            "io_pending": sum(not job.done() for job in self._jobs),
            "closed": self._closed,
        }

    def validate_message(self, message):
        if not isinstance(message, str) or not message:
            raise FrameProtocolError("payload must be non-empty text")
        if len(message) > self.limits.max_message_bytes:
            raise FrameLimitError("logical payload exceeds maximum length")
        try:
            body = message.encode("utf-8", "strict")
        except UnicodeError as exc:
            raise FrameProtocolError("payload is not valid UTF-8") from exc
        if len(body) > self.limits.max_message_bytes:
            raise FrameLimitError("logical payload exceeds maximum length")
        return body

    @staticmethod
    def _check_deadline(deadline, abort):
        if abort.is_set() or time.monotonic() >= deadline:
            raise FrameTimeoutError("payload I/O deadline expired")

    @staticmethod
    def _cutoff(deadline):
        return time.monotonic() + max(
            0,
            deadline - asyncio.get_running_loop().time(),
        )

    async def _io(self, function, deadline, *, orphan=None, settled=None):
        if self._closed:
            raise FrameClosedError("payload store is closed")
        abort = threading.Event()
        job = asyncio.create_task(asyncio.to_thread(function, abort))
        self._jobs[job] = abort
        abandoned = False

        def complete(task):
            try:
                task.result()
            except BaseException:
                pass
            if settled is not None:
                settled()
            if abandoned and orphan is not None:
                orphan()
            self._jobs.pop(task, None)

        job.add_done_callback(complete)
        try:
            return await asyncio.wait_for(
                asyncio.shield(job),
                max(0, deadline - asyncio.get_running_loop().time()),
            )
        except asyncio.TimeoutError as exc:
            abandoned = True
            abort.set()
            raise FrameTimeoutError("payload I/O deadline expired") from exc
        except asyncio.CancelledError:
            abandoned = True
            abort.set()
            raise
        except OSError as exc:
            raise FrameWriteError("payload I/O failed") from exc

    async def stage(self, message, *, max_frame_bytes, deadline):
        if self._closed:
            raise FrameClosedError("payload store is closed")
        body = self.validate_message(message)
        if len(body) <= max_frame_bytes:
            return message, None
        try:
            _strict_json(message)
        except (ValueError, TypeError, RecursionError) as exc:
            raise FrameProtocolError("payload is not strict JSON") from exc
        await self._sweep(deadline)
        if self._closed:
            raise FrameClosedError("payload store is closed")
        if (
            len(self._owned) >= self.limits.max_pending_files
            or sum(self._owned.values()) + len(body)
            > self.limits.max_pending_bytes
        ):
            raise FrameLimitError("pending payload disk quota exceeded")
        token = uuid4().hex
        self._owned[token] = len(body)
        self._writing.add(token)

        cutoff = self._cutoff(deadline)

        def write(abort):
            self._check_deadline(cutoff, abort)
            fd = self._open(self.direction, token + ".part", create=True)
            with os.fdopen(fd, "wb") as output:
                for offset in range(0, len(body), 65536):
                    self._check_deadline(cutoff, abort)
                    output.write(body[offset : offset + 65536])
                output.flush()
                if os.name == "nt":
                    os.chmod(
                        self._path(self.direction, token + ".part"),
                        0o400,
                    )
                else:
                    os.fchmod(output.fileno(), 0o400)
            self._check_deadline(cutoff, abort)
            # Atomic publication must never replace an existing token.
            self._check_directories()
            if os.name == "nt":
                os.link(
                    self._path(self.direction, token + ".part"),
                    self._path(self.direction, token + ".json"),
                )
            else:
                directory = self._directories[self.direction]
                os.link(
                    token + ".part",
                    token + ".json",
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            self._unlink(self.direction, token + ".part")
            if os.name == "nt":
                # Windows readonly is shared by hard links; restore it
                # after removing the staging name, before ref visibility.
                self._path(self.direction, token + ".json").chmod(0o400)

        try:
            await self._io(
                write,
                deadline,
                settled=lambda: self._writing.discard(token),
                orphan=lambda: self.discard(token),
            )
        except BaseException:
            if token not in self._writing:
                self.discard(token)
            raise
        reference = {
            _MARKER: 1,
            "run_id": self.run_id,
            "direction": self.direction,
            "id": token,
            "byte_length": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        return json.dumps(reference, separators=(",", ":")), token

    def discard(self, token):
        """Register deletion; capacity stays owned until confirmed removed."""
        if self._cleanup_job is not None:
            return self._cleanup_job
        if self._disposed or token not in self._owned:
            return None
        if token in self._deleting:
            return self._deleting[token]
        if token in self._writing:
            return None

        def remove():
            try:
                for suffix in (".part", ".json"):
                    try:
                        self._unlink(self.direction, token + suffix)
                    except FileNotFoundError:
                        pass
                return True
            except (OSError, FrameProtocolError):
                return False

        job = asyncio.create_task(asyncio.to_thread(remove))
        self._jobs[job] = threading.Event()
        self._deleting[token] = job

        def complete(task):
            try:
                if task.result():
                    self._owned.pop(token, None)
            except BaseException:
                pass
            self._deleting.pop(token, None)
            self._jobs.pop(task, None)

        job.add_done_callback(complete)
        return job

    async def adiscard(self, token):
        job = self.discard(token)
        if job is not None:
            await asyncio.shield(job)

    async def read(self, message, *, deadline):
        self.validate_message(message)
        try:
            reference = _strict_json(message)
        except (ValueError, TypeError, RecursionError):
            return message  # Preserve ordinary RpcPeer parse-error handling.
        if not isinstance(reference, dict) or _MARKER not in reference:
            return message

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise FrameProtocolError("duplicate payload field")
                result[key] = value
            return result

        reference = json.loads(message, object_pairs_hook=unique)
        if (
            set(reference) != _REFERENCE_KEYS
            or type(reference[_MARKER]) is not int
            or reference[_MARKER] != 1
            or reference["run_id"] != self.run_id
            or reference["direction"] != self._incoming
            or not _hex(reference["id"], 32)
            or not _hex(reference["sha256"], 64)
            or type(reference["byte_length"]) is not int
            or not 0
            < reference["byte_length"]
            <= min(
                self.limits.max_message_bytes,
                self.limits.max_pending_bytes,
            )
        ):
            raise FrameProtocolError("invalid payload reference")
        name = reference["id"] + ".json"

        cutoff = self._cutoff(deadline)

        def load(abort):
            self._check_deadline(cutoff, abort)
            try:
                fd = self._open(self._incoming, name)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOENT, errno.ENOTDIR}:
                    raise FrameProtocolError("invalid payload target") from exc
                raise
            with os.fdopen(fd, "rb") as source:
                info = os.fstat(source.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_size != reference["byte_length"]
                    or info.st_mode & 0o222
                ):
                    raise FrameProtocolError("invalid payload file")
                chunks, digest = [], hashlib.sha256()
                remaining = reference["byte_length"]
                while remaining:
                    self._check_deadline(cutoff, abort)
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        raise FrameProtocolError("truncated payload file")
                    remaining -= len(chunk)
                    chunks.append(chunk)
                    digest.update(chunk)
                if source.read(1) or digest.hexdigest() != reference["sha256"]:
                    raise FrameProtocolError("payload integrity mismatch")
            self._check_directories()
            try:
                result = b"".join(chunks).decode("utf-8", "strict")
                _strict_json(result)
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise FrameProtocolError("invalid payload JSON") from exc
            self._check_deadline(cutoff, abort)
            self._unlink(self._incoming, name)
            return result

        return await self._io(load, deadline)

    def close(self):
        """Fence new I/O; possibly unread files remain owned until tree exit."""
        self._closed = True
        for abort in self._jobs.values():
            abort.set()

    def _close_handles(self):
        for name, fd in tuple(self._directories.items()):
            os.close(fd)
            self._directories.pop(name)

    def _cleanup_files(self, deadline, abort):
        closed = []
        try:
            self._check_deadline(deadline, abort)
            if self._owner:
                try:
                    root_info = self.root.lstat()
                except FileNotFoundError:
                    root_info = None
                if root_info is not None:
                    if (
                        self._reparse(root_info)
                        or (root_info.st_dev, root_info.st_ino)
                        != self._identities["root"]
                    ):
                        return False, closed
                    for direction in ("h2w", "w2h"):
                        directory = self.root / direction
                        try:
                            info = directory.lstat()
                        except FileNotFoundError:
                            continue
                        if (
                            self._reparse(info)
                            or (info.st_dev, info.st_ino)
                            != self._identities[direction]
                        ):
                            return False, closed
                        for path in directory.iterdir():
                            self._check_deadline(deadline, abort)
                            if path.is_dir():
                                return False, closed
                            self._unlink(direction, path.name)
                    for direction in ("h2w", "w2h"):
                        self._check_deadline(deadline, abort)
                        try:
                            (self.root / direction).rmdir()
                        except FileNotFoundError:
                            pass
                    self._check_deadline(deadline, abort)
                    self.root.rmdir()
            for name, fd in tuple(self._directories.items()):
                self._check_deadline(deadline, abort)
                os.close(fd)
                closed.append(name)
            return True, closed
        except (OSError, FrameProtocolError, FrameTimeoutError):
            return False, closed

    async def cleanup(self, *, deadline):
        """Fence admission, drain every successor, then exclusively dispose."""
        if self._disposed:
            return True
        self.close()
        loop = asyncio.get_running_loop()
        while self._jobs:
            if loop.time() >= deadline:
                return False
            _, pending = await asyncio.wait(
                tuple(self._jobs),
                timeout=max(0, deadline - loop.time()),
            )
            if pending:
                return False
            # Completion callbacks may register orphan deletion successors.
            await asyncio.sleep(0)
        if self._disposed:
            return True
        if loop.time() >= deadline:
            return False
        abort = threading.Event()
        job = asyncio.create_task(
            asyncio.to_thread(
                self._cleanup_files,
                self._cutoff(deadline),
                abort,
            ),
        )
        self._cleanup_job = job
        self._jobs[job] = abort

        def complete(task):
            try:
                disposed, closed = task.result()
                for name in closed:
                    self._directories.pop(name, None)
                if disposed:
                    self._owned.clear()
                    self._disposed = True
            except BaseException:
                pass
            self._cleanup_job = None
            self._jobs.pop(task, None)

        job.add_done_callback(complete)
        try:
            await asyncio.wait_for(
                asyncio.shield(job),
                max(0, deadline - loop.time()),
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            abort.set()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return False
        return self._disposed
