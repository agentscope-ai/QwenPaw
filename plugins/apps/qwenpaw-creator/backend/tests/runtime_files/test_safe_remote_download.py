# -*- coding: utf-8 -*-
from __future__ import annotations

import httpx
import pytest

from services.runtime_files import safe_remote_download
from services.runtime_files.safe_remote_download import (
    SafeRemoteDownloadError,
    safe_download_bytes,
    validate_public_remote_url,
    validate_response_peer,
)


class _Chunks(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks
        self.yielded = 0

    def __iter__(self):
        for chunk in self.chunks:
            self.yielded += 1
            yield chunk


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> dict:
    observed: dict = {}
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(**kwargs):
        observed.update(kwargs)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(safe_remote_download.httpx, "Client", client_factory)
    monkeypatch.setattr(
        safe_remote_download,
        "validate_public_remote_url",
        lambda value: value,
    )
    monkeypatch.setattr(
        safe_remote_download,
        "validate_response_peer",
        lambda _response: None,
    )
    return observed


def test_public_url_validation_rejects_private_literal_and_dns_result() -> (
    None
):
    with pytest.raises(SafeRemoteDownloadError, match="私有或保留网络"):
        validate_public_remote_url("http://127.0.0.1/metadata")

    def private_resolver(*_args, **_kwargs):
        return [(2, 1, 6, "", ("169.254.169.254", 80))]

    with pytest.raises(SafeRemoteDownloadError, match="私有或保留网络"):
        validate_public_remote_url(
            "http://metadata.example/latest",
            resolver=private_resolver,
        )


def test_connected_peer_is_checked_independently_from_dns() -> None:
    class NetworkStream:
        def get_extra_info(self, name):
            assert name == "server_addr"
            return ("10.0.0.9", 443)

    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://public.example/media"),
        extensions={"network_stream": NetworkStream()},
    )

    with pytest.raises(SafeRemoteDownloadError, match="私有或保留网络"):
        validate_response_peer(response)


def test_safe_download_bytes_disables_redirects_proxies_and_compression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "6"},
            stream=_Chunks(b"abc", b"def"),
        )

    observed = _install_transport(monkeypatch, handler)

    assert (
        safe_download_bytes(
            "https://public.example/image.png",
            max_bytes=6,
            timeout=5.0,
        )
        == b"abcdef"
    )
    assert observed["follow_redirects"] is False
    assert observed["trust_env"] is False
    assert observed["headers"]["Accept-Encoding"] == "identity"


def test_safe_download_bytes_stops_chunked_body_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _Chunks(b"123", b"456", b"must-not-be-read")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    _install_transport(monkeypatch, handler)

    with pytest.raises(SafeRemoteDownloadError, match="5 bytes"):
        safe_download_bytes(
            "https://public.example/large.bin",
            max_bytes=5,
            timeout=5.0,
        )
    assert stream.yielded == 2


def test_safe_download_bytes_revalidates_each_redirect_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def validate(value: str) -> str:
        seen.append(value)
        if value.startswith("http://127.0.0.1"):
            raise SafeRemoteDownloadError("redirect target is private")
        return value

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/metadata"},
        )

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(
        safe_remote_download,
        "validate_public_remote_url",
        validate,
    )

    with pytest.raises(SafeRemoteDownloadError, match="private"):
        safe_download_bytes(
            "https://public.example/start",
            max_bytes=1024,
            timeout=5.0,
        )
    assert seen == [
        "https://public.example/start",
        "http://127.0.0.1/metadata",
    ]


def test_safe_download_bytes_rejects_declared_oversize_before_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _Chunks(b"must-not-be-read")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "6"},
            stream=stream,
        )

    _install_transport(monkeypatch, handler)

    with pytest.raises(SafeRemoteDownloadError, match="5 bytes"):
        safe_download_bytes(
            "https://public.example/large.bin",
            max_bytes=5,
            timeout=5.0,
        )
    assert stream.yielded == 0
