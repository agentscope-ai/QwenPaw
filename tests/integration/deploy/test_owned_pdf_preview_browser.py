# -*- coding: utf-8 -*-
"""真实前端的本人历史 PDF 预览；所有 API 均为本地隔离夹具。"""
import json
from io import BytesIO
import os
from urllib.parse import urlsplit

import pytest

BASE_URL = os.environ.get("WELDON_TEST_CONSOLE_URL", "")
CHAT_ID = "b79144ea-1810-4bb6-9a33-45930ae3d9bb"
ARTIFACT_ID = "bd20d801-5fa2-4dd0-8d5e-691806601b5b"
NAME = "2026-09-17_防水行业新闻简报.pdf"
AGENT = "pdf-test-agent"


@pytest.mark.skipif(not BASE_URL, reason="Set WELDON_TEST_CONSOLE_URL to a local built console")
@pytest.mark.parametrize("scenario", ["active", "retired_with_other", "retired_only", "missing_profile"])
def test_owned_chinese_pdf_from_chat_survives_browser_tab_and_menu_return(scenario):
    from playwright.sync_api import expect, sync_playwright
    from pypdf import PdfWriter

    # Never point this test at a real service. Routes also block every external
    # request so stale historical media cannot send credentials to an old host.
    assert urlsplit(BASE_URL).hostname in {"127.0.0.1", "localhost", "::1"}
    read_only = scenario != "active"
    pdf_buffer = BytesIO()
    pdf = PdfWriter()
    pdf.add_blank_page(width=595, height=842)
    pdf.write(pdf_buffer)
    chat = {"id": CHAT_ID, "session_id": CHAT_ID, "user_id": "fixture-user", "channel": "console",
            "name": "本人简报验收", "created_at": "2026-11-21T00:00:00Z", "updated_at": "2026-11-21T00:00:00Z", "meta": {},
            "access_role": "owner", "read_only": read_only, "agent_id": AGENT}
    agent = {"id": AGENT, "name": "简报智能体", "enabled": not read_only,
             "historical_read_only": read_only, "access_role": "user", "can_edit": False}
    other_agent = {"id": "other-agent", "name": "其他智能体", "enabled": True,
                   "access_role": "user", "can_edit": False}
    agents = [] if scenario == "missing_profile" else [agent]
    if scenario == "retired_with_other":
        agents.insert(0, other_agent)
    download = f"/console/artifacts/{ARTIFACT_ID}/download"
    file_reads, errors, unexpected_requests, mutations = [], [], [], []
    refresh_count = 0
    refresh_after_expiry = False
    expire_next_read = False

    def api(route):
        nonlocal refresh_count, refresh_after_expiry, expire_next_read
        path = urlsplit(route.request.url).path.removeprefix("/api")
        if path == download:
            headers = route.request.headers
            file_reads.append({"agent": headers.get("x-agent-id"), "auth": headers.get("authorization")})
            assert headers.get("x-agent-id") == AGENT
            assert "token=" not in urlsplit(route.request.url).query
            assert headers.get("authorization") == f"Bearer local-pdf-fixture-{refresh_count}"
            if expire_next_read:
                expire_next_read = False
                refresh_after_expiry = True
                route.fulfill(status=401, content_type="application/json", body='{"detail":"token_expired"}')
                return
            route.fulfill(status=200, content_type="application/pdf", body=pdf_buffer.getvalue())
            return
        if path.endswith("/stream"):
            route.fulfill(status=204)
            return
        payload = {}
        if path == "/auth/status":
            payload = {"enabled": True, "mode": "multi_user", "has_users": True}
        elif path == "/auth/refresh":
            refresh_count += 1
            payload = {"token": f"local-pdf-fixture-{refresh_count}", "username": "pdf-owner"}
        elif path == "/me":
            payload = {"user": {"id": "11111111-1111-4111-8111-111111111111", "username": "pdf-owner", "platform_role": "member", "status": "active"}, "preferences": {"language": "zh"}}
        elif path == "/agents":
            payload = {"agents": agents}
        elif path == "/chats":
            payload = [chat] if route.request.headers.get("x-agent-id") == AGENT else []
        elif path == "/chats/page":
            payload = {"items": [chat] if route.request.headers.get("x-agent-id") == AGENT else [],
                       "has_more": False, "next_cursor": None}
        elif path == f"/chats/{CHAT_ID}/spec":
            payload = chat
        elif path == f"/chats/{CHAT_ID}":
            assert route.request.headers.get("x-agent-id") == AGENT
            payload = {"status": "idle", "access_role": "owner", "read_only": read_only, "messages": [
                {"id": "question", "role": "user", "type": "message", "content": [{"type": "text", "text": "请给我防水简报"}]},
                {"id": "answer", "role": "assistant", "type": "message", "status": "completed", "content": [
                    {"type": "text", "text": "这是你的中文简报"},
                    # Same-origin historical links must discard an expired
                    # embedded token and use the current authenticated session.
                    {"type": "file", "file_url": f"{BASE_URL.rstrip('/')}/api{download}?token=expired-token", "filename": NAME},
                ]},
            ]}
        elif path.endswith("/status"):
            payload = {"status": "idle"}
        elif path.endswith("/model") or path == "/model-catalog/default":
            payload = {"active_llm": {"provider_id": "test", "model": "fixture"}, "source": "agent_default", "model_override": None, "locked": False}
        elif path == "/model-catalog":
            payload = {"models": [{"provider_id": "test", "provider_name": "Test", "model": "fixture", "name": "fixture"}]}
        elif path.endswith("/project-dir") or path == "/workspace/project-directory":
            payload = {"project_dir": "/fixture", "source": "workspace_fallback", "exists": True}
        elif path in ("/frontend_plugin", "/slash/catalog", "/loops", "/console/attachments", "/console/artifacts"):
            payload = []
        elif path == "/console/push-messages":
            payload = {"messages": [], "pending_approvals": []}
        elif path == "/console/inbox/events":
            payload = {"events": [], "total": 0, "unread_count": 0}
        elif path in ("/runtime-status/current", "/user-input/pending", "/plan/current"):
            payload = None
        if route.request.method not in {"GET", "OPTIONS"} and path != "/auth/refresh":
            mutations.append((route.request.method, path))
            route.fulfill(status=403, content_type="application/json", body='{"detail":"fixture_read_only"}')
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))

    def isolate(route):
        parsed = urlsplit(route.request.url)
        if parsed.scheme in {"data", "blob", "about"}:
            route.continue_()
        elif parsed.netloc != urlsplit(BASE_URL).netloc:
            if parsed.hostname in {"img.alicdn.com", "gw.alicdn.com"} and route.request.resource_type == "image":
                assert "authorization" not in route.request.headers
                assert "x-agent-id" not in route.request.headers
                route.fulfill(status=200, content_type="image/svg+xml",
                              body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
                return
            unexpected_requests.append(route.request.url)
            route.abort()
        elif parsed.path.startswith("/api/"):
            api(route)
        else:
            route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            # Separate contexts simulate reopening history after logout/login,
            # with no converted-session cache, selected-Agent state or blobs.
            for visit in range(2):
                context = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="zh-CN")
                context.route("**/*", isolate)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"{BASE_URL.rstrip('/')}/chat/{CHAT_ID}", wait_until="networkidle")
                dismiss = page.get_by_text("我知道了", exact=True)
                if dismiss.is_visible(): dismiss.click()
                expect(page.get_by_text("这是你的中文简报", exact=True)).to_be_visible(timeout=20000)
                expect(page.get_by_text(NAME, exact=True).first).to_be_visible()
                if read_only:
                    # The history remains inspectable but cannot send turns.
                    expect(page.locator('[contenteditable="true"]')).to_have_count(0)
                expire_next_read = visit == 0
                before_refresh = refresh_count
                page.locator(".qwenpaw-bubble-files-download").first.click()
                expect(page.locator('embed[src^="blob:"]')).to_be_visible(timeout=15000)
                if visit == 0:
                    assert refresh_after_expiry and refresh_count == before_refresh + 1
                expect(page.get_by_text("访问被拒绝：没有预览此文件的权限。", exact=True)).to_have_count(0)
                other = context.new_page()
                other.goto("about:blank")
                for _ in range(2):
                    other.bring_to_front()
                    page.bring_to_front()
                    expect(page.locator('embed[src^="blob:"]')).to_be_visible()
                for _ in range(2):
                    page.get_by_text("收件箱", exact=True).first.click()
                    page.wait_for_url("**/inbox")
                    page.get_by_text("聊天", exact=True).first.click()
                    expect(page).to_have_url(f"{BASE_URL.rstrip('/')}/chat/{CHAT_ID}")
                    expect(page.get_by_text("这是你的中文简报", exact=True)).to_be_visible(timeout=15000)
                    expect(page.get_by_text("请给我防水简报", exact=True)).to_have_count(1)
                page.reload(wait_until="networkidle")
                expect(page.get_by_text("这是你的中文简报", exact=True)).to_be_visible(timeout=15000)
                expect(page.get_by_text("请给我防水简报", exact=True)).to_have_count(1)
                context.close()
            assert file_reads and all(x["agent"] == AGENT and x["auth"] for x in file_reads)
            assert not unexpected_requests, unexpected_requests
            assert not mutations, mutations
            assert not errors, errors
        finally:
            browser.close()
