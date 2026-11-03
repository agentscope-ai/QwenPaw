# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from services.runtime_files import safe_remote_download
from services.runtime_files.safe_remote_download import (
    SafeRemoteDownloadError,
    safe_curl_download_to_file,
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


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> dict:
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


def _download(url: str, max_bytes: int) -> bytes:
    return safe_download_bytes(url, max_bytes=max_bytes, timeout=5.0)


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
        _download("https://public.example/image.png", max_bytes=6) == b"abcdef"
    )
    assert observed["follow_redirects"] is False
    assert observed["trust_env"] is False
    assert observed["headers"]["Accept-Encoding"] == "identity"


def test_safe_download_bytes_enforces_max_bytes_during_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunked = _Chunks(b"123", b"456", b"must-not-be-read")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=chunked)

    _install_transport(monkeypatch, handler)

    with pytest.raises(SafeRemoteDownloadError, match="5 bytes"):
        _download("https://public.example/large.bin", max_bytes=5)
    assert chunked.yielded == 2


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
        _download("https://public.example/start", max_bytes=1024)
    assert seen == [
        "https://public.example/start",
        "http://127.0.0.1/metadata",
    ]


def _public_resolver(*_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def _curl(url: str, destination, runner):
    return safe_curl_download_to_file(
        url,
        destination,
        max_bytes=1024,
        timeout_seconds=30,
        resolver=_public_resolver,
        runner=runner,
    )


def test_curl_download_pins_validated_ip_and_writes_file(tmp_path) -> None:
    destination = tmp_path / "video.mp4"
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(command)
        destination.write_bytes(b"payload")
        return SimpleNamespace(
            returncode=0,
            stdout="200\tvideo/mp4\t",
            stderr="",
        )

    size, media_type, final_url = _curl(
        "https://public.example/video.mp4",
        destination,
        runner,
    )

    assert (size, media_type) == (7, "video/mp4")
    assert final_url == "https://public.example/video.mp4"
    assert destination.read_bytes() == b"payload"
    command = commands[0]
    assert command[0] == "curl"
    assert (
        command[command.index("--resolve") + 1]
        == "public.example:443:93.184.216.34"
    )
    assert command[command.index("--max-redirs") + 1] == "0"
    assert command[command.index("--max-filesize") + 1] == "1024"
    assert "--noproxy" in command


def test_curl_download_maps_failures_and_removes_partial_file(
    tmp_path,
) -> None:
    destination = tmp_path / "file.bin"
    url = "https://public.example/file.bin"

    def failing_runner(_command, **_kwargs):
        destination.write_bytes(b"partial")
        return SimpleNamespace(
            returncode=7,
            stdout="000\t\t",
            stderr="Failed to connect",
        )

    with pytest.raises(SafeRemoteDownloadError, match="curl 下载失败"):
        _curl(url, destination, failing_runner)
    assert not destination.exists()
