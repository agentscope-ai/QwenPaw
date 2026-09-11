# -*- coding: utf-8 -*-
"""SSRF-safe, bounded HTTP(S) download primitives.

Every caller uses the same URL, DNS, connected-peer, redirect, compression and
size policy. Small consumers may materialize bytes; large-media consumers keep
the validated response streaming into their own staging/file boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
import ipaddress
import logging
from pathlib import Path
import shutil
import socket
import subprocess
import time
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

logger = logging.getLogger(
    "qwenpaw.creator.runtime_files.safe_remote_download",
)


DEFAULT_MAX_REMOTE_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class SafeRemoteDownloadError(ValueError):
    """A remote URL or response violated the Creator download policy."""


def require_public_ip(address: str) -> None:
    """Reject loopback, private, link-local and reserved addresses."""

    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError as error:
        logger.warning("ssrf block: invalid ip address: %s", address)
        raise SafeRemoteDownloadError("远程 URL 解析到了非法 IP") from error
    if not parsed.is_global:
        logger.warning(
            "ssrf block: non-global ip address: %s (%s)",
            address,
            "loopback"
            if parsed.is_loopback
            else "private"
            if parsed.is_private
            else "link-local"
            if parsed.is_link_local
            else "reserved",
        )
        raise SafeRemoteDownloadError(
            "远程 URL 不允许访问本机、私有或保留网络",
        )


def validate_public_remote_url(
    value: str,
    *,
    resolver: Any = socket.getaddrinfo,
) -> str:
    """Return a fragment-free public HTTP(S) URL after validating every IP."""

    parsed = urlsplit(str(value or "").strip())
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
    ):
        raise SafeRemoteDownloadError("远程 URL 必须是公网 http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise SafeRemoteDownloadError("远程 URL 不允许携带用户名或密码")
    try:
        port = parsed.port or (
            443 if parsed.scheme.casefold() == "https" else 80
        )
    except ValueError as error:
        raise SafeRemoteDownloadError("远程 URL 端口非法") from error
    host = parsed.hostname
    # Distinguish literal-IP hosts from hostnames up front: pushing a
    # hostname through require_public_ip only to catch the failure logged a
    # misleading "ssrf block: invalid ip address: <hostname>" WARNING on
    # every legitimate domain download.
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        try:
            records = resolver(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as error:
            raise SafeRemoteDownloadError(
                "远程 URL 主机无法解析",
            ) from error
        addresses = {str(record[4][0]) for record in records if record[4]}
        if not addresses:
            raise SafeRemoteDownloadError(
                "远程 URL 主机无法解析",
            ) from None
        for address in addresses:
            require_public_ip(address)
    else:
        require_public_ip(host)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""),
    )


def validate_response_peer(response: httpx.Response) -> None:
    """Verify the address used by the actual socket after DNS resolution."""

    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        raise SafeRemoteDownloadError(
            "远程 URL 连接缺少可验证的 peer address",
        )
    peer = stream.get_extra_info("server_addr")
    if not isinstance(peer, tuple) or not peer:
        raise SafeRemoteDownloadError(
            "远程 URL 连接缺少可验证的 peer address",
        )
    require_public_ip(str(peer[0]))


def declared_content_length(
    response: httpx.Response,
    *,
    max_bytes: int,
) -> int | None:
    """Validate and return Content-Length without trusting it as a cap."""

    declared = response.headers.get("content-length")
    if not declared:
        return None
    try:
        declared_size = int(declared)
    except ValueError as error:
        raise SafeRemoteDownloadError(
            "远程 URL Content-Length 非法",
        ) from error
    if declared_size < 0:
        raise SafeRemoteDownloadError("远程 URL Content-Length 非法")
    if declared_size > max_bytes:
        raise SafeRemoteDownloadError(
            f"远程内容超过 {max_bytes} bytes 限制",
        )
    return declared_size


@dataclass(slots=True)
class SafeRemoteStream:
    """One validated response whose body remains bounded while iterating."""

    response: httpx.Response
    final_url: str
    declared_size: int | None
    max_bytes: int
    _bytes_read: int = 0

    @property
    def media_type(self) -> str:
        return (
            self.response.headers.get("content-type", "").split(";", 1)[0]
            or "application/octet-stream"
        )

    def iter_raw(self) -> Iterator[bytes]:
        for chunk in self.response.iter_raw():
            self._bytes_read += len(chunk)
            if self._bytes_read > self.max_bytes:
                raise SafeRemoteDownloadError(
                    f"远程内容超过 {self.max_bytes} bytes 限制",
                )
            yield chunk


@contextmanager
def open_safe_remote_stream(
    url: str,
    *,
    max_bytes: int,
    timeout: float | httpx.Timeout,
    max_redirects: int = DEFAULT_MAX_REMOTE_REDIRECTS,
) -> Iterator[SafeRemoteStream]:
    """Open one public, identity-encoded response with bounded redirects."""

    if max_bytes <= 0:
        raise SafeRemoteDownloadError("远程下载大小限制必须大于 0")
    if max_redirects < 0:
        raise SafeRemoteDownloadError("远程下载重定向限制不能为负数")
    current = validate_public_remote_url(url)
    with httpx.Client(
        follow_redirects=False,
        timeout=timeout,
        trust_env=False,
        headers={"Accept": "*/*", "Accept-Encoding": "identity"},
    ) as client:
        for redirect_index in range(max_redirects + 1):
            with client.stream("GET", current) as response:
                validate_response_peer(response)
                if response.status_code in _REDIRECT_STATUSES:
                    if redirect_index >= max_redirects:
                        raise SafeRemoteDownloadError(
                            "远程 URL 重定向次数超过限制",
                        )
                    location = response.headers.get("location")
                    if not location:
                        raise SafeRemoteDownloadError(
                            "远程 URL 重定向缺少 Location",
                        )
                    current = validate_public_remote_url(
                        urljoin(current, location),
                    )
                    continue
                response.raise_for_status()
                if response.headers.get(
                    "content-encoding",
                    "identity",
                ).casefold() not in {"", "identity"}:
                    raise SafeRemoteDownloadError(
                        "远程 URL 未返回 identity 原始字节",
                    )
                remote = SafeRemoteStream(
                    response=response,
                    final_url=current,
                    declared_size=declared_content_length(
                        response,
                        max_bytes=max_bytes,
                    ),
                    max_bytes=max_bytes,
                )
                yield remote
                return
    raise SafeRemoteDownloadError("远程 URL 未产生响应")


def safe_download_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: float | httpx.Timeout,
) -> bytes:
    """Download a small public HTTP(S) resource into bounded memory."""

    with open_safe_remote_stream(
        url,
        max_bytes=max_bytes,
        timeout=timeout,
    ) as remote:
        content = b"".join(remote.iter_raw())
    if not content:
        raise SafeRemoteDownloadError("远程 URL 返回了空内容")
    return content


def _resolved_public_endpoint(
    url: str,
    *,
    resolver: Any = socket.getaddrinfo,
) -> tuple[str, int, str]:
    """Return ``(host, port, validated_ip)`` for one already-validated URL."""

    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        try:
            records = resolver(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as error:
            raise SafeRemoteDownloadError("远程 URL 主机无法解析") from error
        addresses = [str(record[4][0]) for record in records if record[4]]
        if not addresses:
            raise SafeRemoteDownloadError("远程 URL 主机无法解析") from None
        for address in addresses:
            require_public_ip(address)
        return host, port, addresses[0]
    require_public_ip(host)
    return host, port, host


def safe_curl_download_to_file(
    url: str,
    destination: str | Path,
    *,
    max_bytes: int,
    timeout_seconds: float,
    connect_timeout_seconds: float = 15.0,
    max_redirects: int = DEFAULT_MAX_REMOTE_REDIRECTS,
    resolver: Any = socket.getaddrinfo,
    runner: Any = subprocess.run,
) -> tuple[int, str, str]:
    """Download via a curl subprocess under the same SSRF/size policy.

    Network fallback for stacks where httpx cannot establish the route
    (observed with DashScope OSS result URLs) while the system curl can.
    Redirects are followed in Python so every hop re-runs URL validation.
    For hostname URLs the connection is pinned to a pre-validated resolved
    IP through ``--resolve``, keeping DNS rebinding out of the curl hop;
    IP-literal URLs are already validated by ``require_public_ip`` and
    curl connects to that literal directly.

    Returns ``(size_bytes, media_type, final_url)``; the partial file is
    removed on every failure.
    """

    if max_bytes <= 0:
        raise SafeRemoteDownloadError("远程下载大小限制必须大于 0")
    if shutil.which("curl") is None:
        raise SafeRemoteDownloadError("系统 curl 不可用，无法回退下载")
    path = Path(destination)
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    current = validate_public_remote_url(url, resolver=resolver)
    try:
        for _ in range(max_redirects + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SafeRemoteDownloadError("远程下载超过总 deadline")
            host, port, address = _resolved_public_endpoint(
                current,
                resolver=resolver,
            )
            command = [
                "curl",
                "--silent",
                "--show-error",
                "--globoff",
                "--noproxy",
                "*",
                "--max-redirs",
                "0",
                "--proto",
                "=http,https",
                "--connect-timeout",
                str(int(max(1, connect_timeout_seconds))),
                "--max-time",
                str(int(max(1, remaining))),
                "--max-filesize",
                str(max_bytes),
                "--header",
                "Accept: */*",
                "--header",
                "Accept-Encoding: identity",
                "--resolve",
                f"{host}:{port}:{address}",
                "--output",
                str(path),
                "--write-out",
                "%{http_code}\t%{content_type}\t%{redirect_url}",
                "--",
                current,
            ]
            completed = runner(
                command,
                capture_output=True,
                text=True,
                timeout=max(1.0, remaining) + 10.0,
                check=False,
            )
            fields = (completed.stdout or "").strip().split("\t")
            status = int(fields[0] or 0) if fields and fields[0] else 0
            media_type = fields[1] if len(fields) > 1 else ""
            redirect_url = fields[2] if len(fields) > 2 else ""
            if status in _REDIRECT_STATUSES:
                if not redirect_url:
                    raise SafeRemoteDownloadError(
                        "远程 URL 重定向缺少 Location",
                    )
                current = validate_public_remote_url(
                    urljoin(current, redirect_url),
                    resolver=resolver,
                )
                path.unlink(missing_ok=True)
                continue
            if completed.returncode != 0:
                detail = (completed.stderr or "").strip()[:200]
                raise SafeRemoteDownloadError(
                    f"curl 下载失败 (exit={completed.returncode}): {detail}",
                )
            if not 200 <= status < 300:
                raise SafeRemoteDownloadError(
                    f"远程 URL 返回 HTTP {status}",
                )
            size = path.stat().st_size if path.exists() else 0
            if size == 0:
                raise SafeRemoteDownloadError("远程 URL 返回了空内容")
            if size > max_bytes:
                raise SafeRemoteDownloadError(
                    f"远程内容超过 {max_bytes} bytes 限制",
                )
            return (
                size,
                (media_type or "").split(";", 1)[0]
                or "application/octet-stream",
                current,
            )
        raise SafeRemoteDownloadError("远程 URL 重定向次数超过限制")
    except subprocess.TimeoutExpired as error:
        raise SafeRemoteDownloadError("curl 下载超时") from error
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def safe_download_to_file(
    url: str,
    destination: str | Path,
    *,
    max_bytes: int,
    timeout: float | httpx.Timeout,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> tuple[int, str, str]:
    """Stream a large public HTTP(S) resource into an explicit local file.

    Returns ``(size_bytes, media_type, final_url)``. A partial destination is
    removed on every failure.  ``on_progress``, when given, is invoked on the
    calling thread after each received chunk with ``(received, total)`` where
    ``total`` is the declared Content-Length (``None`` when absent); receivers
    are responsible for their own throttling and must treat errors as fatal.
    """

    path = Path(destination)
    size = 0
    try:
        with path.open("wb") as output:
            with open_safe_remote_stream(
                url,
                max_bytes=max_bytes,
                timeout=timeout,
            ) as remote:
                for chunk in remote.iter_raw():
                    output.write(chunk)
                    size += len(chunk)
                    if on_progress is not None:
                        on_progress(size, remote.declared_size)
                media_type = remote.media_type
                final_url = remote.final_url
        if size == 0:
            path.unlink(missing_ok=True)
            raise SafeRemoteDownloadError("远程 URL 返回了空内容")
        return size, media_type, final_url
    except BaseException:
        path.unlink(missing_ok=True)
        raise


__all__ = [
    "DEFAULT_MAX_REMOTE_REDIRECTS",
    "SafeRemoteDownloadError",
    "SafeRemoteStream",
    "declared_content_length",
    "open_safe_remote_stream",
    "require_public_ip",
    "safe_curl_download_to_file",
    "safe_download_bytes",
    "safe_download_to_file",
    "validate_public_remote_url",
    "validate_response_peer",
]
