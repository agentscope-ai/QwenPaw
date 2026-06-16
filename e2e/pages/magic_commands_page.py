# -*- coding: utf-8 -*-
"""
QwenPaw Magic Commands page object.

Magic Commands are slash-prefixed commands typed into the chat input
(e.g. ``/history``, ``/model``, ``/clear``). They route through the
console SSE endpoint (``POST /api/console/chat``) but most of them
execute synchronously in handler code without ever calling the LLM.

This page object centralises:
- A small SSE parser that pulls the final assistant text out of the
  streaming response.
- A ``send_command`` helper that posts a slash command and returns
  that text.
- A ``seed_history_jsonl`` helper that fabricates a debug-history
  JSONL file under the workspace dir, so ``/load_history`` can pull
  a deterministic conversation into memory without any LLM calls.

Cases covered:
- MAGIC-001 P0   test_history_with_seeded_dialog
- MAGIC-002 P0   test_clear_resets_seeded_history
- MAGIC-003 P0   test_dump_then_load_round_trip
- MAGIC-004 P0   test_message_inspect_specific_index
- MAGIC-005 P0   test_model_shows_current
- MAGIC-006 P1   test_model_list_includes_active_marker
- MAGIC-007 P1   test_model_switch_and_reset
- MAGIC-008 P1   test_status_reports_running
- MAGIC-009 P1   test_new_with_seeded_history_resets
- MAGIC-010 P1   test_compact_str_when_no_summary
- MAGIC-011 P2   test_daemon_version
- MAGIC-012 P2   test_load_history_missing_file_fails
- MAGIC-013 P0   test_compact_with_seeded_history    (xfail, requires_llm)
- MAGIC-014 P1   test_summarize_status_after_compact (xfail, requires_llm)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


# Default debug-history filename written / read by /dump_history and
# /load_history. See ``src/qwenpaw/constant.py:DEBUG_HISTORY_FILE``.
DEBUG_HISTORY_FILE = "debug_history.jsonl"


class MagicCommandsPage(BasePage):
    """Page object for slash-prefixed magic commands."""

    AGENT_ID_DEFAULT = "default"

    # ========== Workspace path helpers ==========

    @staticmethod
    def workspace_dir() -> Path:
        """Return the agent's on-disk workspace dir.

        Honours ``QWENPAW_WORKING_DIR`` (set by the e2e isolation
        scripts) and falls back to ``~/.qwenpaw``.
        """
        working = os.getenv("QWENPAW_WORKING_DIR")
        base = Path(working) if working else Path.home() / ".qwenpaw"
        return base / "workspaces" / "default"

    @classmethod
    def history_jsonl_path(cls) -> Path:
        return cls.workspace_dir() / DEBUG_HISTORY_FILE

    # ========== History seed builder ==========

    @classmethod
    def seed_history_jsonl(
        cls,
        messages: Optional[List[dict]] = None,
    ) -> Path:
        """Write a fake conversation JSONL into the agent workspace.

        Each ``messages`` entry is ``{"role": "user|assistant", "text": str}``.
        We materialise them into agentscope ``Msg`` objects so the format
        matches what ``/load_history`` expects.

        If ``messages`` is None, a small English fixture conversation is
        used. Returns the path to the written file.
        """
        if messages is None:
            messages = [
                {"role": "user", "text": "Help me write a quicksort in Python."},
                {"role": "assistant", "text": "Sure, I can sketch one with a pivot strategy."},
                {"role": "user", "text": "Add type hints please."},
                {"role": "assistant", "text": "Done — List[int] -> List[int] signatures."},
                {"role": "user", "text": "Now also add a small unit test."},
            ]

        # Use agentscope Msg so to_dict() matches load_history's parser.
        from agentscope.message import Msg, TextBlock

        target = cls.history_jsonl_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as f:
            for m in messages:
                msg = Msg(
                    name=m["role"],
                    role=m["role"],
                    content=[TextBlock(type="text", text=m["text"])],
                )
                f.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
        logger.info(
            "Seeded %d history messages → %s", len(messages), target,
        )
        return target

    @classmethod
    def remove_history_jsonl(cls) -> None:
        """Delete the on-disk debug history JSONL if it exists."""
        path = cls.history_jsonl_path()
        try:
            if path.exists():
                path.unlink()
                logger.info("Removed history jsonl at %s", path)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Failed to remove %s: %s", path, exc)

    # ========== SSE invocation ==========

    @staticmethod
    def _build_request_body(text: str, session_id: str) -> dict:
        return {
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                }
            ],
            "meta": {
                "sender_id": "e2e-magic",
                "session_id": session_id,
            },
        }

    @classmethod
    def send_command(
        cls,
        text: str,
        session_id: str,
        timeout: float = 15.0,
    ) -> str:
        """POST a magic command and return the final assistant text.

        We deliberately use stdlib ``urllib`` instead of the playwright
        ``api_context`` fixture because that fixture installs a session
        ``Content-Type: application/json`` header which is fine here,
        but more importantly we want to read the SSE body line-by-line.

        Args:
            text: The slash command, e.g. ``"/history"``.
            session_id: Logical session — use a unique value per test
                so cases don't share memory.
            timeout: Hard ceiling for the whole streaming response.

        Returns:
            The text payload from the *last* ``"completed"`` content
            event in the stream. Empty string when no text events were
            emitted.
        """
        url = f"{config.base_url}/api/console/chat"
        body = json.dumps(
            cls._build_request_body(text, session_id),
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Agent-Id": cls.AGENT_ID_DEFAULT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # Read the whole stream — magic commands are short, so
                # buffering is fine and avoids per-line state.
                raw = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            logger.error("send_command failed for %r: %s", text, exc)
            raise

        return cls._extract_completed_text(raw)

    @staticmethod
    def _extract_completed_text(sse_blob: str) -> str:
        """Pull the final ``status:completed`` content text out of an SSE blob.

        Each event is a ``data: {json}\\n\\n`` chunk. The handler emits
        an in_progress text event followed by an identical completed
        one — we use the *last* completed event to be tolerant of
        partial deltas.
        """
        last_text = ""
        for line in sse_blob.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):].strip()
            if not payload:
                continue
            try:
                evt = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if (
                evt.get("object") == "content"
                and evt.get("status") == "completed"
                and evt.get("type") == "text"
                and isinstance(evt.get("text"), str)
            ):
                last_text = evt["text"]
        return last_text

    # ========== Convenience assertions ==========

    @staticmethod
    def assert_contains(text: str, *needles: str) -> None:
        """Assert every ``needle`` appears in ``text`` (substring match)."""
        for n in needles:
            assert n in text, (
                f"Expected substring {n!r} in command output but it was "
                f"missing.\nFull output:\n{text}"
            )

    # ========== Unique session id ==========

    @staticmethod
    def unique_session_id(label: str) -> str:
        return f"e2e-magic-{label}-{int(time.time() * 1000)}"
