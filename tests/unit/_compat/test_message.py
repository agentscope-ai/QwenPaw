# -*- coding: utf-8 -*-
"""Regression tests for legacy session message compatibility shims."""

from __future__ import annotations

from agentscope.message import DataBlock, URLSource

from qwenpaw._compat.message import _ensure_url_scheme, msg_from_dict


def test_ensure_url_scheme_unc_path():
    assert _ensure_url_scheme(r"\\server\share\image.png") == (
        "file://server/share/image.png"
    )


def test_ensure_url_scheme_unquotes_percent_encoded_path():
    assert _ensure_url_scheme(
        "/app/working/media/wecom_%E4%BC%81%E4%B8%9A%E5%BE%AE%E4%BF%A1.png",
    ).endswith("wecom_企业微信.png")


def test_msg_from_dict_legacy_image_with_local_path_source(tmp_path):
    """Legacy image blocks with local paths must not break session load."""
    image = tmp_path / "wecom_企业微信截图.png"
    image.write_bytes(b"fake-png")

    msg = msg_from_dict(
        {
            "id": "m1",
            "name": "user",
            "role": "user",
            "timestamp": "2026-05-29 01:32:00.000",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "url", "url": str(image)},
                },
            ],
        },
    )
    block = msg.content[0]
    assert isinstance(block, DataBlock)
    assert isinstance(block.source, URLSource)
    assert str(block.source.url).startswith("file://")
