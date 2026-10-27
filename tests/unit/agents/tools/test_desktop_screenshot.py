# -*- coding: utf-8 -*-
"""Tests for desktop_screenshot cancel cleanup."""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import base64
from io import BytesIO
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import Base64Source
from PIL import Image

from qwenpaw.agents.tools.desktop_screenshot import (
    _tool_ok,
    _capture_macos_screencapture,
    desktop_screenshot,
)
from qwenpaw.agents.tools.send_file import send_file_to_user
from qwenpaw.agents.utils.image_freezing import freeze_local_images
from qwenpaw.providers.capping_formatter import MAX_INLINE_MEDIA_BYTES


@pytest.mark.asyncio
async def test_macos_screencapture_kills_proc_on_cancel(tmp_path):
    """Cancel/timeout must terminate the interactive screencapture process."""
    proc = MagicMock()
    proc.returncode = None
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)

    async def _raise_cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError()

    with (
        patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ),
        patch(
            "qwenpaw.tool_calls.cancellable_wait",
            new=_raise_cancelled,
        ),
    ):
        result = await _capture_macos_screencapture(
            str(tmp_path / "shot.png"),
            capture_window=True,
        )

    assert "timed out" in result.content[0].text.lower()
    proc.kill.assert_called_once()
    proc.wait.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("oversized", [False, True])
async def test_desktop_screenshot_freezes_local_image(tmp_path, oversized):
    """A captured screenshot is immutable before tool return."""
    image_path = tmp_path / "desktop.png"
    original = b""

    def capture(path):
        nonlocal original
        if oversized:
            Image.frombytes(
                "RGB",
                (1000, 800),
                random.Random(0).randbytes(1000 * 800 * 3),
            ).save(path)
        else:
            Image.new("RGB", (2, 2), color="red").save(path)
        original = image_path.read_bytes()
        return _tool_ok(path, f"Desktop screenshot saved to {path}")

    with (
        patch("platform.system", return_value="Linux"),
        patch(
            "qwenpaw.agents.tools.desktop_screenshot._capture_mss",
            side_effect=capture,
        ),
    ):
        result = await desktop_screenshot(str(image_path))

    assert isinstance(result.content[0].source, Base64Source)
    first_data = result.content[0].source.data
    assert image_path.read_bytes() == original
    preview = base64.b64decode(first_data)
    assert len(preview) <= MAX_INLINE_MEDIA_BYTES
    if oversized:
        assert len(original) > MAX_INLINE_MEDIA_BYTES
        with Image.open(BytesIO(preview)) as image:
            assert image.width < 1000
            assert image.height < 800
    else:
        assert preview == original

    # Sending the same original must also retain an immutable image block.
    sent = await send_file_to_user(str(image_path))
    freeze_local_images(sent)
    assert sent.content[0].source.data == first_data
    assert image_path.read_bytes() == original
    Image.new("RGB", (2, 2), color="blue").save(image_path)
    assert result.content[0].source.data == first_data
    assert sent.content[0].source.data == first_data
