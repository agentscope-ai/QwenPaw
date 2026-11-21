"""真实构建的收件箱/任务历史往返与换账户验收；只使用隔离 API。"""

import json
import os
import re
from urllib.parse import unquote, urlsplit

import pytest

BASE_URL = os.environ.get("WELDON_TEST_CONSOLE_URL", "")
AGENT = "identity-agent"
USERS = {"甲": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "乙": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
JOBS = {"甲": "11111111-1111-4111-8111-111111111111", "乙": "22222222-2222-4222-8222-222222222222"}
TOKENS = {"甲": "identity-owner-a", "乙": "identity-owner-b"}


@pytest.mark.skipif(not BASE_URL, reason="Set WELDON_TEST_CONSOLE_URL to a local built console")
@pytest.mark.parametrize("module", ["inbox", "cron"])
def test_inbox_and_cron_history_return_and_account_change(module):
    from playwright.sync_api import expect, sync_playwright

    assert urlsplit(BASE_URL).hostname in {"127.0.0.1", "localhost", "::1"}
    current = "甲"
    reads, mutations, errors, unexpected = [], [], [], []

    def job(owner):
        return {
            "id": JOBS[owner], "name": f"用户{owner}的私有任务", "enabled": True,
            "schedule": {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"},
            "task_type": "text", "text": f"用户{owner}任务内容", "status": "active",
            "automation_owner_user_id": USERS[owner], "created_by_user_id": USERS[owner],
            "config_version": 1,
            "dispatch": {"type": "channel", "channel": "console", "mode": "final",
                         "target": {"user_id": USERS[owner], "session_id": f"fixture-{owner}"}},
            "runtime": {"max_concurrency": 1, "timeout_seconds": 300, "misfire_grace_seconds": 60},
        }

    def api(route):
        nonlocal current
        path = unquote(urlsplit(route.request.url).path).removeprefix("/api")
        if route.request.method not in {"GET", "HEAD", "OPTIONS"} and path not in {"/auth/login", "/auth/logout", "/auth/refresh"}:
            mutations.append((route.request.method, path))
            route.fulfill(status=403, content_type="application/json", body='{"detail":"fixture_read_only"}')
            return
        payload = {}
        if path == "/auth/status":
            payload = {"enabled": True, "mode": "multi_user", "has_users": True}
        elif path == "/auth/refresh":
            payload = {"token": TOKENS[current], "username": f"权限用户{current}"}
        elif path == "/auth/login":
            assert route.request.post_data_json["username"] == "权限用户乙"
            current = "乙"
            payload = {"token": TOKENS["乙"], "username": "权限用户乙"}
        elif path == "/auth/logout":
            payload = {"success": True}
        elif path == "/me":
            payload = {"user": {"id": USERS[current], "username": f"权限用户{current}",
                                "platform_role": "member", "status": "active"}, "preferences": {"language": "zh"}}
        elif path == "/agents":
            payload = {"agents": [{"id": AGENT, "name": "权限验收智能体", "enabled": True,
                                    "access_role": "user", "can_edit": False}]}
        elif path == "/config/user-timezone":
            payload = {"timezone": "UTC"}
        elif path == "/cron/dispatch-targets":
            payload = {"items": [], "channels": ["console"]}
        elif path == "/cron/jobs" or path.startswith("/cron/jobs/") or path.startswith("/console/inbox/"):
            auth = route.request.headers.get("authorization")
            owner = next((name for name in USERS if auth == f"Bearer {TOKENS[name]}"), None)
            assert owner is not None, (path, bool(auth))
            reads.append((owner, path))
            if path == "/cron/jobs":
                payload = [job(owner)]
            elif path == f"/cron/jobs/{JOBS[owner]}/history":
                payload = [{"run_at": "2026-11-21T00:00:00Z", "status": "error",
                            "error": f"用户{owner}的历史执行详情", "trigger": "manual"}]
            elif path == "/console/inbox/events":
                payload = {"events": [{"id": f"event-{owner}", "agent_id": AGENT, "source_type": "memory",
                    "source_id": f"run-{owner}", "event_type": "memory_result", "status": "success", "severity": "info",
                    "title": f"用户{owner}的私有通知", "body": f"用户{owner}的通知正文", "read": True,
                    "created_at": 1795219200, "payload": {"run_id": f"run-{owner}"}}],
                    "total": 1, "unread_count": 0}
            elif path == f"/console/inbox/traces/run-{owner}":
                payload = {"run_id": f"run-{owner}", "status": "success", "created_at": 1795219200,
                    "completed_at": 1795219201, "meta": {}, "events": [{"at": 1795219200,
                        "event": {"role": "assistant", "name": "assistant", "content": [
                            {"type": "text", "text": f"用户{owner}的执行轨迹正文"}]}}]}
            else:
                route.fulfill(status=403, content_type="application/json", body='{"detail":"forbidden"}')
                return
        elif path.endswith("/stream"):
            route.fulfill(status=204)
            return
        elif path in {"/frontend_plugin", "/slash/catalog", "/loops", "/chats", "/console/attachments", "/console/artifacts"}:
            payload = []
        elif path == "/chats/page":
            payload = {"items": [], "has_more": False, "next_cursor": None}
        elif path == "/console/push-messages":
            payload = {"messages": [], "pending_approvals": []}
        elif path in {"/runtime-status/current", "/user-input/pending", "/plan/current"}:
            payload = None
        elif path == "/model-catalog":
            payload = {"models": []}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))

    def isolate(route):
        parsed = urlsplit(route.request.url)
        if parsed.scheme in {"data", "blob", "about"}:
            route.continue_()
        elif parsed.netloc != urlsplit(BASE_URL).netloc:
            if parsed.hostname in {"img.alicdn.com", "gw.alicdn.com"} and parsed.path.endswith(".svg"):
                assert "authorization" not in route.request.headers
                route.fulfill(status=200, content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
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
            path = "/inbox" if module == "inbox" else "/cron-jobs"
            private_detail = "执行轨迹正文" if module == "inbox" else "历史执行详情"

            def close_detail():
                if module == "inbox":
                    page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()
                else:
                    page.keyboard.press("Escape")
                expect(page.get_by_role("dialog")).not_to_be_visible()

            def open_detail(owner):
                page.goto(BASE_URL.rstrip("/") + path, wait_until="networkidle")
                dismiss = page.get_by_text("我知道了", exact=True)
                if dismiss.is_visible():
                    dismiss.click()
                if module == "inbox":
                    page.get_by_text(f"用户{owner}的通知正文", exact=True).click()
                else:
                    expect(page.get_by_text(f"用户{owner}的私有任务", exact=True)).to_be_visible()
                    page.get_by_role("button", name="执行记录", exact=True).click()
                expect(page.get_by_role("dialog").get_by_text(f"用户{owner}的{private_detail}", exact=True)).to_be_visible(timeout=15000)

            def inspect_return(owner):
                open_detail(owner)
                other = context.new_page()
                other.goto("about:blank")
                for _ in range(2):
                    other.bring_to_front()
                    page.bring_to_front()
                    expect(page.get_by_role("dialog").get_by_text(f"用户{owner}的{private_detail}", exact=True)).to_be_visible()
                other.close()
                close_detail()
                page.get_by_text("文件", exact=True).first.click()
                page.wait_for_url("**/files**")
                page.go_back(wait_until="networkidle")
                if module == "inbox":
                    page.get_by_text(f"用户{owner}的通知正文", exact=True).click()
                else:
                    page.get_by_role("button", name="执行记录", exact=True).click()
                expect(page.get_by_role("dialog").get_by_text(f"用户{owner}的{private_detail}", exact=True)).to_be_visible()
                page.reload(wait_until="networkidle")
                open_detail(owner)

            inspect_return("甲")
            close_detail()
            page.get_by_role("button", name="权限用户甲 普通用户", exact=True).click()
            page.get_by_text("退出登录", exact=True).click()
            page.get_by_role("dialog").get_by_role("button", name=re.compile("退出登录")).click()
            page.wait_for_url("**/login**")
            expect(page.get_by_text("用户甲的通知正文", exact=False)).to_have_count(0)
            expect(page.get_by_text("用户甲的私有任务", exact=False)).to_have_count(0)
            page.get_by_placeholder("用户名", exact=True).fill("权限用户乙")
            page.get_by_placeholder("密码", exact=True).fill("local-only-password")
            page.get_by_role("button", name=re.compile(r"^登\s*录$")).click()
            expect(page.get_by_role("button", name="权限用户乙 普通用户", exact=True)).to_be_visible(timeout=15000)
            inspect_return("乙")
            expect(page.get_by_text("用户甲的通知正文", exact=False)).to_have_count(0)
            expect(page.get_by_text("用户甲的私有任务", exact=False)).to_have_count(0)
            expect(page.get_by_text(f"用户甲的{private_detail}", exact=False)).to_have_count(0)
            assert {owner for owner, read_path in reads if read_path.startswith("/console/inbox/traces/") or read_path.endswith("/history")} == {"甲", "乙"}
            assert not mutations, mutations
            assert not unexpected, unexpected
            assert not errors, errors
        except Exception as exc:
            raise AssertionError({"page": page.locator("body").inner_text()[:2600], "errors": errors, "reads": reads}) from exc
        finally:
            browser.close()
