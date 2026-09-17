# -*- coding: utf-8 -*-
"""Replay orphan tool history against built UI; intercept all API traffic."""

import json
import os
from urllib.parse import urlsplit

import pytest

BASE_URL = os.environ.get("WELDON_TEST_CONSOLE_URL", "")
CHAT_ID = "00000000-0000-4000-8000-000000000041"


@pytest.mark.skipif(
    not BASE_URL, reason="Set WELDON_TEST_CONSOLE_URL to a built console"
)
def test_ended_tool_history_survives_tab_switch_and_reload():
    from playwright.sync_api import sync_playwright

    # Same shape as the persisted PROFILE.md read: call delivery completed,
    # no tool output, and a later user turn proves this response has ended.
    messages = [
        {
            "id": "user-1",
            "role": "user",
            "type": "message",
            "content": [{"type": "text", "text": "Read PROFILE.md"}],
        },
        {
            "id": "tool-1",
            "role": "assistant",
            "type": "plugin_call",
            "status": "completed",
            "content": [
                {
                    "type": "data",
                    "data": {
                        "name": "read_file",
                        "call_id": "orphan-profile",
                        "arguments": '{"file_path":"PROFILE.md"}',
                    },
                }
            ],
        },
        {
            "id": "user-2",
            "role": "user",
            "type": "message",
            "content": [{"type": "text", "text": "Next turn"}],
        },
        {
            "id": "answer-2",
            "role": "assistant",
            "type": "message",
            "status": "completed",
            "content": [{"type": "text", "text": "Later response finished."}],
        },
    ]
    chat = {
        "id": CHAT_ID,
        "session_id": CHAT_ID,
        "user_id": "default",
        "channel": "console",
        "name": "Tool history regression",
        "status": "idle",
        "created_at": "2026-08-31T11:03:13Z",
        "updated_at": "2026-08-31T11:10:52Z",
        "meta": {},
    }
    requests = []

    def api_fixture(route):
        path = urlsplit(route.request.url).path.removeprefix("/api")
        requests.append(path)
        if path.endswith("/stream") or path == "/console/inbox/events":
            route.fulfill(status=204)
            return
        if path in ("/user-input/pending", "/runtime-status/current"):
            payload = None
        elif path == "/auth/status":
            payload = {"enabled": False, "mode": "legacy", "has_users": True}
        elif path == "/agents":
            payload = {
                "agents": [{"id": "default", "name": "Test agent", "enabled": True}]
            }
        elif path == "/chats":
            payload = [chat]
        elif path == f"/chats/{CHAT_ID}":
            payload = {"messages": messages, "status": "idle"}
        elif path == f"/chats/{CHAT_ID}/status":
            payload = {"status": "idle"}
        elif path == "/frontend_plugin":
            payload = []
        elif path == "/model-catalog":
            payload = {"models": []}
        elif path.endswith("/project-dir") or path == "/workspace/project-directory":
            payload = {
                "project_dir": "/workspace",
                "source": "workspace_fallback",
                "exists": True,
            }
        elif path in ("/console/push-messages", "/slash/catalog", "/loops"):
            payload = []
        else:
            payload = {}
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(payload)
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            context.route("**/api/**", api_fixture)
            page = context.new_page()
            errors = []
            console_errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text)
                    if message.type == "error"
                    else None
                ),
            )
            page.goto(
                f"{BASE_URL.rstrip('/')}/chat/{CHAT_ID}", wait_until="domcontentloaded"
            )

            def assert_settled():
                try:
                    page.get_by_text("Later response finished.", exact=True).wait_for(
                        timeout=20000
                    )
                except Exception as exc:
                    raise AssertionError(
                        {
                            "url": page.url,
                            "errors": errors,
                            "console_errors": console_errors,
                            "requests": sorted(set(requests)),
                            "page": page.locator("body").inner_text()[:1500],
                        }
                    ) from exc
                tool = page.locator("summary").filter(has_text="PROFILE.md")
                assert tool.count() == 1
                assert (
                    "未记录结果" in tool.inner_text()
                    or "without a recorded result" in tool.inner_text()
                )
                assert tool.locator('[class*="toolCallSpinner"]').count() == 0
                assert tool.locator('[class*="gearBtn"]').count() == 0
                assert not errors, errors
                assert not any(
                    "tool-calls" in path or "tool_calls" in path for path in requests
                ), requests

            assert_settled()
            other = context.new_page()
            other.goto("about:blank")
            other.bring_to_front()
            page.bring_to_front()
            assert_settled()
            page.reload(wait_until="domcontentloaded")
            assert_settled()
        finally:
            browser.close()
