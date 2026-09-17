# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import io

from PIL import Image

from models.image.dashscope_provider import DashScopeImageModel


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color="blue").save(output, format="PNG")
    return output.getvalue()


def test_dashscope_skips_corrupt_local_reference(
    monkeypatch,
    tmp_path,
) -> None:
    corrupt = tmp_path / "corrupt.jpg"
    corrupt.write_bytes(b"not-an-image")
    valid = tmp_path / "valid.png"
    valid.write_bytes(_png_bytes())

    uploaded: list[str] = []

    async def fake_upload(
        content: bytes,
        filename: str,
        *,
        api_key: str,
        model_name: str,
    ) -> str:
        assert content == _png_bytes()
        assert filename == "valid.png"
        assert api_key == "test"
        assert model_name == "qwen-image-2.0-pro"
        uploaded.append(filename)
        return "oss://dashscope-instant/valid.png"

    monkeypatch.setattr(
        "models.image.dashscope_provider.upload_reference_bytes_to_dashscope_temp",
        fake_upload,
    )
    model = DashScopeImageModel(
        model_name="qwen-image-2.0-pro",
        api_key="test",
        base_url="https://dashscope.test/generate",
        timeout=30,
    )

    body = asyncio.run(
        model._build_body(
            "portrait",
            "1:1",
            [corrupt.as_uri(), valid.as_uri()],
        ),
    )

    assert uploaded == ["valid.png"]
    assert body["input"]["messages"][0]["content"] == [
        {"image": "oss://dashscope-instant/valid.png"},
        {"text": "portrait"},
    ]
