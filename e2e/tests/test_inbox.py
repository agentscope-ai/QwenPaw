# -*- coding: utf-8 -*-
"""
QwenPaw Inbox end-to-end tests.

UI-driven only. Pure API contract tests for /api/console/inbox/* live
in ``tests/integration/test_inbox.py``. The Approvals tab is out of
scope (no seed surface; would require a real LLM-driven protected-tool
call).

Cases:
- INBOX-002 P0  test_inbox_page_renders_with_seeded_events
- INBOX-004 P1  test_message_card_renders_and_modal_opens
- INBOX-005 P1  test_batch_mode_select_and_delete
- INBOX-006 P1  test_sidebar_unread_dot_appears_with_seeded_event
"""
from __future__ import annotations

import logging
import time

import pytest
from playwright.sync_api import expect

from pages.inbox_page import InboxPage
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


def _seed_basic_events(page: InboxPage, run_id: str = "run-e2e-1") -> list:
    """Seed a deterministic 4-event set used by several cases.

    2 cron events (1 read, 1 unread, the unread one carries run_id),
    2 heartbeat events (both unread).
    """
    events = [
        page.make_event(
            event_id="evt-cron-1",
            source_type="cron",
            event_type="cron_result",
            title="Cron Job Daily Digest",
            body="3 articles fetched.",
            payload={"run_id": run_id, "job_name": "daily-digest"},
            read=False,
            created_at=time.time(),
        ),
        page.make_event(
            event_id="evt-cron-2",
            source_type="cron",
            event_type="cron_result",
            title="Cron Job Weekly Report",
            body="Report generated.",
            payload={"job_name": "weekly-report"},
            read=True,
            created_at=time.time() - 60,
        ),
        page.make_event(
            event_id="evt-hb-1",
            source_type="heartbeat",
            event_type="heartbeat_result",
            title="Heartbeat result",
            body="Idle pulse OK.",
            payload={},
            read=False,
            created_at=time.time() - 120,
        ),
        page.make_event(
            event_id="evt-hb-2",
            source_type="heartbeat",
            event_type="heartbeat_result",
            title="Heartbeat result",
            body="Active pulse OK.",
            payload={},
            read=False,
            created_at=time.time() - 180,
        ),
    ]
    page.seed_events(events)
    return events


# ============================================================================
# INBOX-002 P0  Inbox page renders with seeded events
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.inbox
class TestInboxPageRenders:
    """INBOX-002: /inbox shows the message cards once events are seeded."""

    @pytest.mark.test_id("INBOX-002")
    def test_inbox_page_renders_with_seeded_events(
        self,
        inbox_page: InboxPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        try:
            log_test_step("1. Seed events")
            inbox_page.clean_inbox()
            _seed_basic_events(inbox_page)

            log_test_step("2. Open /inbox")
            inbox_page.open()

            log_test_step("3. Page title visible")
            expect(
                inbox_page.page.locator(inbox_page.PAGE_TITLE_TEXT).first
            ).to_be_visible(timeout=inbox_page.timeout)

            log_test_step("4. Push Messages tab visible")
            expect(
                inbox_page.page.locator(inbox_page.TAB_PUSH).first
            ).to_be_visible(timeout=inbox_page.timeout)

            log_test_step("5. At least one message card rendered")
            cards = inbox_page.page.locator(inbox_page.MESSAGE_CARD)
            expect(cards.first).to_be_visible(timeout=inbox_page.timeout)
            assert cards.count() >= 1, (
                f"Expected >=1 message card; got {cards.count()}"
            )

            log_test_result(test_name, True, 0)
            logger.info(
                f"Test {test_name} passed (cards={cards.count()})",
            )
        finally:
            inbox_page.clean_inbox()


# ============================================================================
# INBOX-004 P1  Click a message card → detail modal opens
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.inbox
class TestDetailModal:
    """INBOX-004: Clicking a push message card opens the detail modal."""

    @pytest.mark.test_id("INBOX-004")
    def test_message_card_renders_and_modal_opens(
        self,
        inbox_page: InboxPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        run_id = "run-detail-001"

        try:
            log_test_step("1. Seed one event + matching trace")
            inbox_page.clean_inbox()
            inbox_page.seed_events([
                inbox_page.make_event(
                    event_id="evt-detail-1",
                    title="Detail seed",
                    body="Some body text",
                    payload={"run_id": run_id, "job_name": "detail-job"},
                    read=False,
                ),
            ])
            inbox_page.seed_trace(run_id, {"events": [{"at": time.time()}]})

            log_test_step("2. Open /inbox and click the card")
            inbox_page.open()
            card = inbox_page.page.locator(inbox_page.MESSAGE_CARD).first
            expect(card).to_be_visible(timeout=inbox_page.timeout)
            card.click()

            log_test_step("3. Detail modal opens")
            expect(
                inbox_page.page.locator(inbox_page.DETAIL_MODAL).first
            ).to_be_visible(timeout=inbox_page.timeout)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            inbox_page.clean_inbox()


# ============================================================================
# INBOX-005 P1  Batch mode: enter → select all → delete → cards gone
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.inbox
class TestBatchDelete:
    """INBOX-005: The batch toolbar can select-all and delete.

    The final assertion still hits ``api_list_events`` to wait for the
    backend store to settle (deletes are fire-and-forget from the UI),
    but the *trigger* is fully UI-driven through the batch toolbar.
    """

    @pytest.mark.test_id("INBOX-005")
    def test_batch_mode_select_and_delete(
        self,
        inbox_page: InboxPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        try:
            log_test_step("1. Seed 3 events")
            inbox_page.clean_inbox()
            inbox_page.seed_events([
                inbox_page.make_event(
                    event_id=f"evt-batch-{i}",
                    title=f"Batch seed {i}",
                    read=False,
                )
                for i in range(3)
            ])

            log_test_step("2. Open /inbox and verify cards rendered")
            inbox_page.open()
            cards = inbox_page.page.locator(inbox_page.MESSAGE_CARD)
            expect(cards.first).to_be_visible(timeout=inbox_page.timeout)
            assert cards.count() == 3, (
                f"Expected 3 cards before batch; got {cards.count()}"
            )

            log_test_step("3. Enter batch mode")
            inbox_page.page.locator(
                inbox_page.BATCH_ENTER_BTN
            ).first.click()

            log_test_step("4. Select all current page")
            inbox_page.page.locator(
                inbox_page.BATCH_SELECT_ALL
            ).first.click()

            log_test_step("5. Click Batch Delete and confirm")
            inbox_page.page.locator(
                inbox_page.BATCH_DELETE_BTN
            ).first.click()
            # Popconfirm OK button (may be Popconfirm or Popover variant).
            confirm = inbox_page.page.locator(
                inbox_page.POPCONFIRM_OK
            ).first
            try:
                expect(confirm).to_be_visible(timeout=5000)
                confirm.click()
            except Exception:
                logger.info("No popconfirm dialog appeared; proceeding")

            log_test_step("6. Backend store is empty after delete")
            # Wait for backend to settle (deletes are async-fired).
            for _ in range(15):
                events = inbox_page.api_list_events(api_context)
                if len(events) == 0:
                    break
                time.sleep(0.5)
            events = inbox_page.api_list_events(api_context)
            assert len(events) == 0, (
                f"Expected empty inbox after batch delete; got {len(events)}"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            inbox_page.clean_inbox()


# ============================================================================
# INBOX-006 P1  Sidebar unread dot appears
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.inbox
class TestSidebarUnreadDot:
    """INBOX-006: After seeding an unread event the sidebar Inbox menu
    item shows a Badge dot within the 6s polling window."""

    @pytest.mark.test_id("INBOX-006")
    def test_sidebar_unread_dot_appears_with_seeded_event(
        self,
        inbox_page: InboxPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        try:
            log_test_step("1. Seed one unread event")
            inbox_page.clean_inbox()
            inbox_page.seed_events([
                inbox_page.make_event(
                    event_id="evt-badge-1",
                    title="Badge seed",
                    read=False,
                ),
            ])

            log_test_step("2. Open /chat (any non-inbox page works)")
            inbox_page.open_chat_page()

            log_test_step("3. Wait up to ~18s for the badge polling")
            # Sidebar polls every 6s and the first poll fires after the
            # initial render — give enough headroom for two cycles.
            badge = inbox_page.page.locator(
                inbox_page.SIDEBAR_INBOX_BADGE
            ).first
            expect(badge).to_be_visible(timeout=18000)

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            inbox_page.clean_inbox()
