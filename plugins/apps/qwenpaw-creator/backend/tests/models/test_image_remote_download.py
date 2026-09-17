# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from models.image import base as image_base


def test_remote_image_uses_bounded_curl_when_httpx_transport_cannot_reach_oss(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    client_options: list[dict] = []
    curl_calls: list[tuple[str, str]] = []

    class UnreachableHttpxClient:
        def __init__(self, **kwargs):
            client_options.append(dict(kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str):
            request = httpx.Request("GET", url)
            raise httpx.ConnectError("OSS route unavailable", request=request)

    def curl_download(url: str, local_path: str) -> None:
        curl_calls.append((url, local_path))
        Path(local_path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"i" * 12_000)

    monkeypatch.setattr(
        image_base.httpx,
        "AsyncClient",
        UnreachableHttpxClient,
    )
    monkeypatch.setattr(image_base, "download_remote_file", curl_download)

    result = asyncio.run(
        image_base.download_remote_image(
            "https://dashscope-result.example/image.png?Expires=1",
            "qwen-image-2.0-pro",
        ),
    )

    assert client_options == [{"timeout": 60, "follow_redirects": True}]
    assert len(curl_calls) == 1
    assert result.startswith("/generated/task-work/unscoped/images/img_")
    assert result.endswith(".png")
    assert not Path(curl_calls[0][1]).exists()
