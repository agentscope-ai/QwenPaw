# -*- coding: utf-8 -*-
"""Regression tests for legacy session message compatibility shims."""

from __future__ import annotations

import os

import pytest
from agentscope.message import DataBlock, URLSource

from qwenpaw._compat.message import _ensure_url_scheme, msg_from_dict


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\alice\real.png",
        r"\\server\share\real.png",
        "C:/Users/alice/real.png",
        "/tmp/real.png",
        r"file://C:\files\real.png",
        r"file://\\server\share\real.png",
        r".\dir\real.png",
        r"..\dir\real.png",
        r"/tmp/invoice\real.png",
    ],
)
@pytest.mark.parametrize("hint_key", [None, "filename", "name"])
def test_legacy_file_name_handles_cross_platform_paths(path, hint_key):
    block = {"type": "file", "source": {"type": "url", "url": path}}
    if hint_key:
        block[hint_key] = "report.pdf"
    msg = msg_from_dict(
        {"name": "user", "role": "user", "content": [block]},
    )
    filename = (
        "report.pdf"
        if hint_key
        else (
            r"invoice\real.png"
            if path.startswith("/tmp/invoice")
            else "real.png"
        )
    )
    assert msg.content[0].text == f"File '{filename}' is available at: {path}"


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


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX permits backslashes in names",
)
def test_legacy_relative_posix_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    filename = r"invoice\real.png"
    (tmp_path / filename).write_bytes(b"file content")
    msg = msg_from_dict(
        {
            "name": "user",
            "role": "user",
            "content": [
                {
                    "type": "file",
                    "source": {"type": "url", "url": filename},
                },
            ],
        },
    )
    assert (
        msg.content[0].text == f"File '{filename}' is available at: {filename}"
    )
