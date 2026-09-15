# -*- coding: utf-8 -*-
"""Tests for the desktop screenshot file-result contract."""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import Base64Source, ToolResultState, URLSource
from PIL import Image

from qwenpaw.agents.tools.desktop_screenshot import (
    _capture_macos_screencapture,
    _tool_ok,
    desktop_screenshot,
)


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
    assert result.state == ToolResultState.ERROR
    proc.kill.assert_called_once()
    proc.wait.assert_awaited()


@pytest.mark.asyncio
async def test_desktop_screenshot_freezes_local_image(tmp_path):
    """A captured screenshot is immutable before tool return."""
    image_path = tmp_path / "desktop.png"

    def capture(path):
        Image.new("RGB", (2, 2), color="red").save(path)
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
    Image.new("RGB", (2, 2), color="blue").save(image_path)
    assert result.content[0].source.data == first_data


@pytest.mark.asyncio
async def test_desktop_screenshot_resolves_relative_output_path(tmp_path):
    """Relative outputs follow the shared project/workspace path contract."""
    captured_path = None

    def capture(path):
        nonlocal captured_path
        captured_path = path
        Image.new("RGB", (2, 2), color="red").save(path)
        return _tool_ok(path, f"Desktop screenshot saved to {path}")

    with (
        patch("platform.system", return_value="Linux"),
        patch(
            "qwenpaw.agents.tools.desktop_screenshot._capture_mss",
            side_effect=capture,
        ),
        patch(
            "qwenpaw.agents.tools.file_io.get_current_project_dir",
            return_value=tmp_path,
        ),
    ):
        result = await desktop_screenshot("relative-shot")

    expected_path = os.path.abspath(tmp_path / "relative-shot.png")
    assert captured_path == expected_path
    payload = json.loads(result.content[1].text)
    assert payload["path"] == expected_path
    assert payload["message"] == f"Desktop screenshot saved to {expected_path}"


@pytest.mark.asyncio
async def test_desktop_screenshot_keeps_path_when_inline_media_is_too_large(
    tmp_path,
):
    """The preview location survives model-context size protection."""

    def capture(path):
        Image.new("RGB", (2, 2), color="red").save(path)
        return _tool_ok(path, f"Desktop screenshot saved to {path}")

    with (
        patch("platform.system", return_value="Linux"),
        patch(
            "qwenpaw.agents.tools.desktop_screenshot._capture_mss",
            side_effect=capture,
        ),
        patch(
            "qwenpaw.agents.tools.file_io.get_current_project_dir",
            return_value=tmp_path,
        ),
        patch(
            "qwenpaw.agents.utils.image_freezing.MAX_INLINE_MEDIA_BYTES",
            1,
        ),
    ):
        result = await desktop_screenshot("large-shot.png")

    expected_path = os.path.abspath(tmp_path / "large-shot.png")
    assert result.state == ToolResultState.SUCCESS
    assert "exceeds" in result.content[0].text
    payload = json.loads(result.content[1].text)
    assert payload["path"] == expected_path
    assert payload["message"] == f"Desktop screenshot saved to {expected_path}"


def test_desktop_screenshot_success_result_uses_one_canonical_location(
    tmp_path,
):
    """URL and structured result identify the same absolute file."""
    image_path = tmp_path / "desktop.png"
    result = _tool_ok(
        str(image_path),
        f"Desktop screenshot saved to {image_path}",
    )

    assert result.state == ToolResultState.SUCCESS
    assert isinstance(result.content[0].source, URLSource)
    payload = json.loads(result.content[1].text)
    assert payload["path"] == os.path.abspath(image_path)
    assert str(result.content[0].source.url).endswith(
        str(image_path).replace("\\", "/"),
    )
