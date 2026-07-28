# -*- coding: utf-8 -*-
"""
QwenPaw Chat sidebar & multi-tab end-to-end tests (Sprint 4).

Cases:
- SIDEBAR-001  P1  test_sidebar_date_groups_and_collapse   (upstream #5643)
- MULTITAB-001 P2  test_non_owner_tab_shows_queue_banner   (upstream #5664)

SIDEBAR-001 mocks ``GET /api/chats?archived=false`` via page.route because
the backend cannot backfill timestamps (patch forces "now"), so date
buckets are otherwise impossible to construct. All assertions stay UI-side.

MULTITAB-001 uses two real pages in the SAME browser context (Web Locks
are shared per origin per context): the first page grabs the
``qwenpaw:queue-owner:<sessionId>`` lock, the second becomes queue-only
and must render the info banner in the sender area.
"""
from __future__ import annotations

import logging

import pytest
from playwright.sync_api import expect

from pages.chat_page import ChatPage
from mocks import sidebar_sessions
from config.settings import config
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


# ============================================================================
# SIDEBAR-001 P1 — sidebar session date grouping (upstream #5643)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.chat_sidebar
class TestSidebarDateGroups:
    """Sidebar buckets: Pinned/Today/7d/30d/Earlier + collapse toggling."""

    @pytest.mark.test_id("SIDEBAR-001")
    def test_sidebar_date_groups_and_collapse(
        self,
        page,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Mock the sidebar list with 5 crafted-timestamp sessions")
        sidebar_sessions.register(page)
        # SidebarSessionList only mounts in the sidebar's *simple* mode
        # (Sidebar.tsx: isSimpleExpanded branch); the default is "full"
        # nav mode, so pin simple mode before the app boots.
        page.add_init_script(
            "try { localStorage.setItem('qwenpaw_sidebar_mode', 'simple'); }"
            " catch (e) {}"
        )
        chat = ChatPage(page)
        chat.open()

        log_test_step("2. All five group headers render")
        for group in ("pinned", "today", "week", "month", "older"):
            expect(chat.get_sidebar_group_header(group)).to_be_visible(
                timeout=chat.timeout
            )

        log_test_step("3. Expanded groups show their sessions")
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.PINNED_NAME)
        ).to_be_visible(timeout=chat.timeout)
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.TODAY_NAME)
        ).to_be_visible(timeout=chat.timeout)
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.WEEK_NAME)
        ).to_be_visible(timeout=chat.timeout)

        log_test_step("4. 'Within 30 days' and 'Earlier' start collapsed")
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.MONTH_NAME)
        ).not_to_be_visible(timeout=5000)
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.OLDER_NAME)
        ).not_to_be_visible(timeout=5000)

        log_test_step("5. Clicking 'Earlier' header expands its sessions")
        chat.toggle_sidebar_group("older")
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.OLDER_NAME)
        ).to_be_visible(timeout=chat.timeout)

        log_test_step("6. Clicking again collapses it back")
        chat.toggle_sidebar_group("older")
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.OLDER_NAME)
        ).not_to_be_visible(timeout=5000)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MULTITAB-001 P2 — non-owner tab queue banner (upstream #5664)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.chat_sidebar
class TestMultiTabQueueBanner:
    """Second tab on the same session becomes queue-only and shows a banner."""

    @pytest.mark.test_id("MULTITAB-001")
    def test_non_owner_tab_shows_queue_banner(
        self,
        page,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Seed a chat via API so both tabs share one session id")
        seed = api_context.post(
            "/api/chats",
            data={
                "name": "E2E MultiTab Banner",
                "user_id": config.test.user_id,
                "channel": config.test.channel,
                "session_id": f"{config.test.channel}:{config.test.user_id}",
            },
        )
        if not seed.ok:
            pytest.skip(f"chat seed failed ({seed.status}); cannot test banner")
        chat_id = (seed.json() or {}).get("id")
        if not chat_id:
            pytest.skip("chat seed returned no id; cannot test banner")

        session_url = f"{config.base_url}/chat/{chat_id}"
        page2 = None
        try:
            log_test_step("2. Tab 1 opens the session and becomes lock owner")
            chat1 = ChatPage(page)
            page.goto(session_url, wait_until="commit", timeout=chat1.timeout)
            expect(page.locator(chat1.CHAT_INPUT).first).to_be_visible(
                timeout=chat1.timeout
            )
            # Give tab 1 time to win the ownership Web Lock (300ms resolve
            # timer + lock acquisition).
            page.wait_for_timeout(1500)

            log_test_step("3. Tab 2 (same context) opens the same session URL")
            page2 = page.context.new_page()
            chat2 = ChatPage(page2)
            page2.goto(session_url, wait_until="commit", timeout=chat2.timeout)
            expect(page2.locator(chat2.CHAT_INPUT).first).to_be_visible(
                timeout=chat2.timeout
            )

            log_test_step("4. Tab 2 shows the queue-only info banner")
            expect(chat2.get_queue_banner()).to_be_visible(timeout=15000)

            log_test_step("5. Tab 1 (owner) shows no banner")
            expect(chat1.get_queue_banner()).not_to_be_visible(timeout=3000)

            log_test_step("6. Closing tab 2 releases nothing it owned; owner keeps clean")
            page2.close()
            page2 = None
            expect(chat1.get_queue_banner()).not_to_be_visible(timeout=3000)
        finally:
            if page2 is not None:
                try:
                    page2.close()
                except Exception:
                    pass
            try:
                api_context.delete(f"/api/chats/{chat_id}")
            except Exception:
                pass

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
