# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,too-many-boolean-expressions
# pylint: disable=too-many-return-statements
"""Secure, streaming materialization for file-native R2V provider output.

The materializer has one deliberately narrow authority: it may read a local
provider result only from the current Project/Task scratch directory and may
write only a new file in that same directory.  Remote results are resolved and
downloaded one redirect hop at a time with DNS/peer pinning.  All bytes are
streamed through a bounded sink that computes integrity metadata while writing.

This module is independent from the R2V state machine so admission/recovery can
adopt it without changing provider ownership or Project commit semantics.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import ipaddress
import logging
import os
from pathlib import Path
import re
import socket
import stat
import threading
import time
from typing import Any, Literal, NoReturn
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from uuid import uuid4

import httpx

from domain.errors import StorageIntegrityError, ValidationError

logger = logging.getLogger("qwenpaw.creator.media_files.secure_video_stream")


DEFAULT_MAX_VIDEO_BYTES = 256 * 1024 * 1024
DEFAULT_TOTAL_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_REDIRECTS = 5
_COPY_CHUNK_BYTES = 64 * 1024
_MAGIC_PREFIX_BYTES = 4096
_PROCESS_R2V_MATERIALIZE_SEMAPHORE = threading.BoundedSemaphore(4)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


VideoContainer = Literal["mp4", "quicktime", "webm", "matroska", "mpeg", "avi"]


@dataclass(frozen=True, slots=True)
class MaterializedVideo:
    """A verified Task-local file ready for immutable Asset publication."""

    path: Path
    sha256: str
    size_bytes: int
    media_type: str
    container: VideoContainer
    source_kind: Literal["local", "remote"]


@dataclass(frozen=True, slots=True)
class _ResolvedRemote:
    url: str
    addresses: frozenset[str]


@dataclass(frozen=True, slots=True)
class _DetectedVideo:
    container: VideoContainer
    media_type: str
    suffix: str
    accepted_media_types: frozenset[str]


_DETECTED: dict[VideoContainer, _DetectedVideo] = {
    "mp4": _DetectedVideo(
        container="mp4",
        media_type="video/mp4",
        suffix=".mp4",
        accepted_media_types=frozenset({"video/mp4", "application/mp4"}),
    ),
    "quicktime": _DetectedVideo(
        container="quicktime",
        media_type="video/quicktime",
        suffix=".mov",
        accepted_media_types=frozenset({"video/quicktime"}),
    ),
    "webm": _DetectedVideo(
        container="webm",
        media_type="video/webm",
        suffix=".webm",
        accepted_media_types=frozenset({"video/webm"}),
    ),
    "matroska": _DetectedVideo(
        container="matroska",
        media_type="video/x-matroska",
        suffix=".mkv",
        accepted_media_types=frozenset(
            {"video/x-matroska", "video/matroska", "application/x-matroska"},
        ),
    ),
    "mpeg": _DetectedVideo(
        container="mpeg",
        media_type="video/mpeg",
        suffix=".mpeg",
        accepted_media_types=frozenset({"video/mpeg"}),
    ),
    "avi": _DetectedVideo(
        container="avi",
        media_type="video/x-msvideo",
        suffix=".avi",
        accepted_media_types=frozenset(
            {"video/x-msvideo", "video/avi", "video/msvideo"},
        ),
    ),
}


def _safe_segment(value: str, *, label: str) -> str:
    candidate = str(value or "").strip()
    if (
        not candidate
        or candidate in {".", ".."}
        or Path(candidate).is_absolute()
        or len(Path(candidate).parts) != 1
        or "/" in candidate
        or "\\" in candidate
        or any(ord(character) < 32 for character in candidate)
    ):
        raise ValidationError(f"{label} 不是安全的单段标识")
    return candidate


def _directory_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("安全视频物化要求平台支持 O_NOFOLLOW")
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | os.O_NOFOLLOW
    )


def _file_read_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("安全视频物化要求平台支持 O_NOFOLLOW")
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | os.O_NOFOLLOW
    )


def _file_create_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("安全视频物化要求平台支持 O_NOFOLLOW")
    return (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_NOFOLLOW
    )


def _open_absolute_directory(path: Path) -> int:
    """Open every component from ``/`` with openat and O_NOFOLLOW."""

    if not path.is_absolute():
        raise ValidationError("Project root 必须是绝对路径")
    parts = path.parts
    current = os.open(parts[0], _directory_flags())
    try:
        for part in parts[1:]:
            if part in {"", ".", ".."}:
                raise ValidationError("Project root 包含不安全路径段")
            following = os.open(part, _directory_flags(), dir_fd=current)
            os.close(current)
            current = following
        return current
    except BaseException:
        os.close(current)
        raise


def _open_directory_at(parent_fd: int, name: str, *, label: str) -> int:
    try:
        descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
    except OSError as error:
        raise ValidationError(f"{label} 不存在、不是目录或包含符号链接") from error
    details = os.fstat(descriptor)
    if not stat.S_ISDIR(
        details.st_mode,
    ):  # defensive for platforms without O_DIRECTORY
        os.close(descriptor)
        raise ValidationError(f"{label} 不是目录")
    return descriptor


class _TaskScratch:
    """Descriptor-rooted access to one Project/Task scratch directory."""

    def __init__(
        self,
        project_root: Path,
        project_id: str,
        task_id: str,
    ) -> None:
        self.project_root = Path(project_root)
        self.project_id = _safe_segment(project_id, label="project_id")
        self.task_id = _safe_segment(task_id, label="task_id")
        if self.project_root.name != self.project_id:
            raise ValidationError("Project root 与 project_id 不匹配")
        self.path = self.project_root / "runtime" / "task-work" / self.task_id
        self.fd = -1

    def __enter__(self) -> _TaskScratch:
        project_fd = _open_absolute_directory(self.project_root)
        opened = [project_fd]
        try:
            project_file = os.open(
                "project.json",
                _file_read_flags(),
                dir_fd=project_fd,
            )
            try:
                if not stat.S_ISREG(os.fstat(project_file).st_mode):
                    raise ValidationError(
                        "Project root 缺少 regular project.json",
                    )
            finally:
                os.close(project_file)
            runtime_fd = _open_directory_at(
                project_fd,
                "runtime",
                label="runtime",
            )
            opened.append(runtime_fd)
            work_fd = _open_directory_at(
                runtime_fd,
                "task-work",
                label="runtime/task-work",
            )
            opened.append(work_fd)
            task_fd = _open_directory_at(
                work_fd,
                self.task_id,
                label="current Task scratch",
            )
            opened.append(task_fd)
            self.fd = os.dup(task_fd)
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)
        return self

    def __exit__(self, *_args: object) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def open_regular(self, relative_parts: Sequence[str]) -> int:
        if not relative_parts:
            raise ValidationError("provider 本地视频路径缺少文件名")
        safe_parts = tuple(
            _safe_segment(part, label="provider 本地视频路径")
            for part in relative_parts
        )
        parent = os.dup(self.fd)
        try:
            for part in safe_parts[:-1]:
                following = _open_directory_at(
                    parent,
                    part,
                    label="provider 本地视频父目录",
                )
                os.close(parent)
                parent = following
            try:
                descriptor = os.open(
                    safe_parts[-1],
                    _file_read_flags(),
                    dir_fd=parent,
                )
            except OSError as error:
                raise ValidationError(
                    "provider 本地视频不存在、不是 regular file 或包含符号链接",
                ) from error
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                os.close(descriptor)
                raise ValidationError("provider 本地视频必须是 regular file")
            if details.st_nlink != 1:
                os.close(descriptor)
                raise ValidationError("provider 本地视频不允许使用硬链接")
            return descriptor
        finally:
            os.close(parent)

    def create_temp(self) -> tuple[str, int]:
        name = f"r2v-materialized-{uuid4().hex}.part"
        descriptor = os.open(name, _file_create_flags(), 0o600, dir_fd=self.fd)
        return name, descriptor

    def remove(self, name: str) -> None:
        try:
            os.unlink(name, dir_fd=self.fd)
        except FileNotFoundError:
            pass

    def finish(self, temporary_name: str, suffix: str) -> Path:
        final_name = f"{temporary_name.removesuffix('.part')}{suffix}"
        os.rename(
            temporary_name,
            final_name,
            src_dir_fd=self.fd,
            dst_dir_fd=self.fd,
        )
        os.fsync(self.fd)
        return self.path / final_name


class _StreamingSink:
    def __init__(
        self,
        descriptor: int,
        *,
        max_bytes: int,
        deadline: float,
        monotonic: Callable[[], float],
    ) -> None:
        self.descriptor = descriptor
        self.max_bytes = max_bytes
        self.deadline = deadline
        self.monotonic = monotonic
        self.size = 0
        self.digest = hashlib.sha256()
        self.prefix = bytearray()

    def _check_deadline(self) -> None:
        if self.monotonic() >= self.deadline:
            raise ValidationError("provider 视频物化超过总 deadline")

    def write(self, chunk: bytes) -> None:
        self._check_deadline()
        if not chunk:
            return
        view = memoryview(chunk)
        for offset in range(0, len(view), _COPY_CHUNK_BYTES):
            self._check_deadline()
            piece = view[offset : offset + _COPY_CHUNK_BYTES]
            if self.size + len(piece) > self.max_bytes:
                raise ValidationError("provider 视频超过大小限制")
            written_total = 0
            while written_total < len(piece):
                self._check_deadline()
                written = os.write(self.descriptor, piece[written_total:])
                if (
                    written <= 0
                ):  # pragma: no cover - regular files either write or fail
                    raise StorageIntegrityError("provider 视频 scratch 写入失败")
                written_total += written
            raw = piece.tobytes()
            self.digest.update(raw)
            if len(self.prefix) < _MAGIC_PREFIX_BYTES:
                remaining = _MAGIC_PREFIX_BYTES - len(self.prefix)
                self.prefix.extend(raw[:remaining])
            self.size += len(piece)
        self._check_deadline()

    def complete(self) -> tuple[str, int, bytes]:
        self._check_deadline()
        if self.size <= 0:
            raise ValidationError("provider 视频为空")
        os.fsync(self.descriptor)
        return self.digest.hexdigest(), self.size, bytes(self.prefix)


def _normalized_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(str(value).split("%", 1)[0])
    except ValueError as error:
        raise ValidationError("远程视频解析到了非法 IP") from error
    if not address.is_global:
        raise ValidationError("远程视频不允许访问本机、私有或保留网络")
    return address.compressed


def _parse_remote_url(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(str(value or "").strip())
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError("远程视频必须是公网 http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("远程视频 URL 不允许携带用户名或密码")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as error:
        raise ValidationError("远程视频 URL 端口非法") from error
    sanitized = urlunsplit(
        (scheme, parsed.netloc, parsed.path or "/", parsed.query, ""),
    )
    return sanitized, parsed.hostname, port


def _resolver_addresses(
    host: str,
    port: int,
    resolver: Callable[..., Any],
) -> frozenset[str]:
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        try:
            records = resolver(host, port, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror) as error:
            raise ValidationError("远程视频主机无法解析") from error
        addresses = {
            _normalized_ip(str(record[4][0]))
            for record in records
            if len(record) >= 5 and record[4]
        }
    else:
        addresses = {_normalized_ip(str(literal))}
    if not addresses:
        raise ValidationError("远程视频主机无法解析")
    return frozenset(addresses)


def _response_peer(response: httpx.Response) -> str:
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        raise ValidationError("远程视频连接缺少可验证的 peer address")
    peer = stream.get_extra_info("server_addr")
    if not isinstance(peer, tuple) or not peer:
        raise ValidationError("远程视频连接缺少可验证的 peer address")
    return _normalized_ip(str(peer[0]))


def _detect_video(prefix: bytes) -> _DetectedVideo:
    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        if prefix[8:12] == b"qt  ":
            return _DETECTED["quicktime"]
        return _DETECTED["mp4"]
    if prefix.startswith(b"\x1a\x45\xdf\xa3"):
        lowered = prefix.lower()
        if b"webm" in lowered:
            return _DETECTED["webm"]
        if b"matroska" in lowered:
            return _DETECTED["matroska"]
        raise ValidationError("EBML provider 视频缺少 WebM/Matroska DocType")
    if prefix.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")):
        return _DETECTED["mpeg"]
    if (
        len(prefix) >= 377
        and prefix[0] == 0x47
        and prefix[188] == 0x47
        and prefix[376] == 0x47
    ):
        return _DETECTED["mpeg"]
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"AVI ":
        return _DETECTED["avi"]
    raise ValidationError("provider 输出 magic 不是受支持的视频格式")


def _normalize_declared_media_type(value: Any) -> str:
    return str(value or "").split(";", 1)[0].strip().casefold()


def _verify_media_types(
    detected: _DetectedVideo,
    declarations: Sequence[str],
) -> None:
    for declared in declarations:
        normalized = _normalize_declared_media_type(declared)
        if normalized and normalized not in detected.accepted_media_types:
            raise ValidationError(
                f"provider 声明 MIME {normalized!r} 与 {detected.container} magic 不一致",
            )


def _declared_sha256(value: Any) -> str | None:
    declared = str(value or "").strip()
    if not declared:
        return None
    lowered = declared.casefold()
    for prefix in ("sha256:", "sha256="):
        if lowered.startswith(prefix):
            declared = declared[len(prefix) :].strip()
            break
    if not _SHA256.fullmatch(declared):
        raise ValidationError("provider 视频 checksum 不是合法 sha256")
    return declared.casefold()


def _source_hint(output: Mapping[str, Any]) -> str:
    value = str(
        output.get("output_path")
        or output.get("path")
        or output.get("url")
        or output.get("result_url")
        or output.get("video_url")
        or "",
    ).strip()
    if not value:
        raise ValidationError("provider 结果缺少视频 path/url")
    return value


def _local_relative_parts(
    source: str,
    *,
    project_root: Path,
    project_id: str,
    task_id: str,
) -> tuple[str, ...] | None:
    parsed = urlsplit(source)
    scheme = parsed.scheme.casefold()
    scratch = project_root / "runtime" / "task-work" / task_id
    if scheme in {"http", "https"}:
        return None
    if scheme == "file":
        if (
            parsed.netloc not in {"", "localhost"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError("provider file URL host/query/fragment 非法")
        candidate = Path(unquote(parsed.path))
    elif not scheme and source.startswith("/generated/"):
        if parsed.query or parsed.fragment:
            raise ValidationError("provider generated URL 不允许 query/fragment")
        raw = parsed.path.removeprefix("/generated/").split("/")
        decoded = tuple(unquote(part) for part in raw)
        expected = ("projects", project_id, "task-work", task_id)
        if (
            len(decoded) <= len(expected)
            or decoded[: len(expected)] != expected
        ):
            raise ValidationError(
                "provider generated URL 跨越 Project 或 Task scope",
            )
        return tuple(
            _safe_segment(part, label="provider generated URL")
            for part in decoded[len(expected) :]
        )
    elif scheme:
        raise ValidationError("provider 视频 URL scheme 不受支持")
    else:
        candidate = Path(source).expanduser()

    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(scratch)
        except ValueError as error:
            raise ValidationError(
                "provider 本地视频跨越 Project 或 Task scope",
            ) from error
    else:
        relative = candidate
    if not relative.parts:
        raise ValidationError("provider 本地视频路径缺少文件名")
    return tuple(
        _safe_segment(part, label="provider 本地视频路径") for part in relative.parts
    )


class SecureR2VVideoMaterializer:
    """Stream one provider video into the current Task's scratch directory.

    ``resolver`` and ``transport`` are injectable for deterministic tests.  The
    default semaphore is module-global, so all service instances in this
    process share one bounded materialization budget.
    """

    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_VIDEO_BYTES,
        total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        resolver: Callable[..., Any] = socket.getaddrinfo,
        transport: httpx.AsyncBaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        semaphore: threading.BoundedSemaphore | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects must be non-negative")
        self.max_bytes = int(max_bytes)
        self.total_timeout_seconds = float(total_timeout_seconds)
        self.max_redirects = int(max_redirects)
        self.resolver = resolver
        self.transport = transport
        self.monotonic = monotonic
        self.semaphore = semaphore or _PROCESS_R2V_MATERIALIZE_SEMAPHORE

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            raise ValidationError("provider 视频物化超过总 deadline")
        return remaining

    async def _acquire(self, deadline: float) -> None:
        while not self.semaphore.acquire(blocking=False):
            await asyncio.sleep(min(0.01, self._remaining(deadline)))
        try:
            self._remaining(deadline)
        except BaseException:
            self.semaphore.release()
            raise

    async def _resolve(self, value: str, deadline: float) -> _ResolvedRemote:
        url, host, port = _parse_remote_url(value)
        remaining = self._remaining(deadline)
        try:
            addresses = await asyncio.wait_for(
                asyncio.to_thread(
                    _resolver_addresses,
                    host,
                    port,
                    self.resolver,
                ),
                timeout=remaining,
            )
        except TimeoutError as error:
            raise ValidationError("provider 视频 DNS 解析超过总 deadline") from error
        self._remaining(deadline)
        return _ResolvedRemote(url=url, addresses=addresses)

    async def _stream_remote(
        self,
        source: str,
        sink: _StreamingSink,
        deadline: float,
    ) -> str:
        current = await self._resolve(source, deadline)
        async with httpx.AsyncClient(
            transport=self.transport,
            follow_redirects=False,
            trust_env=False,
            timeout=None,
            headers={"Accept": "video/*", "Accept-Encoding": "identity"},
        ) as client:
            for redirect_index in range(self.max_redirects + 1):
                remaining = self._remaining(deadline)
                try:
                    async with asyncio.timeout(remaining):
                        async with client.stream(
                            "GET",
                            current.url,
                        ) as response:
                            peer = _response_peer(response)
                            if peer not in current.addresses:
                                raise ValidationError(
                                    "远程视频连接 peer 不属于当前跳 DNS 预解析集合",
                                )
                            if response.status_code in _REDIRECT_STATUSES:
                                if redirect_index >= self.max_redirects:
                                    raise ValidationError(
                                        "provider 视频重定向次数超过限制",
                                    )
                                location = response.headers.get("location")
                                if not location:
                                    raise ValidationError(
                                        "provider 视频重定向缺少 Location",
                                    )
                                next_url = urljoin(current.url, location)
                            else:
                                if (
                                    response.status_code < 200
                                    or response.status_code >= 300
                                ):
                                    raise ValidationError(
                                        f"provider 视频下载 HTTP {response.status_code}",
                                    )
                                encoding = response.headers.get(
                                    "content-encoding",
                                    "identity",
                                ).casefold()
                                if encoding not in {"", "identity"}:
                                    raise ValidationError(
                                        "provider 视频未返回 identity 原始字节",
                                    )
                                declared_length = response.headers.get(
                                    "content-length",
                                )
                                if declared_length:
                                    try:
                                        length = int(declared_length)
                                    except ValueError as error:
                                        raise ValidationError(
                                            "provider 视频 Content-Length 非法",
                                        ) from error
                                    if length < 0 or length > self.max_bytes:
                                        raise ValidationError(
                                            "provider 视频 Content-Length 超过大小限制",
                                        )
                                async for chunk in response.aiter_raw():
                                    sink.write(chunk)
                                return response.headers.get("content-type", "")
                except TimeoutError as error:
                    raise ValidationError(
                        "provider 视频下载超过总 deadline",
                    ) from error
                current = await self._resolve(next_url, deadline)
        raise ValidationError("provider 视频未产生最终响应")  # pragma: no cover

    @staticmethod
    def _stream_local(source_fd: int, sink: _StreamingSink) -> None:
        while True:
            sink._check_deadline()
            chunk = os.read(source_fd, _COPY_CHUNK_BYTES)
            sink._check_deadline()
            if not chunk:
                return
            sink.write(chunk)

    @staticmethod
    def _raise_materialize_os_error(
        project_id: str,
        task_id: str,
        error: OSError,
    ) -> NoReturn:
        """Translate an OS-level failure, keeping its detail visible.

        The transient-failure classifier matches on the message (e.g.
        "bad file descriptor", "connection reset"); a bare label
        previously turned every transport hiccup into a deterministic,
        never-retried failure after the provider had already paid for
        the generation.
        """

        logger.error(
            "video materialize os error: project=%s task=%s error=%s",
            project_id,
            task_id,
            error,
        )
        raise ValidationError(
            f"provider 视频安全物化失败: {error}",
        ) from error

    async def materialize(
        self,
        output: Mapping[str, Any],
        *,
        project_root: Path,
        project_id: str,
        task_id: str,
    ) -> MaterializedVideo:
        """Materialize and verify one provider result inside its Task scope."""

        source = _source_hint(output)
        project_root = Path(project_root)
        project_id = _safe_segment(project_id, label="project_id")
        task_id = _safe_segment(task_id, label="task_id")
        relative_parts = _local_relative_parts(
            source,
            project_root=project_root,
            project_id=project_id,
            task_id=task_id,
        )
        source_kind = "local" if relative_parts is not None else "remote"
        logger.info(
            "video materialize start: project=%s task=%s source=%s",
            project_id,
            task_id,
            source_kind,
        )
        deadline = self.monotonic() + self.total_timeout_seconds
        acquired = False
        temporary_name: str | None = None
        destination_fd = -1
        try:
            await self._acquire(deadline)
            acquired = True
            with _TaskScratch(project_root, project_id, task_id) as scratch:
                temporary_name, destination_fd = scratch.create_temp()
                sink = _StreamingSink(
                    destination_fd,
                    max_bytes=self.max_bytes,
                    deadline=deadline,
                    monotonic=self.monotonic,
                )
                response_media_type = ""
                try:
                    if relative_parts is None:
                        response_media_type = await self._stream_remote(
                            source,
                            sink,
                            deadline,
                        )
                        source_kind: Literal["local", "remote"] = "remote"
                    else:
                        source_fd = scratch.open_regular(relative_parts)
                        try:
                            self._stream_local(source_fd, sink)
                        finally:
                            os.close(source_fd)
                        source_kind = "local"
                    checksum, size_bytes, prefix = sink.complete()
                    detected = _detect_video(prefix)
                    _verify_media_types(
                        detected,
                        (
                            str(
                                output.get("media_type")
                                or output.get("content_type")
                                or "",
                            ),
                            response_media_type,
                        ),
                    )
                    declared_checksum = _declared_sha256(
                        output.get("checksum"),
                    )
                    if (
                        declared_checksum is not None
                        and declared_checksum != checksum
                    ):
                        raise StorageIntegrityError(
                            "provider 视频 checksum 与实际流式 sha256 不一致",
                        )
                    os.close(destination_fd)
                    destination_fd = -1
                    path = scratch.finish(temporary_name, detected.suffix)
                    temporary_name = None
                    logger.info(
                        "video materialize complete: project=%s task=%s "
                        "size=%d sha256=%s container=%s",
                        project_id,
                        task_id,
                        size_bytes,
                        checksum[:16],
                        detected.container,
                    )
                    return MaterializedVideo(
                        path=path,
                        sha256=checksum,
                        size_bytes=size_bytes,
                        media_type=detected.media_type,
                        container=detected.container,
                        source_kind=source_kind,
                    )
                finally:
                    if destination_fd >= 0:
                        os.close(destination_fd)
                        destination_fd = -1
                    if temporary_name is not None:
                        scratch.remove(temporary_name)
        except OSError as error:
            self._raise_materialize_os_error(project_id, task_id, error)
        finally:
            if acquired:
                self.semaphore.release()


async def materialize_r2v_video(
    output: Mapping[str, Any],
    *,
    project_root: Path,
    project_id: str,
    task_id: str,
    max_bytes: int = DEFAULT_MAX_VIDEO_BYTES,
    total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
) -> MaterializedVideo:
    """Convenience API using the process-global materialization semaphore."""

    return await SecureR2VVideoMaterializer(
        max_bytes=max_bytes,
        total_timeout_seconds=total_timeout_seconds,
    ).materialize(
        output,
        project_root=project_root,
        project_id=project_id,
        task_id=task_id,
    )


__all__ = [
    "DEFAULT_MAX_VIDEO_BYTES",
    "DEFAULT_TOTAL_TIMEOUT_SECONDS",
    "MaterializedVideo",
    "SecureR2VVideoMaterializer",
    "materialize_r2v_video",
]
