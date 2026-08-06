# -*- coding: utf-8 -*-
"""Real Chromium session-context isolation through the subprocess plane."""

import pytest

from qwenpaw.browser.control_link.playwright.adapter import (
    PlaywrightControlLink,
)
from qwenpaw.browser.execution.subprocess_plane import SubprocessPlane
from qwenpaw.browser.execution.wire import ExecRequest
from qwenpaw.browser.runtime.links import link_for


def request(session_id: str, code: str) -> ExecRequest:
    return ExecRequest(
        request_id=session_id,
        code=code,
        context="incognito",
        owner_workspace_id="w",
        owner_session_id=session_id,
    )


async def test_two_incognito_sessions_are_isolated(fixture_url: str) -> None:
    plane = SubprocessPlane()
    first_code = (
        "browser = await Browser.connect(identity='guest')\n"
        f"page = await browser.open({fixture_url!r})\n"
        "result = page.id\n"
        "result"
    )
    second_code = (
        "browser = await Browser.connect(identity='guest')\n"
        f"await browser.open({fixture_url!r})\n"
        "result = len(await browser.pages())\n"
        "result"
    )
    try:
        first = await plane.run("w", request("sA", first_code))
        second = await plane.run("w", request("sB", second_code))

        assert first.error is None
        assert first.value
        assert second.error is None
        # Browser.connect() retains the provider-created first page, so the
        # first Browser.open() reuses it instead of creating a ghost tab.
        assert second.value == "1"
    finally:
        await plane.discard_all_workers()
        # The Playwright truth now lives in the test process.  Unlike its
        # former worker-local lifetime, it must be released before pytest
        # advances to a test with a fresh event loop.
        link = link_for("playwright")
        if link is not None:
            await link.close_all()


async def test_same_session_id_is_isolated_by_workspace(
    fixture_url: str,
) -> None:
    """Provider ownership includes workspace, not merely session ID."""
    link = PlaywrightControlLink()
    owner_a = {"workspace_id": "ws_A", "session_id": "chat_1"}
    owner_b = {"workspace_id": "ws_B", "session_id": "chat_1"}
    url_b = "data:text/html,<title>workspace-b</title><p>B</p>"
    try:
        await link.request(
            "open_session",
            {**owner_a, "context": "incognito"},
        )
        await link.request(
            "open_session",
            {**owner_b, "context": "incognito"},
        )
        opened_a = await link.request(
            "new_page",
            {**owner_a, "url": fixture_url},
        )
        opened_b = await link.request(
            "new_page",
            {**owner_b, "url": url_b},
        )

        pages_a = await link.request("list_pages", owner_a)
        pages_b = await link.request("list_pages", owner_b)
        assert {page["page_id"] for page in pages_a["pages"]} == {
            opened_a["page_id"],
        }
        assert {page["page_id"] for page in pages_b["pages"]} == {
            opened_b["page_id"],
        }
        assert (
            await link.request(
                "current_surface",
                {**owner_a, "page_id": opened_a["page_id"]},
            )
        )["url"] == fixture_url
        assert (
            await link.request(
                "current_surface",
                {**owner_b, "page_id": opened_b["page_id"]},
            )
        )["url"] == url_b

        await link.request("close_session", owner_a)
        assert (await link.request("list_pages", owner_a))["pages"] == []
        assert (
            await link.request(
                "current_surface",
                {**owner_b, "page_id": opened_b["page_id"]},
            )
        )["url"] == url_b
    finally:
        await link.close_all()


@pytest.mark.parametrize(
    "contexts",
    [("profile", "incognito"), ("incognito", "profile")],
)
async def test_profile_and_incognito_have_independent_process_cells(
    contexts: tuple[str, str],
    tmp_path,
) -> None:
    """Profile and incognito sessions do not share a provider process cell."""
    link = PlaywrightControlLink()
    workspace_id = "mixed-workspace"
    opened: dict[str, dict[str, str]] = {}
    try:
        for context in contexts:
            session_id = f"session-{context}"
            params = {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "context": context,
            }
            if context == "profile":
                params["user_data_dir"] = str(tmp_path / "profile")
            await link.request("open_session", params)
            opened[context] = dict(
                await link.request(
                    "new_page",
                    {
                        "workspace_id": workspace_id,
                        "session_id": session_id,
                    },
                ),
            )

        first, second = contexts
        await link.request(
            "close_session",
            {"workspace_id": workspace_id, "session_id": f"session-{first}"},
        )
        surface = await link.request(
            "current_surface",
            {
                "workspace_id": workspace_id,
                "session_id": f"session-{second}",
                "page_id": opened[second]["page_id"],
            },
        )
        assert surface["url"] == "about:blank"
    finally:
        await link.close_all()
