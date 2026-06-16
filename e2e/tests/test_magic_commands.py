# -*- coding: utf-8 -*-
"""
QwenPaw Magic Commands end-to-end tests.

All 14 cases drive the console SSE endpoint via a small urllib-based
helper in ``MagicCommandsPage``. Twelve cases avoid the LLM entirely
by seeding the agent's debug-history JSONL on disk and using
``/load_history`` to pull a deterministic conversation into memory.
The two remaining cases (``/compact``, ``/summarize_status``) need a
real LLM and are gated behind ``requires_llm`` + ``xfail`` so they
skip cleanly on machines without a key.

Each test uses a unique ``session_id`` so cases never share memory.
"""
from __future__ import annotations

import logging
import time

import pytest

from pages.magic_commands_page import MagicCommandsPage
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


# ============================================================================
# MAGIC-001 P0  /history with seeded dialog
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.magic_commands
class TestHistoryWithSeededDialog:
    """MAGIC-001: /history reflects messages loaded via /load_history."""

    @pytest.mark.test_id("MAGIC-001")
    def test_history_with_seeded_dialog(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("hist")

        log_test_step("1. Seed 5 messages into debug_history.jsonl")
        magic_commands_page.seed_history_jsonl()

        try:
            log_test_step("2. /load_history pulls the seeded messages in")
            load_out = magic_commands_page.send_command("/load_history", sid)
            magic_commands_page.assert_contains(
                load_out, "History Loaded", "Messages loaded: 5",
            )

            log_test_step("3. /history reports 5 messages")
            hist_out = magic_commands_page.send_command("/history", sid)
            magic_commands_page.assert_contains(
                hist_out,
                "Conversation History",
                "Total messages: 5",
                "quicksort",  # seeded text
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            magic_commands_page.remove_history_jsonl()


# ============================================================================
# MAGIC-002 P0  /clear resets seeded history
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.magic_commands
class TestClearResets:
    """MAGIC-002: After /clear, /history shows zero messages."""

    @pytest.mark.test_id("MAGIC-002")
    def test_clear_resets_seeded_history(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("clear")

        log_test_step("1. Seed + load 5 messages")
        magic_commands_page.seed_history_jsonl()

        try:
            magic_commands_page.send_command("/load_history", sid)

            log_test_step("2. /clear succeeds")
            clear_out = magic_commands_page.send_command("/clear", sid)
            magic_commands_page.assert_contains(clear_out, "History Cleared")

            log_test_step("3. /history now reports 0 messages")
            hist_out = magic_commands_page.send_command("/history", sid)
            magic_commands_page.assert_contains(
                hist_out, "Total messages: 0",
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            magic_commands_page.remove_history_jsonl()


# ============================================================================
# MAGIC-003 P0  /dump_history → /load_history round-trip
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.magic_commands
class TestDumpLoadRoundTrip:
    """MAGIC-003: dump-then-load preserves messages on disk."""

    @pytest.mark.test_id("MAGIC-003")
    def test_dump_then_load_round_trip(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("dump")

        log_test_step("1. Seed + load 5 messages into memory")
        magic_commands_page.seed_history_jsonl()
        magic_commands_page.send_command("/load_history", sid)

        try:
            log_test_step("2. /dump_history writes them back to disk")
            dump_out = magic_commands_page.send_command("/dump_history", sid)
            magic_commands_page.assert_contains(
                dump_out, "History Dumped", "Messages saved: 5",
            )
            jsonl = magic_commands_page.history_jsonl_path()
            assert jsonl.exists(), f"Expected {jsonl} to exist after dump"
            assert jsonl.stat().st_size > 0, "Dump file must be non-empty"

            log_test_step("3. /load_history re-reads the file successfully")
            reload_out = magic_commands_page.send_command(
                "/load_history",
                magic_commands_page.unique_session_id("dump-reload"),
            )
            magic_commands_page.assert_contains(
                reload_out, "History Loaded", "Messages loaded: 5",
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            magic_commands_page.remove_history_jsonl()


# ============================================================================
# MAGIC-004 P0  /message <index> shows specific message
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.magic_commands
class TestMessageInspect:
    """MAGIC-004: /message <index> returns that message's full content."""

    @pytest.mark.test_id("MAGIC-004")
    def test_message_inspect_specific_index(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("msg")

        magic_commands_page.seed_history_jsonl()
        try:
            magic_commands_page.send_command("/load_history", sid)

            log_test_step("1. /message 1 shows the first user message")
            out = magic_commands_page.send_command("/message 1", sid)
            magic_commands_page.assert_contains(
                out, "Message 1", "quicksort",
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            magic_commands_page.remove_history_jsonl()


# ============================================================================
# MAGIC-005 P0  /model shows current model
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.magic_commands
class TestModelShowsCurrent:
    """MAGIC-005: /model with no args shows the active provider/model."""

    @pytest.mark.test_id("MAGIC-005")
    def test_model_shows_current(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("model")

        out = magic_commands_page.send_command("/model", sid)
        magic_commands_page.assert_contains(
            out, "Current Model", "Provider:",
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MAGIC-006 P1  /model list contains [ACTIVE] marker
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.magic_commands
class TestModelList:
    """MAGIC-006: /model list shows providers and the [ACTIVE] tag."""

    @pytest.mark.test_id("MAGIC-006")
    def test_model_list_includes_active_marker(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("model-list")

        out = magic_commands_page.send_command("/model list", sid)
        magic_commands_page.assert_contains(
            out, "Available Models", "[ACTIVE]",
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MAGIC-007 P1  /model <p>:<m> switch then reset
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.magic_commands
class TestModelSwitchAndReset:
    """MAGIC-007: switch to an alternate model, verify, then reset."""

    @pytest.mark.test_id("MAGIC-007")
    def test_model_switch_and_reset(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("model-sw")

        log_test_step("1. Discover an alternate provider:model pair")
        list_out = magic_commands_page.send_command("/model list", sid)
        # Pick the first provider/model line that is NOT marked ACTIVE.
        # Format example:  - `qwen3-max`
        candidate = None
        provider = None
        for line in list_out.splitlines():
            stripped = line.strip()
            if stripped.startswith("**Provider:"):
                # Provider header looks like:
                #   **Provider: DashScope** (`dashscope`)
                # Pull the id from inside the backticks.
                if "`" in stripped:
                    parts = stripped.split("`")
                    if len(parts) >= 2:
                        provider = parts[1]
                continue
            if "[ACTIVE]" in stripped:
                continue
            if stripped.startswith("- `") and "`" in stripped[3:]:
                candidate = stripped[3:].split("`", 1)[0]
                if provider:
                    break
        if not (provider and candidate):
            pytest.skip(
                "No non-active provider:model candidate found in /model list",
            )

        target = f"{provider}:{candidate}"
        log_test_step(f"2. Switch to {target}")
        try:
            switch_out = magic_commands_page.send_command(
                f"/model {target}", sid,
            )
            magic_commands_page.assert_contains(
                switch_out, "Model Switched",
            )

            log_test_step("3. /model reports the new selection")
            cur_out = magic_commands_page.send_command("/model", sid)
            magic_commands_page.assert_contains(
                cur_out, candidate,
            )
        finally:
            log_test_step("4. /model reset")
            reset_out = magic_commands_page.send_command(
                "/model reset", sid,
            )
            magic_commands_page.assert_contains(
                reset_out, "Model Reset",
            )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed (target={target})")


# ============================================================================
# MAGIC-008 P1  /status reports daemon is running
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.magic_commands
class TestStatus:
    """MAGIC-008: /status returns daemon health info."""

    @pytest.mark.test_id("MAGIC-008")
    def test_status_reports_running(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("status")

        out = magic_commands_page.send_command("/status", sid)
        magic_commands_page.assert_contains(
            out, "Daemon Status", "Working dir:",
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MAGIC-009 P1  /new resets seeded history
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.magic_commands
class TestNewResets:
    """MAGIC-009: /new clears the in-memory dialog like /clear does."""

    @pytest.mark.test_id("MAGIC-009")
    def test_new_with_seeded_history_resets(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("new")

        magic_commands_page.seed_history_jsonl()
        try:
            magic_commands_page.send_command("/load_history", sid)

            log_test_step("1. /new returns confirmation")
            new_out = magic_commands_page.send_command("/new", sid)
            magic_commands_page.assert_contains(
                new_out, "New Conversation Started",
            )

            log_test_step("2. /history reports 0 messages")
            hist_out = magic_commands_page.send_command("/history", sid)
            magic_commands_page.assert_contains(
                hist_out, "Total messages: 0",
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            magic_commands_page.remove_history_jsonl()


# ============================================================================
# MAGIC-010 P1  /compact_str when no summary exists
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.magic_commands
class TestCompactStrNoSummary:
    """MAGIC-010: /compact_str on a fresh session reports no summary."""

    @pytest.mark.test_id("MAGIC-010")
    def test_compact_str_when_no_summary(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("cstr")

        out = magic_commands_page.send_command("/compact_str", sid)
        magic_commands_page.assert_contains(out, "No Compressed Summary")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MAGIC-011 P2  /daemon version
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.magic_commands
class TestDaemonVersion:
    """MAGIC-011: /daemon version surfaces version + working dir."""

    @pytest.mark.test_id("MAGIC-011")
    def test_daemon_version(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("ver")

        out = magic_commands_page.send_command("/daemon version", sid)
        magic_commands_page.assert_contains(
            out, "Daemon version", "Working dir:",
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MAGIC-012 P2  /load_history with no file → Load Failed
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.magic_commands
class TestLoadHistoryMissingFile:
    """MAGIC-012: /load_history reports a friendly failure when no file."""

    @pytest.mark.test_id("MAGIC-012")
    def test_load_history_missing_file_fails(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("load-miss")

        # Make sure no stale jsonl is hanging around from another test.
        magic_commands_page.remove_history_jsonl()
        out = magic_commands_page.send_command("/load_history", sid)
        magic_commands_page.assert_contains(out, "Load Failed")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# MAGIC-013 P0  /compact with seeded history (xfail, requires LLM)
# ============================================================================

@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p0
@pytest.mark.magic_commands
class TestCompactWithLLM:
    """
    MAGIC-013: /compact on real history calls the LLM and produces a
    compressed summary. Strongly LLM-dependent — declared xfail
    strict=False so a missing or flaky LLM doesn't break the suite.
    """

    @pytest.mark.test_id("MAGIC-013")
    @pytest.mark.xfail(
        reason="Requires a configured LLM; LLM responses can be flaky.",
        strict=False,
    )
    def test_compact_with_seeded_history(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("compact")

        magic_commands_page.seed_history_jsonl()
        try:
            magic_commands_page.send_command("/load_history", sid)
            out = magic_commands_page.send_command(
                "/compact", sid, timeout=120.0,
            )
            magic_commands_page.assert_contains(
                out, "Compact Complete", "Compressed Summary",
            )
            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            magic_commands_page.remove_history_jsonl()


# ============================================================================
# MAGIC-014 P1  /summarize_status after /compact (xfail, requires LLM)
# ============================================================================

@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p1
@pytest.mark.magic_commands
class TestSummarizeStatusAfterCompact:
    """MAGIC-014: /summarize_status surfaces the background summary task."""

    @pytest.mark.test_id("MAGIC-014")
    @pytest.mark.xfail(
        reason="Depends on a successful /compact run and LLM response.",
        strict=False,
    )
    def test_summarize_status_after_compact(
        self,
        magic_commands_page: MagicCommandsPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        sid = magic_commands_page.unique_session_id("sumstatus")

        magic_commands_page.seed_history_jsonl()
        try:
            magic_commands_page.send_command("/load_history", sid)
            magic_commands_page.send_command(
                "/compact", sid, timeout=120.0,
            )
            # Give the background summary task a beat to register.
            time.sleep(2)
            out = magic_commands_page.send_command(
                "/summarize_status", sid,
            )
            magic_commands_page.assert_contains(
                out, "Summary Task Status",
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            magic_commands_page.remove_history_jsonl()
