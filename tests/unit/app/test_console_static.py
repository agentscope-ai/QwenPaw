# -*- coding: utf-8 -*-
"""Console static asset cache and compression behavior."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from starlette.types import Message, Scope

from qwenpaw.app.console_static import ASSET_CACHE_CONTROL, ConsoleAssetFiles


def _scope(
    path: str,
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    extensions: dict | None = None,
) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "extensions": extensions or {},
    }


async def _request(app: ConsoleAssetFiles, scope: Scope) -> list[Message]:
    messages: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    await app(scope, receive, send)
    return messages


def _response_headers(messages: list[Message]) -> dict[str, str]:
    start = next(
        message
        for message in messages
        if message["type"] == "http.response.start"
    )
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start["headers"]
    }


def _response_body(messages: list[Message]) -> bytes:
    return b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )


@pytest.fixture(name="assets")
def assets_fixture(tmp_path: Path) -> tuple[ConsoleAssetFiles, bytes, bytes]:
    javascript = b"const value = 'compressible';\n" * 400
    image = b"\x89PNG\r\n\x1a\n" + (b"not-compressible" * 400)
    (tmp_path / "app-12345678.js").write_bytes(javascript)
    (tmp_path / "logo-12345678.png").write_bytes(image)
    return ConsoleAssetFiles(str(tmp_path)), javascript, image


async def test_compresses_text_assets_and_sets_immutable_cache(
    assets: tuple[ConsoleAssetFiles, bytes, bytes],
) -> None:
    app, javascript, _ = assets
    messages = await _request(
        app,
        _scope(
            "/app-12345678.js",
            headers=[(b"accept-encoding", b"br, gzip")],
        ),
    )

    headers = _response_headers(messages)
    assert headers["cache-control"] == ASSET_CACHE_CONTROL
    assert headers["content-encoding"] == "gzip"
    assert headers["vary"] == "Accept-Encoding"
    assert gzip.decompress(_response_body(messages)) == javascript


async def test_forces_streaming_when_server_advertises_pathsend(
    assets: tuple[ConsoleAssetFiles, bytes, bytes],
) -> None:
    app, javascript, _ = assets
    messages = await _request(
        app,
        _scope(
            "/app-12345678.js",
            headers=[(b"accept-encoding", b"gzip")],
            extensions={"http.response.pathsend": {}},
        ),
    )

    assert not any(
        message["type"] == "http.response.pathsend" for message in messages
    )
    assert gzip.decompress(_response_body(messages)) == javascript


@pytest.mark.parametrize(
    "accept_encoding",
    [b"identity", b"gzip;q=0", b"br"],
)
async def test_respects_clients_that_do_not_accept_gzip(
    assets: tuple[ConsoleAssetFiles, bytes, bytes],
    accept_encoding: bytes,
) -> None:
    app, javascript, _ = assets
    messages = await _request(
        app,
        _scope(
            "/app-12345678.js",
            headers=[(b"accept-encoding", accept_encoding)],
        ),
    )

    headers = _response_headers(messages)
    assert "content-encoding" not in headers
    assert headers["vary"] == "Accept-Encoding"
    assert _response_body(messages) == javascript


async def test_does_not_compress_binary_assets(
    assets: tuple[ConsoleAssetFiles, bytes, bytes],
) -> None:
    app, _, image = assets
    messages = await _request(
        app,
        _scope(
            "/logo-12345678.png",
            headers=[(b"accept-encoding", b"gzip")],
        ),
    )

    headers = _response_headers(messages)
    assert headers["cache-control"] == ASSET_CACHE_CONTROL
    assert "content-encoding" not in headers
    assert "vary" not in headers
    assert _response_body(messages) == image


async def test_range_requests_are_not_compressed(
    assets: tuple[ConsoleAssetFiles, bytes, bytes],
) -> None:
    app, javascript, _ = assets
    messages = await _request(
        app,
        _scope(
            "/app-12345678.js",
            headers=[
                (b"accept-encoding", b"gzip"),
                (b"range", b"bytes=0-31"),
            ],
        ),
    )

    headers = _response_headers(messages)
    assert headers["cache-control"] == ASSET_CACHE_CONTROL
    assert "content-encoding" not in headers
    assert headers["content-range"].startswith("bytes 0-31/")
    assert _response_body(messages) == javascript[:32]


async def test_conditional_request_preserves_cache_policy(
    assets: tuple[ConsoleAssetFiles, bytes, bytes],
) -> None:
    app, _, _ = assets
    initial = await _request(app, _scope("/app-12345678.js"))
    etag = _response_headers(initial)["etag"]

    messages = await _request(
        app,
        _scope(
            "/app-12345678.js",
            headers=[(b"if-none-match", etag.encode())],
        ),
    )

    start = next(
        message
        for message in messages
        if message["type"] == "http.response.start"
    )
    assert start["status"] == 304
    headers = _response_headers(messages)
    assert headers["cache-control"] == ASSET_CACHE_CONTROL
    assert headers["vary"] == "Accept-Encoding"
