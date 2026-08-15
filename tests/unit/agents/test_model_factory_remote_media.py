# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Remote media preparation must degrade failures, never raise.

A dead media URL in history is a content problem, not a model failure.
If ``_prepare_media_sources`` let the HTTP error propagate, the model
error policy would classify a 404 as ``model_not_found`` and burn the
whole fallback chain on every turn.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from agentscope.formatter import AnthropicChatFormatter

from qwenpaw.agents import model_factory


def _install_mock_transport(monkeypatch, handler) -> None:
    """Route model_factory's httpx clients through a mock transport."""
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real_client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(model_factory.httpx, "AsyncClient", factory)


@pytest.mark.parametrize("status_code", [401, 403, 404, 500])
async def test_download_degrades_http_error_to_placeholder(
    monkeypatch,
    status_code: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    _install_mock_transport(monkeypatch, handler)

    prepared = await model_factory._download_remote_media(
        "https://example.invalid/expired.png",
        max_bytes=1024,
    )

    assert prepared.exists is False
    assert prepared.encoded is None


async def test_download_degrades_network_error_to_placeholder(
    monkeypatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    _install_mock_transport(monkeypatch, handler)

    prepared = await model_factory._download_remote_media(
        "https://example.invalid/gone.png",
        max_bytes=1024,
    )

    assert prepared.exists is False


async def test_download_success_still_encodes(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"pixels")

    _install_mock_transport(monkeypatch, handler)

    prepared = await model_factory._download_remote_media(
        "https://example.invalid/live.png",
        max_bytes=1024,
    )

    assert prepared.exists is True
    assert prepared.size == len(b"pixels")
    assert prepared.encoded is not None


async def test_oversize_chunked_download_does_not_fake_size(
    monkeypatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Strip content-length so size is only discovered while reading.
        response = httpx.Response(200, content=b"x" * 64)
        del response.headers["content-length"]
        return response

    _install_mock_transport(monkeypatch, handler)

    prepared = await model_factory._download_remote_media(
        "https://example.invalid/huge.bin",
        max_bytes=16,
    )

    assert prepared.exists is True
    assert prepared.encoded is None
    assert prepared.size > 16
    assert prepared.size_known is False


async def test_prepare_media_sources_replaces_dead_url_with_text(
    monkeypatch,
) -> None:
    """The 404 must surface as a placeholder block, not an exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    _install_mock_transport(monkeypatch, handler)

    content = [
        {
            "type": "image",
            "source": {
                "type": "url",
                "url": "https://example.invalid/expired.png",
            },
        },
    ]
    msg = SimpleNamespace(content=content)

    await model_factory._prepare_media_sources(
        [msg],
        AnthropicChatFormatter,
        max_bytes=1024,
    )

    block = content[0]
    assert getattr(block, "type", None) == "text"
    assert "download failed" in block.text


def test_placeholder_texts_distinguish_local_and_remote() -> None:
    items = [object(), object()]
    local_ref = model_factory._MediaReference(
        items=items,
        index=0,
        block={},
        source={},
        kind="image",
    )
    remote_ref = model_factory._MediaReference(
        items=items,
        index=1,
        block={},
        source={},
        kind="image",
    )
    missing = model_factory._LocalMediaRead(False, 0, None)

    model_factory._replace_media_reference(
        local_ref,
        missing,
        "",
        AnthropicChatFormatter,
        local=True,
        max_bytes=1024,
    )
    model_factory._replace_media_reference(
        remote_ref,
        missing,
        "",
        AnthropicChatFormatter,
        local=False,
        max_bytes=1024,
    )

    assert "file deleted from disk" in items[0].text
    assert "download failed" in items[1].text
