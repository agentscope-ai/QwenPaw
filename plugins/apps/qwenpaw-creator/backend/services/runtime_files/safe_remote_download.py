# -*- coding: utf-8 -*-
"""SSRF-safe, bounded HTTP(S) download primitives.

Every caller uses the same URL, DNS, connected-peer, redirect, compression and
size policy. Small consumers may materialize bytes; large-media consumers keep
the validated response streaming into their own staging/file boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import ipaddress
import logging
from pathlib import Path
import socket
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
    try:
        require_public_ip(host)
    except SafeRemoteDownloadError:
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
            raise
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


def safe_download_to_file(
    url: str,
    destination: str | Path,
    *,
    max_bytes: int,
    timeout: float | httpx.Timeout,
) -> tuple[int, str, str]:
    """Stream a large public HTTP(S) resource into an explicit local file.

    Returns ``(size_bytes, media_type, final_url)``. A partial destination is
    removed on every failure.
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
    "safe_download_bytes",
    "safe_download_to_file",
    "validate_public_remote_url",
    "validate_response_peer",
]
