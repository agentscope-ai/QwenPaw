# -*- coding: utf-8 -*-
"""Tests for desktop_screenshot cancel cleanup."""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.agents.tools.desktop_screenshot import (
    _capture_macos_screencapture,
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
    proc.kill.assert_called_once()
    proc.wait.assert_awaited()
