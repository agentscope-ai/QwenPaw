# -*- coding: utf-8 -*-
"""Real Chromium contracts for the Playwright control-link provider."""

import pytest

from qwenpaw.browser.control_link.playwright.adapter import (
    PlaywrightControlLink,
)
from qwenpaw.browser.errors import BrowserError


def _locator_spec(method: str, *args: str, **kwargs: str) -> list[dict]:
    return [
        {
            "method": method,
            "args": list(args),
            "kwargs": [[key, value] for key, value in kwargs.items()],
        },
    ]


async def test_real_provider_isolates_sessions_and_profile(
    fixture_url: str,
    tmp_path,
) -> None:
    """Sessions and profile contexts use separate real Chromium state."""
    link = PlaywrightControlLink()
    first_owner = {"workspace_id": "ws", "session_id": "incognito"}
    profile_owner = {"workspace_id": "ws", "session_id": "profile"}
    try:
        await link.request(
            "open_session",
            {**first_owner, "context": "incognito"},
        )
        await link.request(
            "open_session",
            {
                **profile_owner,
                "context": "profile",
                "user_data_dir": str(tmp_path / "profile"),
            },
        )
        first = await link.request(
            "new_page",
            {**first_owner, "url": fixture_url},
        )
        profile = await link.request(
            "new_page",
            profile_owner,
        )
        first_pages = await link.request("list_pages", first_owner)
        profile_pages = await link.request("list_pages", profile_owner)

        assert first["page_id"] != profile["page_id"]
        assert {page["page_id"] for page in first_pages["pages"]} == {
            first["page_id"],
        }
        assert {page["page_id"] for page in profile_pages["pages"]} == {
            profile["page_id"],
        }
    finally:
        await link.close_all()


async def test_real_provider_observes_locates_and_acts(
    fixture_url: str,
) -> None:
    """The provider reads and changes a real page through lazy locators."""
    link = PlaywrightControlLink()
    owner = {"workspace_id": "ws", "session_id": "session"}
    try:
        await link.request(
            "open_session",
            {**owner, "context": "incognito"},
        )
        opened = await link.request(
            "new_page",
            {**owner, "url": fixture_url},
        )
        count = await link.request(
            "locator_count",
            {
                **owner,
                "page_id": opened["page_id"],
                "spec": _locator_spec("get_by_role", "button", name="登录"),
            },
        )
        result = await link.request(
            "locator_action",
            {
                **owner,
                "page_id": opened["page_id"],
                "spec": _locator_spec("get_by_role", "button", name="登录"),
                "action": "click",
            },
        )
        tree = await link.request(
            "capture_tree",
            {**owner, "page_id": opened["page_id"]},
        )

        assert count["count"] == 1
        assert "click" in result["evidence"]
        assert "Logged in" in str(tree["tree"])
    finally:
        await link.close_all()


async def test_real_provider_rejects_unsupported_context_and_method() -> None:
    link = PlaywrightControlLink()
    try:
        with pytest.raises(BrowserError):
            await link.request(
                "open_session",
                {
                    "workspace_id": "ws",
                    "session_id": "attached",
                    "context": "attached",
                },
            )
        with pytest.raises(BrowserError):
            await link.request("no_such_method", {})
    finally:
        await link.close_all()
