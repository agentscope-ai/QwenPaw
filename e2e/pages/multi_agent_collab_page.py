# -*- coding: utf-8 -*-
"""
QwenPaw Multi-Agent Collaboration page object.

This module is purely API-driven — there is no UI surface for the
cross-agent routing / fork / task-state-machine plumbing. We exercise:

- Agent CRUD via ``/api/agents`` (only as setup for collaboration cases —
  basic CRUD is already covered by ``test_agents.py``).
- Background-task submission and polling via
  ``/api/agent/process/task[/{task_id}]``.
- Worktree-based fork preparation via ``/api/fork/agent``.
- Per-agent status read-out via ``/api/agents/{id}/agent-status``.

Cases covered:
- MA-001  P0  test_seed_two_agents_appear_in_list
- MA-002  P0  test_x_agent_id_header_routes_request
- MA-003  P0  test_submit_to_agent_returns_task_id
- MA-004  P0  test_check_agent_task_status_progresses     (xfail, requires_llm)
- MA-005  P1  test_chat_with_agent_sse_routes_to_target   (xfail, requires_llm)
- MA-006  P1  test_fork_agent_creates_worktree
- MA-007  P1  test_disabled_agent_status_reflects_state
- MA-008  P1  test_unknown_target_agent_task_response
- MA-009  P2  test_default_agent_protected_from_delete
- MA-010  P2  test_agent_order_preserved_after_create
- MA-011  P2  test_seeded_agent_workspace_dir_created
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class MultiAgentCollabPage(BasePage):
    """Page object for the Multi-Agent collaboration HTTP surface."""

    AGENT_ID_DEFAULT = "default"

    # ========== Workspace path helpers ==========

    @staticmethod
    def working_dir() -> Path:
        """Return the agent root working dir.

        Honours ``QWENPAW_WORKING_DIR`` (set by the e2e isolation
        scripts) and falls back to ``~/.qwenpaw``.
        """
        working = os.getenv("QWENPAW_WORKING_DIR")
        return Path(working) if working else Path.home() / ".qwenpaw"

    @classmethod
    def workspace_dir(cls, agent_id: str) -> Path:
        return cls.working_dir() / "workspaces" / agent_id

    # ========== Helpers ==========

    @staticmethod
    def unique_agent_id(label: str) -> str:
        return f"e2e-ma-{label}-{int(time.time() * 1000)}"

    def _agent_headers(self, agent_id: str = "") -> dict:
        return {"X-Agent-Id": agent_id or self.AGENT_ID_DEFAULT}

    # ========== /api/agents (setup helpers) ==========

    def api_create_agent(
        self,
        api_context,
        agent_id: str,
        name: Optional[str] = None,
        description: str = "e2e seed agent",
        language: str = "en",
    ) -> dict:
        resp = api_context.post(
            "/api/agents",
            data={
                "id": agent_id,
                "name": name or agent_id,
                "description": description,
                "language": language,
            },
        )
        assert resp.ok, (
            f"Create agent {agent_id} failed [{resp.status}]: {resp.text()}"
        )
        return resp.json()

    def api_delete_agent(self, api_context, agent_id: str):
        return api_context.delete(f"/api/agents/{agent_id}")

    def api_safe_delete_agent(self, api_context, agent_id: str) -> None:
        """Best-effort delete; never raises. Removes the workspace dir too
        because the backend intentionally leaves it on disk after
        DELETE (see app/routers/agents.py)."""
        try:
            resp = self.api_delete_agent(api_context, agent_id)
            if not resp.ok:
                logger.warning(
                    "Cleanup DELETE for %s returned %s: %s",
                    agent_id, resp.status, resp.text(),
                )
        except Exception as exc:
            logger.warning("Cleanup DELETE for %s failed: %s", agent_id, exc)
        # Backend keeps the on-disk workspace; remove it so test runs
        # don't pile up directories under /tmp.
        wsdir = self.workspace_dir(agent_id)
        try:
            if wsdir.exists():
                shutil.rmtree(wsdir, ignore_errors=True)
        except Exception as exc:
            logger.warning(
                "Cleanup rmtree %s failed: %s", wsdir, exc,
            )

    def api_list_agents(self, api_context) -> List[dict]:
        resp = api_context.get("/api/agents")
        assert resp.ok, f"List agents failed [{resp.status}]: {resp.text()}"
        body = resp.json()
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and isinstance(body.get("agents"), list):
            return body["agents"]
        return []

    def api_toggle_agent(
        self, api_context, agent_id: str, enabled: bool,
    ):
        return api_context.patch(
            f"/api/agents/{agent_id}/toggle",
            data={"enabled": enabled},
        )

    # ========== /api/agents/{id}/agent-status ==========

    def api_agent_status(
        self, api_context, agent_id: str,
    ) -> dict:
        resp = api_context.get(
            f"/api/agents/{agent_id}/agent-status",
        )
        assert resp.ok, (
            f"Read agent-status for {agent_id} failed [{resp.status}]: "
            f"{resp.text()}"
        )
        return resp.json()

    # ========== /api/agent/process/task ==========

    def api_submit_task(
        self,
        api_context,
        agent_id: str,
        text: str,
        session_id: str,
    ) -> dict:
        resp = api_context.post(
            "/api/agent/process/task",
            data={
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": text}],
                    }
                ],
                "session_id": session_id,
            },
            headers=self._agent_headers(agent_id),
        )
        assert resp.ok, (
            f"Submit task for {agent_id} failed [{resp.status}]: "
            f"{resp.text()}"
        )
        return resp.json()

    def api_get_task(self, api_context, task_id: str) -> dict:
        resp = api_context.get(f"/api/agent/process/task/{task_id}")
        assert resp.ok, (
            f"Get task {task_id} failed [{resp.status}]: {resp.text()}"
        )
        return resp.json()

    def poll_task_until(
        self,
        api_context,
        task_id: str,
        target_statuses: tuple,
        timeout_s: float = 30.0,
        interval_s: float = 0.5,
    ) -> dict:
        """Poll task status until it reaches one of ``target_statuses``."""
        deadline = time.time() + timeout_s
        last = {}
        while time.time() < deadline:
            last = self.api_get_task(api_context, task_id)
            if last.get("status") in target_statuses:
                return last
            time.sleep(interval_s)
        raise AssertionError(
            f"Task {task_id} never reached {target_statuses} within "
            f"{timeout_s}s; last status: {last.get('status')}",
        )

    # ========== /api/fork/agent ==========

    def api_fork_agent(
        self,
        api_context,
        agent_id: str,
        parent_session_id: str,
    ) -> dict:
        resp = api_context.post(
            "/api/fork/agent",
            data={
                "agent_id": agent_id,
                "parent_session_id": parent_session_id,
            },
            headers=self._agent_headers(agent_id),
        )
        assert resp.ok, (
            f"Fork agent failed [{resp.status}]: {resp.text()}"
        )
        return resp.json()

    @staticmethod
    def cleanup_worktree(
        agent_workspace_dir: Path,
        worktree_path: str,
    ) -> None:
        """Best-effort ``git worktree remove --force`` cleanup."""
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", worktree_path],
                cwd=str(agent_workspace_dir),
                check=False,
                capture_output=True,
                timeout=15,
            )
        except Exception as exc:
            logger.warning(
                "Worktree cleanup failed for %s: %s",
                worktree_path, exc,
            )

    @staticmethod
    def list_worktrees(agent_workspace_dir: Path) -> List[str]:
        """Return absolute paths of all git worktrees rooted at the agent."""
        try:
            out = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=str(agent_workspace_dir),
                capture_output=True,
                check=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            logger.warning(
                "git worktree list failed for %s: %s",
                agent_workspace_dir, exc,
            )
            return []
        paths = []
        for line in out.stdout.splitlines():
            if line.startswith("worktree "):
                paths.append(line[len("worktree "):].strip())
        return paths

    # ========== /api/console/chat (SSE smoke) ==========

    @classmethod
    def post_console_chat_sse_first_event(
        cls,
        agent_id: str,
        text: str,
        session_id: str,
        timeout: float = 30.0,
    ) -> str:
        """Open an SSE stream and return the first event line (or '').

        Used by MA-005 to confirm the request reached the target
        agent's runner without spending the LLM budget on a full reply.
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
                "meta": {
                    "sender_id": "e2e-ma",
                    "session_id": session_id,
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Agent-Id": agent_id,
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if line.startswith("data: "):
                    return line[len("data: "):]
        return ""
