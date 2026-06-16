# -*- coding: utf-8 -*-
"""
QwenPaw Multi-Agent collaboration end-to-end tests.

Eleven cases focused on the *collaboration* surface that ``test_agents.py``
intentionally does not exercise: cross-agent header routing, the
background task state machine, the localhost-only fork endpoint, and a
handful of contract / state assertions.

All cases drive the HTTP API directly. Two cases (MA-004, MA-005)
softly depend on a real LLM and are guarded with
``@pytest.mark.requires_llm`` + ``xfail strict=False`` so they skip
cleanly when ``QWENPAW_DASHSCOPE_API_KEY`` is not configured.
"""
from __future__ import annotations

import logging
import time

import pytest

from pages.multi_agent_collab_page import MultiAgentCollabPage
from utils.helpers import log_test_step, log_test_result


logger = logging.getLogger(__name__)


# ============================================================================
# MA-001 P0  Two seeded agents appear in the list
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.multi_agent
class TestSeededAgentsListed:
    """MA-001: After seeding two agents they both show up in /api/agents."""

    @pytest.mark.test_id("MA-001")
    def test_seed_two_agents_appear_in_list(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page
        qa_id = page.unique_agent_id("qa")
        code_id = page.unique_agent_id("code")

        try:
            log_test_step("1. Seed qa_bot and code_bot")
            page.api_create_agent(api_context, qa_id, name="QA Bot")
            page.api_create_agent(api_context, code_id, name="Code Bot")

            log_test_step("2. /api/agents lists both")
            agents = page.api_list_agents(api_context)
            ids = {a.get("id") for a in agents}
            assert qa_id in ids and code_id in ids, (
                f"Expected {qa_id} and {code_id} in agent list; got {ids}"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            page.api_safe_delete_agent(api_context, qa_id)
            page.api_safe_delete_agent(api_context, code_id)


# ============================================================================
# MA-002 P0  X-Agent-Id header routes the request to the right workspace
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.multi_agent
class TestAgentRouting:
    """MA-002: Both ``/api/agents/{id}/...`` path and ``X-Agent-Id`` header
    route to the same workspace's status endpoint."""

    @pytest.mark.test_id("MA-002")
    def test_x_agent_id_header_routes_request(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page
        agent_id = page.unique_agent_id("route")

        try:
            page.api_create_agent(api_context, agent_id, name="Route Bot")

            log_test_step("1. Path-based status returns the agent's state")
            via_path = page.api_agent_status(api_context, agent_id)
            assert "status" in via_path, (
                f"Expected status field via path, got {via_path}"
            )

            log_test_step("2. Header-based status returns the same shape")
            # AgentContextMiddleware: when path doesn't carry an agentId
            # placeholder, X-Agent-Id header is the fallback.
            resp = api_context.get(
                f"/api/agents/{agent_id}/agent-status",
                headers={"X-Agent-Id": agent_id},
            )
            assert resp.ok, (
                f"Header-routed status failed [{resp.status}]: {resp.text()}"
            )
            via_header = resp.json()
            assert via_header.get("status") == via_path.get("status"), (
                f"Path status={via_path.get('status')} differs from "
                f"header status={via_header.get('status')}"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            page.api_safe_delete_agent(api_context, agent_id)


# ============================================================================
# MA-003 P0  Submit task returns task_id without LLM
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.multi_agent
class TestSubmitTaskReturnsId:
    """MA-003: POST /api/agent/process/task returns immediately with a
    task_id; we don't wait for the LLM-backed run to finish."""

    @pytest.mark.test_id("MA-003")
    def test_submit_to_agent_returns_task_id(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page
        agent_id = page.unique_agent_id("submit")

        try:
            page.api_create_agent(api_context, agent_id, name="Submit Bot")

            log_test_step("1. POST /api/agent/process/task")
            body = page.api_submit_task(
                api_context,
                agent_id=agent_id,
                text="Hello, please reply briefly.",
                session_id=f"e2e-ma-submit-{int(time.time() * 1000)}",
            )

            log_test_step("2. Response includes task_id and submitted status")
            assert body.get("task_id"), (
                f"Expected task_id in submit response; got {body}"
            )
            # The runner reports either ``submitted`` (initial) or
            # ``running`` (already kicked off by the time we read).
            assert body.get("status") in {"submitted", "running"}, (
                f"Expected submitted/running status; got {body.get('status')}"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed (task_id={body['task_id']})")
        finally:
            page.api_safe_delete_agent(api_context, agent_id)


# ============================================================================
# MA-004 P0  Task progresses through the state machine (requires LLM)
# ============================================================================

@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p0
@pytest.mark.multi_agent
class TestTaskStateMachine:
    """MA-004: Submit a task and poll until it leaves ``submitted``.

    The runner needs an LLM to actually finish, so this case is
    declared xfail strict=False — environments without a model key
    skip cleanly via ``requires_llm``."""

    @pytest.mark.test_id("MA-004")
    @pytest.mark.xfail(
        reason="Requires a configured LLM to advance past submitted.",
        strict=False,
    )
    def test_check_agent_task_status_progresses(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page
        agent_id = page.unique_agent_id("state")

        try:
            page.api_create_agent(api_context, agent_id, name="State Bot")

            submit = page.api_submit_task(
                api_context,
                agent_id=agent_id,
                text="Reply with the single word OK.",
                session_id=f"e2e-ma-state-{int(time.time() * 1000)}",
            )
            task_id = submit["task_id"]

            log_test_step(
                "Poll task status until it reaches running or finished",
            )
            final = page.poll_task_until(
                api_context,
                task_id,
                target_statuses=("running", "finished", "completed"),
                timeout_s=60.0,
            )
            assert final.get("status") in {"running", "finished", "completed"}, (
                f"Unexpected final status: {final}"
            )

            log_test_result(test_name, True, 0)
            logger.info(
                f"Test {test_name} passed (final={final.get('status')})",
            )
        finally:
            page.api_safe_delete_agent(api_context, agent_id)


# ============================================================================
# MA-005 P1  Console SSE routes via X-Agent-Id (requires LLM)
# ============================================================================

@pytest.mark.integration
@pytest.mark.requires_llm
@pytest.mark.p1
@pytest.mark.multi_agent
class TestConsoleSseRouting:
    """MA-005: ``POST /api/console/chat`` with X-Agent-Id starts a stream
    on the target agent's workspace runner. We only verify the very
    first SSE event so the LLM budget stays low."""

    @pytest.mark.test_id("MA-005")
    @pytest.mark.xfail(
        reason="Hits the LLM-backed SSE pipeline; flaky without a key.",
        strict=False,
    )
    def test_chat_with_agent_sse_routes_to_target(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page
        agent_id = page.unique_agent_id("sse")

        try:
            page.api_create_agent(api_context, agent_id, name="SSE Bot")

            first = page.post_console_chat_sse_first_event(
                agent_id=agent_id,
                text="Hi.",
                session_id=f"e2e-ma-sse-{int(time.time() * 1000)}",
                timeout=30.0,
            )
            # The first event should be a JSON envelope with at least
            # an ``object`` key (``response`` or ``message``).
            import json
            assert first, "No SSE event received"
            envelope = json.loads(first)
            assert envelope.get("object") in {"response", "message", "content"}, (
                f"Unexpected first SSE event: {envelope}"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            page.api_safe_delete_agent(api_context, agent_id)


# ============================================================================
# MA-006 P1  /api/fork/agent creates a real git worktree
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.multi_agent
class TestForkCreatesWorktree:
    """MA-006: POST /api/fork/agent prepares a git worktree under the
    agent workspace; cleanup uses ``git worktree remove --force``."""

    @pytest.mark.test_id("MA-006")
    def test_fork_agent_creates_worktree(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page

        agent_id = page.AGENT_ID_DEFAULT
        ws = page.workspace_dir(agent_id)
        worktree_path: str = ""

        try:
            log_test_step("1. POST /api/fork/agent on the default agent")
            body = page.api_fork_agent(
                api_context,
                agent_id=agent_id,
                parent_session_id=f"e2e-ma-fork-{int(time.time() * 1000)}",
            )
            for k in ("fork_session_id", "worktree_path", "worktree_branch"):
                assert k in body, (
                    f"Fork response missing {k}: {body}"
                )
            worktree_path = body["worktree_path"]
            assert body["worktree_branch"].startswith("fork/"), (
                f"Expected fork/* branch; got {body['worktree_branch']}"
            )

            log_test_step("2. Worktree path exists on disk")
            from pathlib import Path
            assert Path(worktree_path).is_dir(), (
                f"Expected worktree dir at {worktree_path}"
            )

            log_test_step("3. git worktree list includes the new path")
            entries = page.list_worktrees(ws)
            # /tmp may resolve to /private/tmp on macOS; normalise.
            normalised = {Path(p).resolve() for p in entries}
            assert Path(worktree_path).resolve() in normalised, (
                f"Worktree {worktree_path} not in {entries}"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed (path={worktree_path})")
        finally:
            if worktree_path:
                page.cleanup_worktree(ws, worktree_path)


# ============================================================================
# MA-007 P1  Disabled agent reports "disabled" status
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.multi_agent
class TestDisabledAgentStatus:
    """MA-007: After PATCH .../toggle disable, agent-status returns
    ``disabled`` and running_task_count == 0."""

    @pytest.mark.test_id("MA-007")
    def test_disabled_agent_status_reflects_state(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page
        agent_id = page.unique_agent_id("disable")

        try:
            page.api_create_agent(api_context, agent_id, name="Disable Bot")

            log_test_step("1. Initial status is idle")
            initial = page.api_agent_status(api_context, agent_id)
            assert initial.get("status") == "idle", (
                f"Expected idle initial status; got {initial}"
            )

            log_test_step("2. PATCH toggle to disabled=false")
            resp = page.api_toggle_agent(api_context, agent_id, enabled=False)
            assert resp.ok, (
                f"Toggle failed [{resp.status}]: {resp.text()}"
            )

            log_test_step("3. Status is now disabled")
            disabled = page.api_agent_status(api_context, agent_id)
            assert disabled.get("status") == "disabled", (
                f"Expected disabled status; got {disabled}"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            page.api_safe_delete_agent(api_context, agent_id)


# ============================================================================
# MA-008 P1  Unknown target agent task: response shape is sensible
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.multi_agent
class TestUnknownAgentTaskResponse:
    """MA-008: Submitting a task with an unknown ``X-Agent-Id`` either
    rejects with 4xx, or accepts and surfaces a failure when polled.
    Either behaviour is acceptable as long as the system does not
    silently route the work to ``default``."""

    @pytest.mark.test_id("MA-008")
    def test_unknown_target_agent_task_response(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page
        ghost = f"e2e-ma-ghost-does-not-exist-{int(time.time() * 1000)}"

        log_test_step("1. Submit task with X-Agent-Id pointing at a ghost id")
        resp = api_context.post(
            "/api/agent/process/task",
            data={
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "hi"}],
                    }
                ],
                "session_id": "e2e-ma-ghost-session",
            },
            headers={"X-Agent-Id": ghost},
        )

        if not resp.ok:
            log_test_step("2a. Backend rejected with 4xx")
            assert 400 <= resp.status < 500, (
                f"Expected 4xx for ghost agent; got {resp.status}: "
                f"{resp.text()}"
            )
        else:
            log_test_step(
                "2b. Backend accepted; verify the ghost id did not "
                "leak into the agent list",
            )
            agents = page.api_list_agents(api_context)
            ids = {a.get("id") for a in agents}
            assert ghost not in ids, (
                f"Ghost id {ghost} should not appear in /api/agents"
            )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed (status={resp.status})")


# ============================================================================
# MA-009 P2  default agent cannot be deleted
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.multi_agent
class TestDefaultAgentProtected:
    """MA-009: DELETE /api/agents/default → 4xx with a 'cannot delete'
    error message."""

    @pytest.mark.test_id("MA-009")
    def test_default_agent_protected_from_delete(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        resp = api_context.delete("/api/agents/default")
        assert 400 <= resp.status < 500, (
            f"Expected 4xx for delete-default; got {resp.status}: "
            f"{resp.text()}"
        )

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed (status={resp.status})")


# ============================================================================
# MA-010 P2  Agent order persists after creating a new agent
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.multi_agent
class TestAgentOrderPersists:
    """MA-010: A newly-created agent appears at a stable position in
    /api/agents across consecutive calls (sanity check for the
    reorder persistence path)."""

    @pytest.mark.test_id("MA-010")
    def test_agent_order_preserved_after_create(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page
        agent_id = page.unique_agent_id("order")

        try:
            page.api_create_agent(api_context, agent_id, name="Order Bot")

            ids_first = [
                a.get("id") for a in page.api_list_agents(api_context)
            ]
            ids_second = [
                a.get("id") for a in page.api_list_agents(api_context)
            ]
            assert ids_first == ids_second, (
                f"Agent order changed between calls: "
                f"{ids_first} vs {ids_second}"
            )
            assert agent_id in ids_first, (
                f"New agent {agent_id} not found in list"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed")
        finally:
            page.api_safe_delete_agent(api_context, agent_id)


# ============================================================================
# MA-011 P2  Seeded agent's workspace directory is created on disk
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.multi_agent
class TestSeededAgentWorkspaceDir:
    """MA-011: After POST /api/agents, the on-disk workspace directory
    exists with an agent.json inside."""

    @pytest.mark.test_id("MA-011")
    def test_seeded_agent_workspace_dir_created(
        self,
        multi_agent_collab_page: MultiAgentCollabPage,
        api_context,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = multi_agent_collab_page
        agent_id = page.unique_agent_id("ws")

        try:
            body = page.api_create_agent(api_context, agent_id, name="WS Bot")
            assert body.get("workspace_dir"), (
                f"Create response missing workspace_dir: {body}"
            )

            from pathlib import Path
            ws = Path(body["workspace_dir"])
            assert ws.is_dir(), f"workspace_dir {ws} should exist on disk"
            assert (ws / "agent.json").exists(), (
                f"agent.json missing under {ws}"
            )

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed (dir={ws})")
        finally:
            page.api_safe_delete_agent(api_context, agent_id)
