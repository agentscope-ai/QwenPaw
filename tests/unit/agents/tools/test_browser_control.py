# -*- coding: utf-8 -*-
"""Tests for browser click behavior in browser_control."""

# pylint: disable=protected-access

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.agents.tools import browser_control


def _parse_response(resp) -> dict:
    return json.loads(resp.content[0]["text"])


class _FakeLoop:
    async def run_in_executor(self, _executor, func):
        return func()


@pytest.mark.asyncio
async def test_click_by_selector_success(monkeypatch):
    page = MagicMock()
    locator = MagicMock()
    locator.click = AsyncMock()
    root = MagicMock()
    root.locator.return_value.first = locator

    monkeypatch.setattr(browser_control, "_USE_SYNC_PLAYWRIGHT", False)
    monkeypatch.setattr(browser_control, "_get_page", lambda *_args: page)
    monkeypatch.setattr(browser_control, "_get_root", lambda *_args: root)

    resp = await browser_control._action_click(
        state={},
        page_id="default",
        selector="#submit",
    )
    data = _parse_response(resp)

    assert data["ok"] is True
    assert data["message"] == "Clicked #submit"
    locator.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_click_by_ref_success(monkeypatch):
    page = MagicMock()
    locator = MagicMock()
    locator.click = AsyncMock()

    monkeypatch.setattr(browser_control, "_USE_SYNC_PLAYWRIGHT", False)
    monkeypatch.setattr(browser_control, "_get_page", lambda *_args: page)
    monkeypatch.setattr(
        browser_control,
        "_get_locator_by_ref",
        lambda *_args, **_kwargs: locator,
    )

    resp = await browser_control._action_click(
        state={},
        page_id="default",
        selector="",
        ref="e1",
    )
    data = _parse_response(resp)

    assert data["ok"] is True
    assert data["message"] == "Clicked e1"
    locator.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_click_by_coordinates_success(monkeypatch):
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.click = AsyncMock()

    monkeypatch.setattr(browser_control, "_USE_SYNC_PLAYWRIGHT", False)
    monkeypatch.setattr(browser_control, "_get_page", lambda *_args: page)

    resp = await browser_control._action_click(
        state={},
        page_id="default",
        selector="",
        ref="",
        page_x=320,
        page_y=180,
    )
    data = _parse_response(resp)

    assert data["ok"] is True
    assert data["message"] == "Clicked page coordinate (320, 180)"
    page.mouse.click.assert_awaited_once_with(
        320,
        180,
        button="left",
        click_count=1,
    )


@pytest.mark.asyncio
async def test_click_coordinates_validation_error():
    resp = await browser_control._action_click(
        state={},
        page_id="default",
        selector="",
        ref="",
        page_x=20,
        page_y=-1,
    )
    data = _parse_response(resp)

    assert data["ok"] is False
    assert (
        "page_x and page_y must both be non-negative integers" in data["error"]
    )


@pytest.mark.asyncio
async def test_click_without_target_or_coordinates_error():
    resp = await browser_control._action_click(
        state={},
        page_id="default",
        selector="",
        ref="",
    )
    data = _parse_response(resp)

    assert data["ok"] is False
    assert "selector or ref required for click" in data["error"]
    assert "page_x and page_y" in data["error"]


@pytest.mark.asyncio
async def test_click_coordinates_zero_zero_is_valid(monkeypatch):
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.click = AsyncMock()

    monkeypatch.setattr(browser_control, "_USE_SYNC_PLAYWRIGHT", False)
    monkeypatch.setattr(browser_control, "_get_page", lambda *_args: page)

    resp = await browser_control._action_click(
        state={},
        page_id="default",
        selector="",
        ref="",
        page_x=0,
        page_y=0,
    )
    data = _parse_response(resp)

    assert data["ok"] is True
    page.mouse.click.assert_awaited_once_with(
        0,
        0,
        button="left",
        click_count=1,
    )


@pytest.mark.asyncio
async def test_click_target_priority_over_coordinates(monkeypatch):
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.click = AsyncMock()
    locator = MagicMock()
    locator.click = AsyncMock()
    root = MagicMock()
    root.locator.return_value.first = locator

    monkeypatch.setattr(browser_control, "_USE_SYNC_PLAYWRIGHT", False)
    monkeypatch.setattr(browser_control, "_get_page", lambda *_args: page)
    monkeypatch.setattr(browser_control, "_get_root", lambda *_args: root)

    resp = await browser_control._action_click(
        state={},
        page_id="default",
        selector=".btn",
        ref="",
        page_x=100,
        page_y=200,
    )
    data = _parse_response(resp)

    assert data["ok"] is True
    locator.click.assert_awaited_once()
    page.mouse.click.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_click_passes_coordinates(monkeypatch):
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.click = AsyncMock()
    monkeypatch.setattr(browser_control, "_USE_SYNC_PLAYWRIGHT", False)
    monkeypatch.setattr(browser_control, "_get_page", lambda *_args: page)

    resp = await browser_control._action_batch(
        state={},
        page_id="default",
        actions_json=json.dumps(
            [
                {
                    "action": "click",
                    "page_x": 410,
                    "page_y": 260,
                },
            ],
        ),
    )
    data = _parse_response(resp)

    assert data["ok"] is True
    page.mouse.click.assert_awaited_once_with(
        410,
        260,
        button="left",
        click_count=1,
    )


@pytest.mark.asyncio
async def test_click_coordinates_sync_path(monkeypatch):
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.click = MagicMock()

    monkeypatch.setattr(browser_control, "_USE_SYNC_PLAYWRIGHT", True)
    monkeypatch.setattr(browser_control, "_get_page", lambda *_args: page)
    monkeypatch.setattr(
        browser_control,
        "_get_executor",
        lambda: None,
        raising=False,
    )
    monkeypatch.setattr(
        browser_control.asyncio,
        "get_event_loop",
        _FakeLoop,
    )

    resp = await browser_control._action_click(
        state={},
        page_id="default",
        selector="",
        ref="",
        page_x=256,
        page_y=128,
        double_click=True,
        button="right",
    )
    data = _parse_response(resp)

    assert data["ok"] is True
    page.mouse.click.assert_called_once_with(
        256,
        128,
        button="right",
        click_count=2,
    )
