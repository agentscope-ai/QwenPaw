# -*- coding: utf-8 -*-
"""Task 4.5-C/1-F 真实页面全角色记忆作用域验收。"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from config.settings import config


def _credentials(prefix: str) -> tuple[str, str]:
    username = os.getenv(f"QWENPAW_E2E_{prefix}_USERNAME", "").strip()
    password = os.getenv(f"QWENPAW_E2E_{prefix}_PASSWORD", "").strip()
    if not username or not password:
        pytest.skip(f"Missing QWENPAW_E2E_{prefix}_USERNAME/PASSWORD")
    return username, password


def _login(page: Page, username: str, password: str) -> None:
    page.goto(f"{config.base_url}/login", wait_until="networkidle")
    page.evaluate(
        "localStorage.setItem('qwenpaw.desktop-mode-hint.dismissed', '1')"
    )
    inputs = page.locator("input")
    expect(inputs).to_have_count(2)
    inputs.nth(0).fill(username)
    inputs.nth(1).fill(password)
    page.locator("form button[type='submit']").click()
    page.wait_for_url(lambda url: "/login" not in url, timeout=15_000)


def _select_agent(page: Page, agent_id: str) -> None:
    page.evaluate(
        "agentId => localStorage.setItem('qwenpaw-last-used-agent', agentId)",
        agent_id,
    )
    page.evaluate("sessionStorage.clear()")
    page.evaluate(
        "localStorage.setItem('qwenpaw.desktop-mode-hint.dismissed', '1')"
    )


def _assert_scope_tabs(
    page: Page,
    *,
    public: bool,
    private: bool,
) -> None:
    page.get_by_role("tab", name="记忆", exact=True).click()
    public_tab = page.get_by_role("tab", name="公共记忆", exact=True)
    private_tab = page.get_by_role("tab", name="我的记忆", exact=True)
    if public:
        expect(public_tab).to_be_visible(timeout=15_000)
    else:
        expect(public_tab).to_have_count(0)
    if private:
        expect(private_tab).to_be_visible(timeout=15_000)
    else:
        expect(private_tab).to_have_count(0)


def _assert_read_only_memory(page: Page) -> None:
    expect(
        page.get_by_role(
            "button",
            name=re.compile(r"创建记忆|保存记忆|删除记忆|重建索引"),
        )
    ).to_have_count(0)


@pytest.mark.integration
@pytest.mark.memory
def test_memory_scope_full_role_pages(browser: Browser, tmp_path: Path) -> None:
    admin_username, admin_password = _credentials("ADMIN")
    user_username, user_password = _credentials("USER")
    public_agent = os.getenv("QWENPAW_E2E_PUBLIC_AGENT", "default")
    governed_agent = os.getenv(
        "QWENPAW_E2E_GOVERNED_AGENT",
        "task41-member-agent",
    )
    evidence_dir = Path(
        os.getenv("QWENPAW_E2E_EVIDENCE_DIR", str(tmp_path)),
    ).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)

    admin_context = browser.new_context()
    user_context = browser.new_context()
    anonymous_context = browser.new_context()
    try:
        admin_page = admin_context.new_page()
        _login(admin_page, admin_username, admin_password)
        _select_agent(admin_page, public_agent)
        admin_page.goto(f"{config.base_url}/files", wait_until="networkidle")
        _assert_scope_tabs(admin_page, public=True, private=True)
        _assert_read_only_memory(admin_page)
        admin_page.get_by_role("tab", name="公共记忆", exact=True).click()
        _assert_read_only_memory(admin_page)
        admin_page.screenshot(
            path=str(evidence_dir / "admin-owner-memory-scopes.png"),
            full_page=True,
        )

        governance_url = (
            f"{config.base_url}/files?governance=runtime-config"
            f"&agentId={governed_agent}&agentName={governed_agent}"
        )
        admin_page.goto(governance_url, wait_until="networkidle")
        _assert_scope_tabs(admin_page, public=True, private=False)
        _assert_read_only_memory(admin_page)
        admin_page.screenshot(
            path=str(evidence_dir / "admin-governance-public-memory.png"),
            full_page=True,
        )

        user_page = user_context.new_page()
        _login(user_page, user_username, user_password)
        _select_agent(user_page, public_agent)
        user_page.goto(f"{config.base_url}/files", wait_until="networkidle")
        _assert_scope_tabs(user_page, public=True, private=True)
        _assert_read_only_memory(user_page)
        user_page.get_by_role("tab", name="公共记忆", exact=True).click()
        _assert_read_only_memory(user_page)
        user_page.screenshot(
            path=str(
                evidence_dir / "user-public-readonly-private-editable.png"
            ),
            full_page=True,
        )

        anonymous_page = anonymous_context.new_page()
        anonymous_page.goto(f"{config.base_url}/files", wait_until="networkidle")
        expect(anonymous_page).to_have_url(re.compile(r"/login(?:\?|$)"))
    finally:
        anonymous_context.close()
        user_context.close()
        admin_context.close()
