# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Configured Playwright default-argument exclusions survive session launch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.browser.control_link.playwright import adapter as adapter_module
from qwenpaw.browser.runtime.launch_resolve import resolve_launch
from qwenpaw.browser.runtime.ownership_adapter import build_session
from qwenpaw.browser.sdk.contracts import Owner
from qwenpaw.config.config import BrowserConfig


class _RecordingLink:
    def __init__(self) -> None:
        self.params = None

    async def request(self, method, params):
        assert method == "open_session"
        self.params = params
        return {"headless": False}


class _RecordingChromium:
    def __init__(self) -> None:
        self.calls = []

    async def launch(self, **kwargs):
        self.calls.append(("launch", kwargs))

        async def new_context(**_kwargs):
            return object()

        return SimpleNamespace(new_context=new_context)

    async def launch_persistent_context(self, user_data_dir, **kwargs):
        self.calls.append(("launch_persistent_context", kwargs))
        assert user_data_dir
        return object()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context_kind", "launch_method"),
    [
        ("incognito", "launch"),
        ("profile", "launch_persistent_context"),
    ],
)
async def test_default_argument_exclusions_reach_playwright(
    tmp_path,
    context_kind,
    launch_method,
):
    config = BrowserConfig(
        backend="launch",
        ignore_default_args=["--disable-extensions"],
        user_data_dir=str(tmp_path / "profile"),
    )
    launch = resolve_launch(
        config,
        in_container=False,
        has_display=True,
        system_default=(None, None),
        bundled_path="/usr/bin/chromium",
    )
    wire = _RecordingLink()
    await build_session(
        wire,
        context=context_kind,
        owner=Owner(workspace_id="ws", session_id="s1"),
        variant="playwright",
        launch=launch,
    )
    kwargs, context_kwargs = adapter_module._build_launch_kwargs(wire.params)
    chromium = _RecordingChromium()
    link = adapter_module.PlaywrightControlLink()
    link._pw = SimpleNamespace(chromium=chromium)
    try:
        await link._create_session_context(
            ("ws", "s1"),
            context_kind,
            wire.params,
            kwargs,
            context_kwargs,
        )
        assert chromium.calls == [(launch_method, kwargs)]
        assert chromium.calls[0][1]["ignore_default_args"] == [
            "--disable-extensions",
        ]
        assert launch["ignore_default_args"] is not config.ignore_default_args
    finally:
        adapter_module._LIVE.remove(link)


def test_default_config_keeps_playwright_defaults():
    config = BrowserConfig()
    launch = resolve_launch(
        config,
        in_container=False,
        has_display=True,
        system_default=(None, None),
        bundled_path="/usr/bin/chromium",
    )
    wire_params = {**launch}
    kwargs, _context_kwargs = adapter_module._build_launch_kwargs(wire_params)
    assert config.ignore_default_args == []
    assert "ignore_default_args" not in kwargs
