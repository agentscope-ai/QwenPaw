# -*- coding: utf-8 -*-
"""
QwenPaw Chat sidebar end-to-end tests (Sprint 4).

Cases:
- SIDEBAR-001  P1  test_sidebar_date_groups_and_collapse   (upstream #5643)

SIDEBAR-001 mocks ``GET /api/chats?archived=false`` via page.route because
the backend cannot backfill timestamps (patch forces "now"), so date
buckets are otherwise impossible to construct. All assertions stay UI-side.

"""
from __future__ import annotations

import logging

import pytest
from playwright.sync_api import expect

from pages.chat_page import ChatPage
from mocks import sidebar_sessions
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
        """Upstream re-architected the sidebar into user groups that each
        contain date buckets (pinned / today / week / month / older).
        Date headers are non-collapsible; the user-group header toggles
        the whole bucket. This case verifies:

        1. The default group header renders
        2. Date headers for the crafted sessions render (pinned/today/week)
        3. Expanded group shows its sessions
        4. Collapsing the group hides its sessions
        5. Expanding again restores them

        .. versionchanged:: 2026-09-18
           Adapted to upstream #7788 (``redesign sidebar session list for
           small screens``), which changed the date-grouping model in two
           ways this case used to assume away:

           * In ``date`` grouping mode the list renders only the
             ``today`` / ``week`` / ``older`` tiers
             (``SidebarSessionList.tsx``:
             ``(["today", "week", "older"] as const).map(...)``).
             ``pinned`` is **no longer its own date bucket**: pinned
             conversations float to the top of *their* recency tier
             (``tierOfSession`` maps them through ``getDateGroup`` and the
             ordered list puts pinned first).  Step 2 asserting a
             ``pinned`` date header can therefore never pass; the pinned
             session is asserted *visible inside* its tier instead.
           * ``SessionDateHeader`` became collapsible itself (it now
             carries ``role="button"``, ``aria-expanded`` and an
             ``onToggle``), while ``SessionGroupHeader`` only renders in
             ``source`` grouping mode.  Steps 4/5 therefore toggle the
             **date** header, not a user-group header that no longer
             exists in this mode.
        """
        test_name = request.node.name

        log_test_step("1. Mock the sidebar list with 5 crafted-timestamp sessions")
        sidebar_sessions.register(page)
        # SidebarSessionList defaults to source grouping. Pin date grouping
        # before the app boots so the date buckets under test are rendered.
        page.add_init_script(
            "try { localStorage.setItem("
            "'qwenpaw_session_group_mode', 'date'); }"
            " catch (e) {}"
        )
        chat = ChatPage(page)
        chat.open()

        log_test_step("2. Date headers render for the crafted buckets")
        # #7788: only today/week/older render as date buckets; "pinned" is a
        # float-to-top ordering inside its recency tier, not a bucket, so it
        # has no header to assert here.
        for group in ("today", "week"):
            expect(chat.get_sidebar_group_header(group)).to_be_visible(
                timeout=chat.timeout
            )

        log_test_step("3. Expanded group shows its sessions")
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.PINNED_NAME)
        ).to_be_visible(timeout=chat.timeout)
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.TODAY_NAME)
        ).to_be_visible(timeout=chat.timeout)
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.WEEK_NAME)
        ).to_be_visible(timeout=chat.timeout)

        log_test_step("4. Collapsing the date group hides its sessions")
        # #7788: the date header itself is the collapsible control now
        # (SessionDateHeader carries aria-expanded + onToggle); the old
        # user-group header only exists in "source" grouping mode.
        chat.get_sidebar_group_header("today").click()
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.TODAY_NAME)
        ).not_to_be_visible(timeout=5000)

        log_test_step("5. Expanding again restores them")
        chat.get_sidebar_group_header("today").click()
        expect(
            chat.get_sidebar_session_by_name(sidebar_sessions.TODAY_NAME)
        ).to_be_visible(timeout=chat.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
