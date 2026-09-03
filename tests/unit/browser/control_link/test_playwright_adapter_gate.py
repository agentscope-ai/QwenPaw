# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Skip managed Chromium download when launch uses another browser."""

from __future__ import annotations

import pytest

import qwenpaw.browser.control_link.playwright.adapter as adapter_module
from qwenpaw.browser.control_link.playwright.adapter import (
    PlaywrightControlLink,
)
from qwenpaw.browser.errors import BrowserError, ErrorCategory, ErrorCause


def _owner_params(**extra):
    params = {
        "workspace_id": "ws",
        "session_id": "s1",
        "context": "incognito",
    }
    params.update(extra)
    return params


@pytest.fixture
def open_session(monkeypatch):
    """Stub Playwright launch so tests only observe the download gate."""
    download_calls: list[bool] = []

    def ensure(*_args, **_kwargs):
        download_calls.append(True)
        return True, "", 0.0

    monkeypatch.setattr(adapter_module, "ensure_managed_chromium", ensure)
    link = PlaywrightControlLink()
    link._pw = object()

    async def fake_create(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(link, "_create_session_context", fake_create)

    async def run(params):
        return await link._m_open_session(params)

    try:
        yield run, download_calls
    finally:
        if link in adapter_module._LIVE:
            adapter_module._LIVE.remove(link)


@pytest.mark.asyncio
async def test_default_launch_starts_managed_download(open_session):
    run, download_calls = open_session
    await run(_owner_params())
    assert download_calls == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"executable_path": "/usr/bin/chromium"},
        {"channel": "chrome"},
    ],
)
async def test_explicit_browser_skips_managed_download(
    open_session,
    extra,
):
    run, download_calls = open_session
    await run(_owner_params(**extra))
    assert not download_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"executable_path": " "},
        {"channel": " "},
    ],
)
async def test_blank_browser_target_still_downloads(open_session, extra):
    run, download_calls = open_session
    await run(_owner_params(**extra))
    assert download_calls == [True]
    launch, _context = adapter_module._build_launch_kwargs(
        _owner_params(**extra),
    )
    assert "channel" not in launch
    assert "executable_path" not in launch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("detail", "retry_after", "reason_part", "action_part"),
    [
        ("", 15.0, "downloading", "Wait 15 seconds"),
        ("firewall", 45.0, "install failed", "Wait 45 seconds"),
    ],
)
async def test_managed_cache_not_ready_raises_retryable(
    monkeypatch,
    detail,
    retry_after,
    reason_part,
    action_part,
):
    def ensure(*_args, **_kwargs):
        return False, detail, retry_after

    monkeypatch.setattr(adapter_module, "ensure_managed_chromium", ensure)
    link = PlaywrightControlLink()
    link._pw = object()

    async def fake_create(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(link, "_create_session_context", fake_create)
    try:
        with pytest.raises(BrowserError) as caught:
            await link._m_open_session(_owner_params())
        assert caught.value.category is ErrorCategory.RETRYABLE
        assert caught.value.cause is ErrorCause.TIMING
        assert reason_part in caught.value.reason
        assert action_part in caught.value.suggested_action
        if detail:
            assert "downloading" not in caught.value.reason
    finally:
        if link in adapter_module._LIVE:
            adapter_module._LIVE.remove(link)
