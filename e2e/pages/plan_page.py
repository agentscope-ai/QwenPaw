# -*- coding: utf-8 -*-
"""
QwenPaw Plan Mode page object.

UI-driven only. Pure API contract tests for ``/api/agents/{id}/plan/*``
live in ``tests/integration/``. This page object exposes:

- The agent-config Plan Mode toggle (UI primary path).
- Helpers to navigate /chat after Plan Mode is enabled.
- Disk seeding for ``<workspace>/sessions/<session_id>.json`` so the
  plan Drawer can render an existing plan without a real LLM run.
- A small API helper that flips ``/plan/config`` (test-setup only —
  this is the same plumbing the Agent Config UI uses).

Cases covered:
- PLAN-001 P0  test_plan_mode_toggle_in_agent_config
- PLAN-002 P1  test_plan_button_appears_when_enabled
- PLAN-003 P1  test_plan_panel_drawer_opens_with_empty_state
- PLAN-004 P0  test_plan_panel_renders_seeded_plan
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class PlanPage(BasePage):
    """Page object + seed helpers for Plan Mode."""

    AGENT_CONFIG_URL = f"{config.base_url}/agent-config"
    CHAT_URL = f"{config.base_url}/chat"
    AGENT_ID_DEFAULT = "default"

    # ========== Selectors ==========

    # The Plan Mode form-item on /agent-config (ReAct Agent tab).
    # We anchor on the bilingual label and walk to the adjacent Switch.
    PLAN_MODE_LABEL = (
        'label:has-text("Plan Mode"), '
        'label:has-text("计划模式")'
    )
    # Within the same form-item the Switch is a button[role="switch"].
    PLAN_MODE_SWITCH = (
        '.qwenpaw-form-item:has(label:has-text("Plan Mode")) '
        'button[role="switch"], '
        '.qwenpaw-form-item:has(label:has-text("计划模式")) '
        'button[role="switch"]'
    )

    # Save button at the bottom of the agent-config form.
    SAVE_BTN = (
        'button.qwenpaw-btn-primary:has-text("Save"), '
        'button.qwenpaw-btn-primary:has-text("保存")'
    )

    # Plan button in the Chat action group — only visible when
    # planEnabled=true. The button itself is icon-only with a tooltip.
    # We anchor on the tooltip's name via aria-label fallback, plus
    # a tooltip-text match after hover.
    CHAT_PLAN_TOOLTIP = (
        '[role="tooltip"]:has-text("Plan"), '
        '[role="tooltip"]:has-text("计划")'
    )

    # PlanPanel Drawer (right-side antd Drawer wrapped with qwenpaw prefix).
    # Drawer opens with a known title; empty-state and plan title text
    # are matched bilingually.
    PLAN_DRAWER = '.qwenpaw-drawer-content-wrapper'
    PLAN_EMPTY_STATE = (
        'text=/(No active plan|暂无活动计划|当前没有计划)/'
    )

    # Plan icon button in ChatActionGroup. The icon is an inline
    # checkmark SVG with a unique ``d`` attribute (see
    # ``console/src/pages/Chat/components/ChatActionGroup/index.tsx``
    # ``PlanIcon``); we anchor on the path so we don't depend on the
    # bilingual tooltip or hashed CSS Module classnames.
    CHAT_PLAN_BUTTON = 'button:has(svg path[d="M9 11l3 3L22 4"])'

    # ========== Workspace path helpers ==========

    @staticmethod
    def working_dir() -> Path:
        from config.settings import config
        return config.working_dir

    @classmethod
    def workspace_dir(cls) -> Path:
        return cls.working_dir() / "workspaces" / cls.AGENT_ID_DEFAULT

    @classmethod
    def session_state_path(cls, session_id: str) -> Path:
        """Path that ``_plan_from_session_state`` reads.

        The plan router calls ``session.get_session_state_dict``
        without a ``user_id`` or ``channel`` argument, so the file
        lives directly under ``sessions/<session_id>.json`` (no
        ``console/`` subdir, no ``default_`` prefix).
        """
        return cls.workspace_dir() / "sessions" / f"{session_id}.json"

    # ========== Seed / clean helpers ==========

    @classmethod
    def seed_plan_session_state(
        cls,
        session_id: str,
        plan_name: str,
        subtasks: Optional[List[dict]] = None,
    ) -> Path:
        """Seed an on-disk session-state file containing a plan_notebook.

        The plan endpoint falls back to this file when the in-memory
        ``_live_plan_cache`` has nothing for the session, so this is
        the cleanest LLM-free way to make the Drawer render real data.
        """
        state = {
            "agent": {
                "plan_notebook": {
                    "storage": {"plans": {}},
                    "current_plan": {
                        "id": f"plan-e2e-{int(time.time() * 1000)}",
                        "name": plan_name,
                        "description": "Seeded plan for UI rendering test",
                        "expected_outcome": "Drawer renders with subtasks",
                        "state": "in_progress",
                        "subtasks": subtasks
                        or [
                            {
                                "name": "Subtask alpha",
                                "description": "First subtask",
                                "expected_outcome": "Alpha done",
                                "outcome": "ok",
                                "state": "done",
                            },
                            {
                                "name": "Subtask bravo",
                                "description": "Second subtask",
                                "expected_outcome": "Bravo done",
                                "outcome": None,
                                "state": "in_progress",
                            },
                            {
                                "name": "Subtask charlie",
                                "description": "Third subtask",
                                "expected_outcome": "Charlie done",
                                "outcome": None,
                                "state": "todo",
                            },
                        ],
                    },
                },
            },
        }
        path = cls.session_state_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Seeded plan session state at %s", path)
        return path

    @classmethod
    def remove_plan_session_state(cls, session_id: str) -> None:
        path = cls.session_state_path(session_id)
        try:
            if path.exists():
                path.unlink()
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to remove %s: %s", path, exc)

    # ========== API helpers (test setup only) ==========

    def _agent_headers(self) -> dict:
        return {"X-Agent-Id": self.AGENT_ID_DEFAULT}

    def api_set_plan_enabled(self, api_context, enabled: bool) -> dict:
        """PUT /plan/config — used as test setup to flip the toggle
        without driving the agent-config UI on every test."""
        resp = api_context.put(
            f"/api/agents/{self.AGENT_ID_DEFAULT}/plan/config",
            data={"enabled": enabled},
            headers=self._agent_headers(),
        )
        assert resp.ok, (
            f"Plan config PUT failed [{resp.status}]: {resp.text()}"
        )
        return resp.json()

    def api_get_plan_enabled(self, api_context) -> bool:
        """GET /plan/config — used to verify post-condition state."""
        resp = api_context.get(
            f"/api/agents/{self.AGENT_ID_DEFAULT}/plan/config",
            headers=self._agent_headers(),
        )
        assert resp.ok, (
            f"Plan config GET failed [{resp.status}]: {resp.text()}"
        )
        return bool(resp.json().get("enabled"))

    # ========== UI helpers ==========

    _init_script_installed = False

    def _install_default_agent_init_script(self) -> None:
        if self._init_script_installed:
            return
        agent = self.AGENT_ID_DEFAULT
        script = (
            "(() => {"
            "  try {"
            f"    const a = '{agent}';"
            "    const blob = JSON.stringify({"
            "      state: { selectedAgent: a, agents: [], lastChatIdByAgent: {} },"
            "      version: 0"
            "    });"
            "    try { localStorage.setItem('qwenpaw-last-used-agent', a); } catch (e) {}"
            "    try { localStorage.setItem('qwenpaw-agent-storage', blob); } catch (e) {}"
            "    try { sessionStorage.setItem('qwenpaw-agent-storage', blob); } catch (e) {}"
            "  } catch (e) {}"
            "})();"
        )
        try:
            self.page.context.add_init_script(script=script)
            self._init_script_installed = True
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not install init script: %s", exc)

    def open_agent_config(self) -> "PlanPage":
        self._install_default_agent_init_script()
        self.page.goto(
            self.AGENT_CONFIG_URL,
            wait_until="commit",
            timeout=self.timeout,
        )
        try:
            self.page.wait_for_load_state(
                "networkidle", timeout=self.timeout,
            )
        except TimeoutError:
            pass
        return self

    def open_chat(self, session_id: Optional[str] = None) -> "PlanPage":
        """Open /chat. ``session_id`` is appended as a query param so
        the chat page can use it when querying /plan/current."""
        self._install_default_agent_init_script()
        url = self.CHAT_URL
        if session_id:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}session_id={session_id}"
        self.page.goto(url, wait_until="commit", timeout=self.timeout)
        try:
            self.page.wait_for_load_state(
                "networkidle", timeout=self.timeout,
            )
        except TimeoutError:
            pass
        return self

    def scroll_plan_mode_into_view(self) -> None:
        label = self.page.locator(self.PLAN_MODE_LABEL).first
        label.scroll_into_view_if_needed(timeout=self.timeout)

    def get_plan_mode_switch_state(self) -> bool:
        """Return True if the on-screen Plan Mode switch is checked."""
        sw = self.page.locator(self.PLAN_MODE_SWITCH).first
        aria = sw.get_attribute("aria-checked", timeout=self.timeout)
        return aria == "true"

    def click_plan_mode_switch(self) -> None:
        sw = self.page.locator(self.PLAN_MODE_SWITCH).first
        sw.click(timeout=self.timeout)

    def click_save(self) -> None:
        save = self.page.locator(self.SAVE_BTN).first
        save.click(timeout=self.timeout)

    def set_window_session_id(self, session_id: str) -> None:
        """Force ``window.currentSessionId`` to the given value.

        PlanPanel reads the backend session id off ``window`` (see
        ``console/src/components/PlanPanel/index.tsx::getBackendSessionId``),
        not from React state. To make the Drawer query
        ``/plan/current`` for our seeded session we have to set this
        global directly.
        """
        self.page.evaluate(
            "(sid) => { window.currentSessionId = sid; }",
            session_id,
        )

    def wait_and_read_session_id(self, timeout: int = 15000) -> str:
        """Wait until the frontend sets ``window.currentSessionId`` and
        return its value.

        After ``page.goto("/chat")``, the chat library auto-creates a
        session and writes the backend session id into this global
        asynchronously. We poll until it's set.
        """
        import time as _time
        deadline = _time.time() + timeout / 1000
        while _time.time() < deadline:
            sid = self.page.evaluate("() => window.currentSessionId || ''")
            if sid:
                logger.info("Read window.currentSessionId = %s", sid)
                return sid
            _time.sleep(0.3)
        raise TimeoutError(
            f"window.currentSessionId not set within {timeout}ms"
        )
