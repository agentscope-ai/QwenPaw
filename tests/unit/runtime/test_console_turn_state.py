# -*- coding: utf-8 -*-
"""Regression coverage for damaged history image repair."""

import nturl2path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from qwenpaw.runtime import console_turn_state

pytestmark = [pytest.mark.unit, pytest.mark.p1]


def _history(*urls):
    return {
        "state": {
            "context": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"media_type": "image/png", "url": url},
                        }
                        for url in urls
                    ],
                },
            ],
        },
    }


def test_repair_preserves_valid_remote_and_missing_images(tmp_path):
    # Literal percent escapes must not be decoded twice.
    damaged = tmp_path / "broken %20 图片.png"
    damaged.write_bytes(b"not an image")
    valid = tmp_path / "valid.png"
    Image.new("RGB", (1, 1)).save(valid)
    data = _history(
        damaged.as_uri(),
        valid.as_uri(),
        "https://example.com/image.png",
        (tmp_path / "missing.png").as_uri(),
    )
    message = data["state"]["context"][0]
    original = list(message["content"])

    console_turn_state.repair_invalid_history_images(data)
    console_turn_state.repair_invalid_history_images(data)

    assert message["content"][0]["type"] == "text"
    assert message["content"][1:] == original[1:]
    assert message["metadata"]["qwenpaw_invalid_images"] == original[:1]
    assert damaged.read_bytes() == b"not an image"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file:///C:/tmp/a.png", "C:\\tmp\\a.png"),
        ("file://localhost/C:/tmp/a.png", "C:\\tmp\\a.png"),
        ("file://server/share/a.png", "\\\\server\\share\\a.png"),
        ("file:////server/share/a.png", "\\\\server\\share\\a.png"),
        ("file:///C:/tmp/a%20b%2520.png", "C:\\tmp\\a b%20.png"),
        ("file:///C:/tmp/%E5%9B%BE.png", "C:\\tmp\\图.png"),
    ],
)
def test_windows_file_uri_reaches_image_validation(monkeypatch, url, expected):
    # Exercise the Windows stdlib converter even on POSIX test hosts.
    monkeypatch.setattr(
        console_turn_state, "url2pathname", nturl2path.url2pathname
    )
    path_factory = MagicMock()
    path_factory.return_value.is_file.return_value = True
    monkeypatch.setattr(console_turn_state, "Path", path_factory)
    image_open = MagicMock(side_effect=OSError("damaged image"))
    monkeypatch.setattr(Image, "open", image_open)
    data = _history(url)

    console_turn_state.repair_invalid_history_images(data)

    path_factory.assert_called_once_with(expected)
    image_open.assert_called_once_with(path_factory.return_value)
    message = data["state"]["context"][0]
    assert message["content"][0]["type"] == "text"
    assert (
        message["metadata"]["qwenpaw_invalid_images"][0]["source"]["url"]
        == url
    )
