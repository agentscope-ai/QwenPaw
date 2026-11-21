# -*- coding: utf-8 -*-
"""真实前端构建的登录保护和管理员解锁验收；业务请求均由本地 mock 接管。"""

import json
import os
import re
from urllib.parse import urlsplit

import pytest


BASE_URL = os.environ.get("WELDON_TEST_CONSOLE_URL", "")
pytestmark = pytest.mark.skipif(
    not BASE_URL, reason="Set WELDON_TEST_CONSOLE_URL to a local built console"
)
MEMBER_ID = "22222222-2222-4222-8222-222222222222"


class ApiFixture:
    def __init__(self, role=None):
        self.role = role
        self.logins = []
        self.unlocks = []
        self.reads = []
        self.login_unlocked = False
        self.users = [
            {
                "id": MEMBER_ID,
                "username": "sunjun",
                "status": "active",
                "platform_role": "member",
                "login_locked": True,
                "login_retry_after_seconds": 900,
                "login_failed_attempts": 5,
                "login_remaining_attempts": 0,
            },
            {
                "id": "33333333-3333-4333-8333-333333333333",
                "username": "disabled-user",
                "status": "disabled",
                "platform_role": "member",
                "login_locked": True,
                "login_retry_after_seconds": 900,
                "login_failed_attempts": 5,
                "login_remaining_attempts": 0,
            },
        ]

    def route(self, route):
        path = urlsplit(route.request.url).path.removeprefix("/api")
        self.reads.append(path)
        if path.endswith("/stream"):
            route.fulfill(status=204)
            return
        status, payload, headers = 200, {}, {}
        if path == "/auth/status":
            payload = {"enabled": True, "mode": "multi_user", "has_users": True}
        elif path == "/auth/refresh":
            if self.role:
                payload = {"token": "local-test-token", "username": "browser-test"}
            else:
                status, payload = 401, {"detail": "Not authenticated"}
        elif path == "/auth/login":
            submitted = route.request.post_data_json
            self.logins.append(submitted["username"])
            locked = len(self.logins) >= 5
            status = 423 if locked else 401
            payload = {
                "detail": {
                    "code": "account_locked" if locked else "invalid_credentials",
                    "message": "账户已临时锁定，请稍后重试或联系管理员解锁。" if locked else "用户名或密码不正确。",
                    "remaining_attempts": max(0, 5 - len(self.logins)),
                    "retry_after_seconds": 900 if locked else 0,
                    "max_attempts": 5,
                    "lock_duration_seconds": 900,
                }
            }
            if locked:
                headers["Retry-After"] = "900"
            if self.login_unlocked:
                self.role = "member"
                status, payload, headers = 200, {
                    "token": "local-test-only-after-unlock",
                    "username": submitted["username"],
                }, {}
        elif path == "/me":
            payload = {
                "user": {
                    "id": "11111111-1111-4111-8111-111111111111",
                    "username": "browser-test",
                    "platform_role": self.role,
                    "status": "active",
                },
                "preferences": {"language": "zh", "timezone": "Asia/Shanghai"},
            }
        elif path == "/admin/users":
            if self.role == "admin":
                payload = self.users
            else:
                status, payload = 403, {"detail": "forbidden"}
        elif path == f"/admin/users/{MEMBER_ID}/unlock":
            assert route.request.method == "POST"
            assert self.role == "admin"
            self.unlocks.append(MEMBER_ID)
            self.users[0].update(
                login_locked=False, login_retry_after_seconds=0,
                login_failed_attempts=0, login_remaining_attempts=5,
            )
            payload = self.users[0]
        elif path in ("/agents", "/admin/agents"):
            payload = {
                "agents": [{"id": "default", "name": "本地验收智能体", "enabled": True,
                            "access_role": "owner", "can_edit": True}]
            }
        elif path in ("/frontend_plugin", "/slash/catalog", "/loops", "/chats", "/console/attachments"):
            payload = []
        elif path == "/chats/page":
            payload = {"items": [], "has_more": False, "next_cursor": None}
        elif path == "/console/push-messages":
            payload = {"messages": [], "pending_approvals": []}
        elif path == "/console/inbox/events":
            payload = {"events": [], "total": 0, "unread_count": 0}
        elif path in ("/user-input/pending", "/runtime-status/current", "/plan/current"):
            payload = None
        elif path == "/model-catalog":
            payload = {"models": []}
        route.fulfill(status=status, content_type="application/json", headers=headers,
                      body=json.dumps(payload, ensure_ascii=False))


def open_page(browser, fixture, path):
    context = browser.new_context(viewport={"width": 1600, "height": 1000})
    context.route("**/api/**", fixture.route)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{BASE_URL.rstrip('/')}{path}", wait_until="networkidle")
    dismiss = page.get_by_text("我知道了", exact=True)
    if dismiss.is_visible():
        dismiss.click()
    return context, page, errors


def test_login_remaining_attempts_countdown_reload_and_browser_tab_return():
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            api = ApiFixture()
            context, page, errors = open_page(browser, api, "/login?redirect=%2Ffiles")
            username = page.get_by_placeholder("用户名", exact=True)
            password = page.get_by_placeholder("密码", exact=True)
            submit = page.get_by_role("button", name=re.compile(r"^登\s*录$"))
            username.fill("sunjun")
            password.fill("test-only-incorrect")
            for remaining in (4, 3, 2, 1):
                submit.click()
                expect(page.get_by_role("alert").filter(
                    has_text=f"再失败 {remaining} 次将锁定 15 分钟"
                )).to_be_visible()
            submit.click()
            lock = page.get_by_role("alert").filter(has_text="登录暂时锁定")
            expect(lock).to_be_visible()
            expect(lock).to_contain_text(re.compile(r"\d+:\d{2}"))
            expect(lock).to_contain_text("联系管理员")
            expect(submit).to_be_disabled()
            # Both mouse and Enter submissions are blocked while the clock runs.
            submit.evaluate("button => { button.click(); button.click(); }")
            password.press("Enter")
            page.wait_for_timeout(1200)
            assert len(api.logins) == 5
            other = context.new_page()
            other.goto("about:blank")
            other.bring_to_front()
            page.bring_to_front()
            expect(lock).to_be_visible()
            expect(submit).to_be_disabled()
            # Reload does not persist passwords or assume the server lock vanished.
            page.reload(wait_until="networkidle")
            expect(password).to_have_value("")
            username.fill("sunjun")
            password.fill("test-only-incorrect")
            submit.click()
            expect(lock).to_be_visible()
            expect(submit).to_be_disabled()
            assert len(api.logins) == 6
            # An administrator may have unlocked the server before the local clock expires.
            retry = page.get_by_role("button", name="管理员已解锁，重新尝试", exact=True)
            retry.click()
            expect(submit).to_be_enabled()
            assert len(api.logins) == 6
            submit.click()
            expect(lock).to_be_visible()
            expect(submit).to_be_disabled()
            assert len(api.logins) == 7  # Still locked on the server: no local bypass.
            api.login_unlocked = True
            retry.click()
            submit.click()
            page.wait_for_url("**/files")
            expect(page.get_by_role("tab", name="临时附件", exact=True)).to_be_visible()
            assert len(api.logins) == 8
            assert not errors, errors
        finally:
            browser.close()


def test_admin_unlock_chinese_confirm_and_state_survive_menu_return():
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            api = ApiFixture("admin")
            _context, page, errors = open_page(browser, api, "/admin/users")
            row = page.get_by_role("row").filter(has_text="sunjun")
            expect(row).to_contain_text("暂时锁定")
            unlock = row.get_by_role("button", name="解锁登录", exact=True)
            unlock.click()
            dialog = page.get_by_role("dialog").filter(has_text="解除登录锁定")
            expect(dialog).to_contain_text("不会修改密码")
            cancel = dialog.get_by_role("button", name=re.compile(r"^取\s*消$"))
            expect(cancel).to_be_visible()
            cancel.click()
            assert api.unlocks == []
            unlock.click()
            dialog.get_by_role("button", name="解锁登录", exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(row).to_contain_text("未锁定")
            expect(unlock).to_be_disabled()
            expect(page.get_by_text("登录锁定及失败次数已清除", exact=True)).to_be_visible()
            disabled = page.get_by_role("row").filter(has_text="disabled-user")
            expect(disabled.get_by_role("button", name="解锁登录", exact=True)).to_be_disabled()
            page.get_by_text("文件", exact=True).first.click()
            page.wait_for_url("**/files")
            page.get_by_text("用户管理", exact=True).first.click()
            page.wait_for_url("**/admin/users")
            expect(row).to_contain_text("未锁定")
            page.reload(wait_until="networkidle")
            expect(row).to_contain_text("未锁定")
            assert api.unlocks == [MEMBER_ID]
            assert not errors, errors
        finally:
            browser.close()


def test_member_cannot_open_user_management_or_fetch_platform_user_rows():
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            api = ApiFixture("member")
            _context, page, errors = open_page(browser, api, "/admin/users")
            expect(page.get_by_text("无权访问", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="解锁登录", exact=True)).to_have_count(0)
            assert "/admin/users" not in api.reads
            assert api.unlocks == []
            assert not errors, errors
        finally:
            browser.close()
