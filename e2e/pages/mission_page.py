# -*- coding: utf-8 -*-
"""
QwenPaw Mission Mode page object.

Mission Mode (``/mission`` command) has no dedicated REST endpoint or
UI page — every external touchpoint goes through the console SSE
endpoint. The state machine is purely file-system:
``<workspace>/missions/mission-<ts>/{prd.json, loop_config.json,
task.md, progress.txt}``. We exercise the read-only sub-commands and
the early-return paths inside Phase 2 (invalid PRD) — both completely
LLM-free — and avoid driving a full master/worker/verifier pipeline.

Cases covered:
- MISSION-001 P0  test_mission_list_with_seeded_dir
- MISSION-002 P1  test_mission_status_no_active
- MISSION-003 P1  test_mission_list_empty
- MISSION-004 P1  test_mission_help_for_short_input
- MISSION-005 P2  test_mission_list_orders_two_missions
- MISSION-006 P2  test_invalid_prd_rejected_when_entering_phase2
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class MissionPage(BasePage):
    """Page object + seed helpers for Mission Mode."""

    AGENT_ID_DEFAULT = "default"

    # ========== Workspace path helpers ==========

    @staticmethod
    def working_dir() -> Path:
        working = os.getenv("QWENPAW_WORKING_DIR")
        return Path(working) if working else Path.home() / ".qwenpaw"

    @classmethod
    def workspace_dir(cls, agent_id: str = "") -> Path:
        agent_id = agent_id or cls.AGENT_ID_DEFAULT
        return cls.working_dir() / "workspaces" / agent_id

    @classmethod
    def missions_dir(cls, agent_id: str = "") -> Path:
        return cls.workspace_dir(agent_id) / "missions"

    # ========== Helpers ==========

    @staticmethod
    def unique_session_id(label: str) -> str:
        return f"e2e-mission-{label}-{int(time.time() * 1000)}"

    @staticmethod
    def unique_mission_ts(offset_ms: int = 0) -> int:
        return int(time.time() * 1000) + offset_ms

    # ========== Seed / clean (file-system) ==========

    @classmethod
    def clean_missions(cls) -> None:
        directory = cls.missions_dir()
        try:
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to clean %s: %s", directory, exc)

    @classmethod
    def seed_mission(
        cls,
        *,
        ts: int,
        session_id: str,
        current_phase: str = "completed",
        max_iterations: int = 1,
        project: str = "e2e-fixture",
        branch_name: str = "mission/e2e-fixture",
        stories: Optional[List[dict]] = None,
        invalid_prd: bool = False,
    ) -> Path:
        """Materialise a mission directory on disk.

        Returns the path to the new ``mission-<ts>`` directory.
        """
        mdir = cls.missions_dir() / f"mission-{ts}"
        mdir.mkdir(parents=True, exist_ok=True)

        (mdir / "task.md").write_text("seeded e2e task", encoding="utf-8")
        (mdir / "progress.txt").write_text("", encoding="utf-8")

        loop_cfg = {
            "current_phase": current_phase,
            "session_id": session_id,
            "max_iterations": max_iterations,
            "git_installed": False,
            "is_git_repo": False,
            "default_branch": "",
            "branch_name": branch_name,
            "repo_root": "",
            "workspace_dir": str(cls.workspace_dir()),
            "verify_commands": "",
        }
        (mdir / "loop_config.json").write_text(
            json.dumps(loop_cfg, indent=2),
            encoding="utf-8",
        )

        if invalid_prd:
            # Schema-invalid: missing userStories array entirely.
            prd = {"project": project}
        else:
            prd = {
                "project": project,
                "branchName": branch_name,
                # Use project as description so /mission list (which
                # prefers description over project when rendering)
                # surfaces a unique label per seed.
                "description": project,
                "userStories": stories
                or [
                    {
                        "id": "US-001",
                        "title": "Story one",
                        "description": "Implement story one",
                        "acceptanceCriteria": ["a1"],
                        "priority": 1,
                        "passes": True,
                        "notes": "",
                    },
                ],
            }
        (mdir / "prd.json").write_text(
            json.dumps(prd, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Seeded mission %s (phase=%s)", mdir, current_phase)
        return mdir

    # ========== SSE invocation ==========

    @classmethod
    def send_chat(
        cls,
        text: str,
        session_id: str,
        timeout: float = 30.0,
    ) -> str:
        """POST a chat message and return the final assistant text.

        Uses stdlib urllib so we can read the SSE body directly. The
        ``session_id`` MUST be a top-level field — not under ``meta`` —
        because the runner reads ``request.session_id`` to drive the
        Mission state machine (see app/routers/console.py and
        app/runner/runner.py).
        """
        url = f"{config.base_url}/api/console/chat"
        body = json.dumps(
            {
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": text}],
                    }
                ],
                "session_id": session_id,
            }
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
                raw = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            logger.error("send_chat failed for %r: %s", text, exc)
            raise
        return cls._extract_completed_text(raw)

    @staticmethod
    def _extract_completed_text(sse_blob: str) -> str:
        """Pull the final ``status:completed`` content text out of SSE."""
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
        for n in needles:
            assert n in text, (
                f"Expected substring {n!r} in mission output but it was "
                f"missing.\nFull output:\n{text}"
            )
