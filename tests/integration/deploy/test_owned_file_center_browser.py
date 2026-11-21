# -*- coding: utf-8 -*-
"""真实前端的本人资料/记忆读取与账户切换；全部业务接口为隔离夹具。"""

import json
import os
import re
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import pytest

BASE_URL = os.environ.get("WELDON_TEST_CONSOLE_URL", "")
AGENT = "retired-file-agent"
DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
SECOND_DOCUMENT_ID = "22222222-2222-4222-8222-222222222222"
MEMORY_PATH = "2026-11-21/旅行偏好.md"


@pytest.mark.skipif(not BASE_URL, reason="Set WELDON_TEST_CONSOLE_URL to a local built console")
@pytest.mark.parametrize("scenario", ["retired", "missing_profile"])
def test_owned_library_and_private_memory_survive_return_and_account_change(scenario):
    from playwright.sync_api import expect, sync_playwright

    assert urlsplit(BASE_URL).hostname in {"127.0.0.1", "localhost", "::1"}
    current = "甲"
    reads, mutations, errors, unexpected = [], [], [], []
    document = {
        "id": DOCUMENT_ID, "relative_path": "旅行计划.md", "name": "旅行计划.md",
        "media_type": "text/markdown", "size": 30, "sha256": "a" * 64,
        "created_at": "2026-11-21T00:00:00Z", "updated_at": "2026-11-21T00:00:00Z",
    }
    url = BASE_URL.rstrip("/")
    def library_url(user):
        return url + "/files?" + urlencode({
            "agentId": AGENT, "category": "library", "item": document["relative_path"],
            "stableId": DOCUMENT_ID if user == "甲" else SECOND_DOCUMENT_ID,
        })

    def api(route):
        nonlocal current
        parsed = urlsplit(route.request.url)
        path = parsed.path.removeprefix("/api")
        query = parse_qs(parsed.query)
        if route.request.method not in {"GET", "HEAD", "OPTIONS"} and path not in {"/auth/login", "/auth/logout", "/auth/refresh"}:
            mutations.append((route.request.method, path))
            route.fulfill(status=403, content_type="application/json", body='{"detail":"fixture_read_only"}')
            return
        payload = {}
        if path == "/auth/status":
            payload = {"enabled": True, "mode": "multi_user", "has_users": True}
        elif path == "/auth/refresh":
            payload = {"token": "file-owner-a" if current == "甲" else "file-owner-b", "username": f"文件用户{current}"}
        elif path == "/auth/login":
            assert route.request.post_data_json["username"] == "文件用户乙"
            current = "乙"
            payload = {"token": "file-owner-b", "username": f"文件用户{current}"}
        elif path == "/auth/logout":
            payload = {"success": True}
        elif path == "/me":
            payload = {"user": {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" if current == "甲" else "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "username": f"文件用户{current}", "platform_role": "member", "status": "active",
            }, "preferences": {"language": "zh"}}
        elif path == "/agents":
            agent = {"id": AGENT, "name": "已停用智能体", "enabled": False,
                     "historical_read_only": True, "access_role": "user", "can_edit": False}
            other = {"id": "another-agent", "name": "其他智能体", "enabled": True,
                     "access_role": "user", "can_edit": False}
            payload = {"agents": [other] if scenario == "missing_profile" else [agent, other]}
        elif path.startswith("/console/personal-library/"):
            assert route.request.headers.get("x-agent-id") == AGENT
            assert route.request.headers.get("authorization") == ("Bearer file-owner-a" if current == "甲" else "Bearer file-owner-b")
            reads.append((current, "library", path))
            own_document = {**document, "id": DOCUMENT_ID if current == "甲" else SECOND_DOCUMENT_ID}
            if path.endswith("/documents/page"):
                payload = {"items": [own_document], "total": 1}
            elif path.endswith("/documents"):
                payload = [own_document]
            elif path.endswith("/index"):
                payload = [{"document_id": own_document["id"], "status": "ready", "indexed_characters": 30, "updated_at": None}]
            elif path == f"/console/personal-library/documents/{own_document['id']}/text":
                payload = {**own_document, "content": f"# 用户{current}的旅行资料\n\n用户{current}私有资料正文。", "offset": 0,
                           "next_offset": None, "truncated": False}
            else:
                route.fulfill(status=403, content_type="application/json", body='{"detail":"forbidden"}')
                return
        elif path == f"/agents/{AGENT}/memory/scopes":
            assert route.request.headers.get("x-agent-id") == AGENT
            assert route.request.headers.get("authorization") == ("Bearer file-owner-a" if current == "甲" else "Bearer file-owner-b")
            payload = {"agent_id": AGENT, "scopes": [{
                "scope": "private", "can_read": True, "can_edit": False,
                "status": "access_revoked", "index_state": "needs_reindex", "index_version": 1,
            }]}
        elif path == "/workspace/memory" or path.startswith("/workspace/memory/"):
            assert route.request.headers.get("x-agent-id") == AGENT
            assert route.request.headers.get("authorization") == ("Bearer file-owner-a" if current == "甲" else "Bearer file-owner-b")
            assert query.get("scope") == ["private"]
            assert query.get("section") == ["daily"]
            if path != "/workspace/memory":
                assert unquote(path.removeprefix("/workspace/memory/")) == MEMORY_PATH
            reads.append((current, "memory", path))
            payload = ([{"filename": MEMORY_PATH, "size": 40, "modified_time": "2026-11-21T00:00:00Z"}]
                       if path == "/workspace/memory" else {"content": f"# 用户{current}的私有记忆\n\n用户{current}喜欢徒步旅行。"})
        elif path.endswith("/stream"):
            route.fulfill(status=204)
            return
        elif path in ("/frontend_plugin", "/slash/catalog", "/loops", "/chats", "/console/attachments", "/console/artifacts"):
            payload = []
        elif path == "/chats/page":
            payload = {"items": [], "has_more": False, "next_cursor": None}
        elif path == "/console/push-messages":
            payload = {"messages": [], "pending_approvals": []}
        elif path == "/console/inbox/events":
            payload = {"events": [], "total": 0, "unread_count": 0}
        elif path in ("/runtime-status/current", "/user-input/pending", "/plan/current"):
            payload = None
        elif path == "/model-catalog":
            payload = {"models": []}
        # Runtime/configuration endpoints deliberately remain unavailable.
        elif path.startswith("/workspace/") or path.startswith(f"/agents/{AGENT}/"):
            route.fulfill(status=403, content_type="application/json", body='{"detail":"agent_revoked"}')
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
            else:
                unexpected.append(route.request.url)
                route.abort()
        elif parsed.path.startswith("/api/"):
            api(route)
        else:
            route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="zh-CN")
            context.route("**/*", isolate)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def inspect_owned_files(user):
                page.goto(library_url(user), wait_until="networkidle")
                dismiss = page.get_by_text("我知道了", exact=True)
                if dismiss.is_visible():
                    dismiss.click()
                expect(page.get_by_text(f"用户{user}私有资料正文。", exact=True)).to_be_visible(timeout=15000)
                expect(page.get_by_role("button", name="旅行计划.md", exact=True)).to_have_count(1)
                page.get_by_role("tab", name="记忆", exact=True).click()
                memory = page.get_by_role("region", name="记忆", exact=True)
                expect(memory.get_by_role("tab", name="我的记忆", exact=True)).to_be_visible()
                expect(memory.get_by_role("tab", name="公共记忆", exact=True)).to_have_count(0)
                memory.get_by_role("button", name="旅行偏好.md", exact=True).click()
                expect(memory.locator("pre")).to_contain_text(f"用户{user}喜欢徒步旅行。")
                saved = page.url
                other = context.new_page()
                other.goto("about:blank")
                for _ in range(2):
                    other.bring_to_front()
                    page.bring_to_front()
                    expect(memory.locator("pre")).to_contain_text(f"用户{user}喜欢徒步旅行。")
                page.get_by_text("收件箱", exact=True).first.click()
                page.wait_for_url("**/inbox")
                page.go_back(wait_until="networkidle")
                expect(page).to_have_url(saved)
                expect(page.get_by_role("region", name="记忆").locator("pre")).to_contain_text(f"用户{user}喜欢徒步旅行。")
                page.reload(wait_until="networkidle")
                expect(page.get_by_role("region", name="记忆").locator("pre")).to_contain_text(f"用户{user}喜欢徒步旅行。")
                other.close()

            inspect_owned_files("甲")
            page.get_by_role("button", name="文件用户甲 普通用户", exact=True).click()
            page.get_by_text("退出登录", exact=True).click()
            page.get_by_role("dialog").get_by_role("button", name=re.compile("退出登录")).click()
            page.wait_for_url("**/login**")
            expect(page.get_by_text("用户甲喜欢徒步旅行。", exact=False)).to_have_count(0)
            expect(page.get_by_text("用户甲私有资料正文。", exact=False)).to_have_count(0)
            page.get_by_placeholder("用户名", exact=True).fill("文件用户乙")
            page.get_by_placeholder("密码", exact=True).fill("local-only-password")
            page.get_by_role("button", name=re.compile(r"^登\s*录$")).click()
            expect(page.get_by_role("button", name="文件用户乙 普通用户", exact=True)).to_be_visible(timeout=15000)
            inspect_owned_files("乙")
            expect(page.get_by_text("用户甲喜欢徒步旅行。", exact=False)).to_have_count(0)
            expect(page.get_by_text("用户甲私有资料正文。", exact=False)).to_have_count(0)
            assert {(owner, kind) for owner, kind, _ in reads} == {("甲", "library"), ("甲", "memory"), ("乙", "library"), ("乙", "memory")}
            assert not mutations, mutations
            assert not unexpected, unexpected
            assert not errors, errors
        except Exception as exc:
            raise AssertionError({"errors": errors, "reads": reads, "page": page.locator("body").inner_text()[:2200]}) from exc
        finally:
            browser.close()
