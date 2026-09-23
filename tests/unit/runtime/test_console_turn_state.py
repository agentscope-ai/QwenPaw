# -*- coding: utf-8 -*-
"""Regression coverage for damaged history image repair."""

from types import SimpleNamespace
from unittest.mock import MagicMock
import nturl2path

import pytest
from PIL import Image

from qwenpaw.exceptions import ConfigurationException
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
        console_turn_state,
        "url2pathname",
        nturl2path.url2pathname,
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


# ---------------------------------------------------------------------------
# stamp_console_turn
# ---------------------------------------------------------------------------

_CLIENT_ID = "client-1"


def _console_turn(client_id=_CLIENT_ID):
    return {
        "state": {
            "context": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "hi"}],
                    "metadata": {"qwenpaw_client_message_id": client_id},
                },
            ],
        },
    }


def _console_request(client_id=_CLIENT_ID):
    return SimpleNamespace(
        channel="console",
        input=[
            SimpleNamespace(metadata={"qwenpaw_client_message_id": client_id})
        ],
    )


def _terminal(data):
    metadata = data["state"]["context"][0]["metadata"]
    return metadata["qwenpaw_turn_state"]


def test_stamp_keeps_the_stable_error_code():
    data = _console_turn()
    error = ConfigurationException(
        "No active model configured; pick one in the UI",
        config_key="active_model",
        error_code="MODEL_NOT_CONFIGURED",
    )

    console_turn_state.stamp_console_turn(
        data,
        _console_request(),
        "failed",
        error,
    )

    # The persisted terminal must agree with the streamed one, so a reload
    # still resolves the same code instead of the exception class name.
    assert _terminal(data) == {
        "status": "failed",
        "error": {
            "code": "MODEL_NOT_CONFIGURED",
            "message": "No active model configured; pick one in the UI",
        },
    }


def test_stamp_falls_back_to_the_exception_class():
    data = _console_turn()

    console_turn_state.stamp_console_turn(
        data,
        _console_request(),
        "failed",
        ValueError("boom"),
    )

    assert _terminal(data)["error"]["code"] == "ValueError"


def test_stamp_records_a_cancel_without_an_error():
    data = _console_turn()

    console_turn_state.stamp_console_turn(data, _console_request(), "canceled")

    assert _terminal(data) == {"status": "canceled"}


def test_stamp_ignores_non_console_channels():
    data = _console_turn()
    request = _console_request()
    request.channel = "feishu"

    console_turn_state.stamp_console_turn(data, request, "failed")

    assert "qwenpaw_turn_state" not in (
        data["state"]["context"][0]["metadata"]
    )
