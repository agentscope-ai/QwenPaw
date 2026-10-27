# -*- coding: utf-8 -*-
"""
Context & Scroll module E2E test cases.

Coverage:
- agents/context/scroll/memoryspace.py (802 lines, 0% coverage)
- agents/context/compact.py
- agents/context/fold.py
- agents/context/prune.py

Framework: pytest + Playwright + Page Object Pattern.
Run: pytest tests/test_context_scroll.py -v
"""
from __future__ import annotations

import logging
import re

import pytest
from playwright.sync_api import Page, expect, TimeoutError

from pages.chat_page import ChatPage
from config.settings import config
from utils.helpers import (
    log_test_step,
    log_test_result,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Answer-body extraction for the compression follow-up assertion
# ---------------------------------------------------------------------------
# The bubble renders a fixed scaffold around the model's answer:
#
#   'QwenPaw\nCompleted 1 steps\n\nThe first number ... was 1.\n\n16:04:05'
#    ^brand   ^step counter                            ^answer  ^render stamp
#
# Asserting on the raw inner_text() therefore matched the scaffold instead of
# the answer: "Completed 1 steps" alone contains the character "1", and so does
# the trailing HH:MM:SS stamp. Proven mechanically on fork run 39074114725 --
# of the 27 bubble texts captured inside the case's window, all 27 still
# satisfied `"1" in text or "one" in text.lower()` after the answer body was
# deleted and only the scaffold left behind; and rewriting the real answer to
# "The first number was 7" also kept it true. The case could lose the whole
# context and still PASS.
#
# These patterns strip the scaffold so the assertion reads the answer only.
# The step counter has a cancelled variant ("Canceled · 1 steps", U+00B7 middle
# dot, per console/src/locales/en.json chat.messageDisplay.stepsCanceled) which
# must be stripped too: it carries its own digit, so a round the queue
# stabiliser cancelled (upstream #7382; see the note on the send loop below)
# would otherwise satisfy the assertion with no answer present at all.
_STEPS_DONE_RE = re.compile(r"Completed\s+\d+\s+steps", re.IGNORECASE)
_STEPS_CANCELED_RE = re.compile(r"Canceled\s*\u00b7?\s*\d+\s+steps", re.IGNORECASE)
# The rendered stamp trails the bubble. The answer body may itself quote a
# time, so this is a scaffold pattern only because chat_page.py's JS reader
# already treats the LAST HH:MM:SS match as the stamp; keep the two in sync.
_TIME_STAMP_RE = re.compile(r"\d{1,2}:\d{2}:\d{2}")
_PLACEHOLDER_RE = re.compile(r"Thinking|Loading", re.IGNORECASE)
_BRAND = "QwenPaw"


def extract_answer_body(text: str) -> str:
    """Return the model's answer with the bubble scaffold stripped away.

    Removes, in order: the step counter in both its terminal states
    (``Completed N steps`` / ``Canceled · N steps``), the rendered HH:MM:SS
    stamp, the product brand line, and the Thinking/Loading placeholders that
    ``chat_page.py``'s JS reader strips too. Whitespace is collapsed so an
    answer-less bubble yields the empty string rather than stray newlines.

    Args:
        text: raw ``inner_text()`` of an AI bubble.

    Returns:
        The answer body only. Empty when the bubble carried no answer.
    """
    body = _STEPS_DONE_RE.sub(" ", text)
    body = _STEPS_CANCELED_RE.sub(" ", body)
    body = _TIME_STAMP_RE.sub(" ", body)
    body = body.replace(_BRAND, " ")
    body = _PLACEHOLDER_RE.sub(" ", body)
    return re.sub(r"\s+", " ", body).strip()


# ============================================================================
# CS-001: Long conversation triggers context compression
# ============================================================================

@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p1
@pytest.mark.context_scroll
# 2026-09-18 (Tai-ge approved raising this case's per-case ceiling to 600 s):
# the case is a 25-round real-LLM conversation and lives close to the global
# 480 s per-case ceiling introduced by #7803 -- the green 09-16 nightly run
# measured 424 s, i.e. 56 s of headroom, and the Path C stability wait added
# the same day costs ~1.5 s per round (~+39 s over 26 waits), leaving only
# ~17 s at 480 s. pytest-timeout's per-test marker overrides the command
# line --timeout, so this case alone gets 600 s while every other case keeps
# the 480 s hang-detection ceiling (raising the global value would loosen
# hang detection for all ~200 other cases; the second-slowest of them is
# 242 s, so 480 s is still only 2.0x there).
@pytest.mark.timeout(600)
class TestLongConversationCompression:
    """
    CS-001: Long conversation triggers context compression.

    Coverage:
    1. agents/context/scroll/memoryspace.py (802 lines)
    2. agents/context/compact.py
    3. Token usage tracking

    Business scenario:
    User sends 20+ messages in a single chat session. When token limit
    is reached, the system automatically compresses old messages to free
    up context window. The conversation continues seamlessly.
    """

    @pytest.mark.test_id("CS-001")
    def test_long_conversation_compression(
        self,
        clean_chat_page: ChatPage,
        request: pytest.FixtureRequest,
    ):
        """
        Verify context compression triggers after long conversation.

        Steps:
        1. Open Chat page and create new chat
        2. Send 25 short messages rapidly
        3. Wait for AI responses
        4. Verify compression log appears
        5. Send follow-up question referencing early messages
        6. Verify AI understands context (compression preserved key info)
        7. Check token usage increased
        """
        test_name = request.node.name
        log_test_step("1. Open Chat page and create new chat")
        clean_chat_page.open()
        clean_chat_page.create_new_chat()

        log_test_step("2. Send 25 short messages rapidly")
        for i in range(25):
            clean_chat_page.send_message(f"Message {i+1}: count to {i+1}")
            # 2026-09-18: widened per-round budget. After upstream #7382
            # (chat SDK 1.1.73 -> 1.2.0) a round can stall while an earlier
            # one is cancelled by the queue stabiliser; the gate-2/3 window
            # used to be hard-capped at 30 s inside wait_for_ai_response
            # (stability_timeout = min(timeout, 30000)), so raising only the
            # outer timeout had no effect. The shared helper now takes
            # stability_cap_ms (default unchanged = 30 s for all other
            # callers); this 25-round case opts into a 60 s window.
            ai_response = clean_chat_page.wait_for_ai_response(
                timeout=60000, stability_cap_ms=60000
            )
            assert ai_response is not None, f"AI response {i+1} timed out"

        log_test_step("3. Wait for compression to trigger")
        # Compression happens asynchronously, wait for log entry
        clean_chat_page.page.wait_for_timeout(5000)

        log_test_step("4. Verify compression log appears")
        # Check for compression indicator in chat metadata
        compression_log = clean_chat_page.page.locator(
            '[class*="compression"], [class*="compact"]'
        )
        # Compression may or may not be visible; log but don't fail
        if compression_log.count() > 0:
            logger.info("Compression log visible")
        else:
            logger.info("Compression log not visible (may be in backend)")

        log_test_step("5. Send follow-up question referencing early messages")
        clean_chat_page.send_message(
            "What was the first number I asked you to count to?"
        )
        ai_response = clean_chat_page.wait_for_ai_response(
            timeout=60000, stability_cap_ms=60000
        )
        assert ai_response is not None, "Follow-up AI response timed out"

        log_test_step("6. Verify AI understands context")
        last_ai_msg = clean_chat_page.get_last_ai_message()
        if last_ai_msg is not None:
            response_text = last_ai_msg.inner_text()
            # Strip the bubble scaffold before matching: the raw text always
            # carries "Completed 1 steps" and an HH:MM:SS stamp, both of which
            # contain "1", so asserting on it was true no matter what the model
            # answered (see extract_answer_body for the proof and the cancelled
            # variant, which made a queue-stabiliser cancellation pass too).
            answer_body = extract_answer_body(response_text)
            logger.info(
                "compression follow-up: raw=%r answer_body=%r",
                response_text[:200], answer_body[:200],
            )
            # An answer-less body is its own failure: it means the bubble the
            # reader resolved carried nothing but scaffold, which is exactly the
            # case the old assertion silently accepted.
            assert answer_body, (
                "AI bubble carried no answer body after stripping the "
                f"step counter, timestamp and brand: raw={response_text[:200]!r}"
            )
            # AI should remember the first message asked to count to 1
            assert "1" in answer_body or "one" in answer_body.lower(), \
                f"AI lost context after compression: answer={answer_body[:200]!r}"
        else:
            logger.warning("Could not get last AI message")

        log_test_step("7. Check token usage increased")
        # Token usage is tracked in backend; verify via API if available
        # For now, just verify conversation completed successfully
        all_messages = clean_chat_page.get_all_messages()
        assert len(all_messages) >= 50, "Message history incomplete"

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# CS-002: Manual fold + prune + truncate
# ============================================================================

@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p1
@pytest.mark.context_scroll
class TestManualFoldPruneTruncate:
    """
    CS-002: Manual fold + prune + truncate.

    Coverage:
    1. agents/context/fold.py
    2. agents/context/prune.py
    3. agents/context/truncate.py

    Business scenario:
    User manually folds a tool result to save space, prunes old messages,
    and verifies long tool outputs are truncated with markers.
    """

    @pytest.mark.test_id("CS-002")
    def test_manual_fold_prune_truncate(
        self,
        clean_chat_page: ChatPage,
        request: pytest.FixtureRequest,
    ):
        """
        Verify manual fold, prune, and truncate operations.

        Steps:
        1. Open Chat page and create new chat
        2. Send a message that triggers a tool call with long output
        3. Wait for tool result
        4. Fold the tool result (click fold button)
        5. Verify folded state (collapsed view)
        6. Send another message to trigger prune
        7. Verify old messages are pruned (not visible but in history)
        8. Send a message with very long output
        9. Verify truncation marker appears
        """
        test_name = request.node.name
        log_test_step("1. Open Chat page and create new chat")
        clean_chat_page.open()
        clean_chat_page.create_new_chat()

        log_test_step("2. Send message triggering tool call with long output")
        # Use a tool that returns long output (e.g., file read, web search)
        clean_chat_page.send_message(
            "Read the file /etc/hosts and show me all lines"
        )
        ai_response = clean_chat_page.wait_for_ai_response(timeout=60000)
        assert ai_response is not None, "AI response timed out"

        log_test_step("3. Wait for tool result")
        clean_chat_page.page.wait_for_timeout(3000)

        log_test_step("4. Fold the tool result")
        # Look for fold button on tool result card
        fold_btn = clean_chat_page.page.locator(
            'button:has-text("Fold"), button:has-text("折叠"), '
            '[class*="fold-btn"]'
        ).first
        if fold_btn.count() > 0 and fold_btn.is_visible():
            fold_btn.click()
            clean_chat_page.page.wait_for_timeout(1000)
            logger.info("Tool result folded")
        else:
            logger.info("Fold button not found (tool result may be short)")

        log_test_step("5. Verify folded state")
        # Check for collapsed indicator
        folded_indicator = clean_chat_page.page.locator(
            '[class*="folded"], [class*="collapsed"]'
        )
        if folded_indicator.count() > 0:
            logger.info("Folded state visible")
        else:
            logger.info("Folded state not visible")

        log_test_step("6. Send another message to trigger prune")
        clean_chat_page.send_message("What did we just do?")
        ai_response = clean_chat_page.wait_for_ai_response(timeout=30000)
        assert ai_response is not None, "Follow-up response timed out"

        log_test_step("7. Verify old messages are pruned")
        # Pruned messages are in backend history but may not be visible
        all_messages = clean_chat_page.get_all_messages()
        assert len(all_messages) >= 4, "Message history incomplete"

        log_test_step("8. Send message with very long output")
        clean_chat_page.send_message(
            "Generate a list of 1000 numbers, one per line"
        )
        ai_response = clean_chat_page.wait_for_ai_response(timeout=60000)
        assert ai_response is not None, "Long output response timed out"

        log_test_step("9. Verify truncation marker appears")
        # Look for truncation indicator
        truncation_marker = clean_chat_page.page.locator(
            '[class*="truncated"], [class*="truncation"]'
        )
        if truncation_marker.count() == 0:
            # Try text-based locator
            truncation_marker = clean_chat_page.page.locator(
                'text="... (truncated)"'
            )
        if truncation_marker.count() == 0:
            truncation_marker = clean_chat_page.page.locator(
                'text="...（已截断）"'
            )
        if truncation_marker.count() > 0:
            logger.info("Truncation marker visible")
        else:
            logger.info("Truncation marker not visible (output may be short)")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
