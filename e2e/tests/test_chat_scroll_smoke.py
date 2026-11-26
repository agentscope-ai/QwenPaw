# -*- coding: utf-8 -*-
"""Browser regression for returning from an old chat-history page."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from mocks import (
    agents,
    auth,
    backups,
    channels,
    cron_jobs,
    environments,
    heartbeat,
    models,
    security,
    sessions,
)
from pages.chat_page import ChatPage

CHAT_ID = "88888888-8888-4888-8888-888888888888"


def _register_api_mocks(page: Page) -> None:
    parsed_base = urlsplit(config.server.base_url)
    origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    api_pattern = re.compile(rf"^{re.escape(origin)}/api/")
    page.route(api_pattern, lambda route: route.fulfill(json={}))
    for mock in (
        auth,
        agents,
        channels,
        sessions,
        cron_jobs,
        heartbeat,
        models,
        security,
        environments,
        backups,
    ):
        mock.register(page)


def _chat_history() -> dict:
    messages = [
        {
            "id": f"history-{index}",
            "role": "user",
            "content": f"history message {index}",
            "metadata": {"original_id": f"history-{index}"},
        }
        for index in range(62, 0, -1)
    ]
    return {"messages": messages, "status": "idle"}


def _register_chat_routes(page: Page) -> None:
    chat = {
        "id": CHAT_ID,
        "session_id": CHAT_ID,
        "user_id": "admin",
        "channel": "console",
        "name": "Scroll smoke history",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "status": "idle",
    }
    groups = [
        {
            "id": "default",
            "name": "Uncategorized",
            "order": 0,
            "kind": "default",
            "source": None,
            "pinned": False,
        },
    ]

    def handle(route) -> None:
        request = route.request
        path = urlsplit(request.url).path
        if request.method != "GET":
            route.fallback()
        elif path == "/api/chats/resolve":
            route.fulfill(json={"agent_id": "default", "chat": chat})
        elif path == "/api/chats/groups":
            route.fulfill(json=groups)
        elif path == "/api/chats":
            route.fulfill(json=[chat])
        elif path == f"/api/chats/{CHAT_ID}/status":
            route.fulfill(json={"status": "idle"})
        elif path == f"/api/chats/{CHAT_ID}/thinking":
            route.fulfill(
                json={
                    "model": None,
                    "control": {
                        "kind": "unsupported",
                        "efforts": [],
                        "supports_off": False,
                    },
                    "value": {"level": "inherit"},
                    "effective": {"level": "inherit"},
                    "source": "agent",
                    "reason": None,
                }
            )
        elif path == f"/api/chats/{CHAT_ID}/project-dirs":
            route.fulfill(
                json={
                    "project_dirs": [
                        {
                            "path": "/workspace/default",
                            "label": "Workspace",
                            "exists": True,
                            "nested_with": None,
                            "is_workspace": True,
                        }
                    ],
                    "source": "agent",
                    "agent_project_dir": "/workspace/default",
                }
            )
        elif path == f"/api/chats/{CHAT_ID}":
            route.fulfill(json=_chat_history())
        else:
            route.fallback()

    page.route("**/api/chats**", handle)


@pytest.mark.ui_smoke
@pytest.mark.chat
@pytest.mark.test_id("CHAT-SCROLL-001")
def test_old_history_bottom_keeps_return_to_latest_visible(
    page: Page,
) -> None:
    """Jump to the oldest message, scroll to the page end, and return."""
    _register_api_mocks(page)
    _register_chat_routes(page)
    page.add_init_script(
        "localStorage.setItem('qwenpaw_auth_token', 'scroll-smoke-token');"
    )
    chat = ChatPage(page)
    chat.goto(f"{config.server.base_url}/chat/{CHAT_ID}")
    page.locator(ChatPage.CHAT_INPUT).first.wait_for(state="visible")

    directory_button = page.get_by_role(
        "button", name="Open user message directory"
    )
    directory_button.hover()
    directory = page.locator('[class*="anchor-directory-list"]')
    expect(directory).to_be_visible()
    oldest_message = directory.locator(
        'button[class*="anchor-directory-item"]'
    ).first
    expect(oldest_message).to_contain_text("history message 62")
    oldest_message.click()

    old_bubble = page.locator("#history-62")
    expect(old_bubble).to_be_visible()
    scroller = page.locator('[class*="bubble-list-order-desc"]').first
    page.wait_for_function(
        """() => {
          const scroller = document.querySelector(
            '[class*="bubble-list-order-desc"]'
          );
          return scroller && scroller.scrollTop < -10;
        }"""
    )
    scroller.evaluate(
        "element => { element.scrollTop = 0; "
        "element.dispatchEvent(new Event('scroll')); }"
    )

    return_to_latest = page.locator(
        '[class*="bubble-list-scroll-to-bottom-show"] button'
    )
    expect(return_to_latest).to_be_visible()
    return_to_latest.click()
    expect(page.locator("#history-1")).to_be_visible()
