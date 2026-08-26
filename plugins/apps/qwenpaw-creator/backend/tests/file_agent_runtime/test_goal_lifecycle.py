# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Goal lifecycle recovery: terminal goals never wedge the Session.

Production incident: resuming after the mainline Goal reached COMPLETED
bound a fresh QUEUED run to the dead Goal. The dispatcher refuses to
start runs on terminal Goals and admission rejects every later message
with "Active Goal is terminal", deadlocking the Session until the
runtime records were repaired by hand.
"""
from __future__ import annotations

import asyncio

import pytest

from services.file_agent_runtime import (
    AgentModelTurn,
    CallbackAgentChatClient,
    FileCreatorAgentRuntime,
)
from services.file_agent_runtime.models import CreatorAgentRunRecord
from services.file_agent_runtime.run_store import CreatorAgentRunStore
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.models import ChangeOrigin, ReviewPolicy

pytestmark = pytest.mark.unit

PROJECT_ID = "project-1"
SESSION_ID = "session-1"
CONVERSATION_ID = "conversation-1"
GOAL_ID = "goal-1"


def _create_project(tmp_path, *, initial_goal: str | None):
    services = CreatorFileServices.create(tmp_path.resolve())

    def initialize(staged_root) -> None:
        services.sessions.initialize_staged_project(
            staged_root,
            PROJECT_ID,
            session_id=SESSION_ID,
            conversation_id=CONVERSATION_ID,
            initial_goal=initial_goal,
            goal_id=GOAL_ID if initial_goal is not None else None,
            initial_message_id=(
                "message-initial" if initial_goal is not None else None
            ),
            initial_client_message_id=(
                "client-initial" if initial_goal is not None else None
            ),
        )

    snapshot = services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Initial"),
        initialize_staged_project=initialize,
    )
    services.poller.note_commit(snapshot)
    return services


async def _wait_for(predicate, *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise TimeoutError("condition was not reached")
        await asyncio.sleep(0.01)


def test_message_after_completed_goal_admits_a_fresh_goal(tmp_path) -> None:
    """A resume request never reuses a terminal Goal for its run."""

    async def callback(_messages, _tools) -> AgentModelTurn:
        return AgentModelTurn(content="完成")

    async def scenario():
        services = _create_project(tmp_path, initial_goal="第一个任务")
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        runs = CreatorAgentRunStore(services.root)
        await _wait_for(
            lambda: any(
                run.status.value == "SUCCEEDED"
                for run in runs.list(PROJECT_ID)
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        first_goal = services.sessions.get_goal(PROJECT_ID, GOAL_ID)
        if first_goal.status.value != "COMPLETED":
            # Force the terminal state deterministically; the incident's
            # goal reached COMPLETED through the review-resolution path.
            services.sessions.set_goal_status(
                PROJECT_ID,
                GOAL_ID,
                "COMPLETED",
            )

        services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "请继续第二个任务"}],
        )
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: sum(
                1
                for run in runs.list(PROJECT_ID)
                if run.status.value == "SUCCEEDED"
            )
            == 2,
        )
        await driver.wait_until_idle(PROJECT_ID)
        records = runs.list(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        await driver.stop()
        return records, session

    records, session = asyncio.run(scenario())

    goal_ids = {record.goal_id for record in records}
    assert len(records) == 2
    assert all(record.status.value == "SUCCEEDED" for record in records)
    # The second run owns a brand-new Goal instead of the COMPLETED one.
    assert len(goal_ids) == 2
    assert GOAL_ID in goal_ids
    assert session.error is None


def test_reconcile_reclaims_a_queued_run_bound_to_a_terminal_goal(
    tmp_path,
) -> None:
    """The exact production deadlock heals without manual record surgery."""

    async def callback(_messages, _tools) -> AgentModelTurn:
        return AgentModelTurn(content="恢复后的运行完成")

    async def scenario():
        services = _create_project(tmp_path, initial_goal=None)
        appended = services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "旧的主线请求"}],
        ).message
        goal = services.sessions.create_goal(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            root_message_seq=appended.message_seq,
            intent="旧的主线请求",
            goal_id="goal-terminal",
        )
        services.sessions.set_goal_status(
            PROJECT_ID,
            goal.goal_id,
            "COMPLETED",
        )
        snapshot = services.projects.read(PROJECT_ID)
        runs = CreatorAgentRunStore(services.root)
        runs.create(
            CreatorAgentRunRecord(
                run_id="agent-run-orphan",
                project_id=PROJECT_ID,
                session_id=SESSION_ID,
                goal_id=goal.goal_id,
                conversation_id=CONVERSATION_ID,
                round_id="round-orphan",
                caused_by_message_id=appended.message_id,
                caused_by_message_seq=appended.message_seq,
                origin=ChangeOrigin.AGENTDOCK_IDLE_GOAL,
                review_policy=ReviewPolicy.AUTO_FIX,
                input_generation=snapshot.generation,
                input_etag=snapshot.etag,
            ),
        )
        services.sessions.activate_run(
            PROJECT_ID,
            SESSION_ID,
            goal_id=goal.goal_id,
            run_id="agent-run-orphan",
        )
        services.sessions.mark_messages_consumed(
            PROJECT_ID,
            SESSION_ID,
            through_seq=appended.message_seq,
            goal_id=goal.goal_id,
        )
        # The pending resume request that hit the deadlock in production.
        services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "let's go"}],
        )

        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        driver._ORPHAN_RUN_GRACE_SECONDS = 0.0
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: runs.get(PROJECT_ID, "agent-run-orphan").status.value
            == "CANCELLED",
        )
        await _wait_for(
            lambda: any(
                run.status.value == "SUCCEEDED"
                for run in runs.list(PROJECT_ID)
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        orphan = runs.get(PROJECT_ID, "agent-run-orphan")
        records = runs.list(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        await driver.stop()
        return orphan, records, session

    orphan, records, session = asyncio.run(scenario())

    assert orphan.status.value == "CANCELLED"
    assert (orphan.error or {}).get("code") == "ORPHANED_ON_TERMINAL_GOAL"
    succeeded = [
        record for record in records if record.status.value == "SUCCEEDED"
    ]
    assert len(succeeded) == 1
    # The healed resume run owns a fresh Goal, not the terminal one.
    assert succeeded[0].goal_id != "goal-terminal"
    assert session.active_run_id is None
    assert session.error is None


def test_stalled_interrupt_reclaims_a_running_run_with_no_live_owner(
    tmp_path,
) -> None:
    """A dead worker's RUNNING run must not park the stop forever.

    Production wedge: the mainline failed on stream persistence and the
    FAILED transition itself lost the Runtime lock race, leaving the run
    durably RUNNING with no owner. Every reconcile pass treated it as a
    foreign live lease, so the Session stayed INTERRUPT_REQUESTED and the
    dock showed 「正在停止所有 Agent」 indefinitely while user messages
    piled up unconsumed. After the stall window the stop must be served.
    """

    async def callback(_messages, _tools) -> AgentModelTurn:
        return AgentModelTurn(content="不应被调用")

    async def scenario():
        services = _create_project(tmp_path, initial_goal=None)
        appended = services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "生成镜头视频"}],
        ).message
        goal = services.sessions.create_goal(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            root_message_seq=appended.message_seq,
            intent="生成镜头视频",
            goal_id="goal-dead-owner",
        )
        snapshot = services.projects.read(PROJECT_ID)
        runs = CreatorAgentRunStore(services.root)
        runs.create(
            CreatorAgentRunRecord(
                run_id="agent-run-dead-owner",
                project_id=PROJECT_ID,
                session_id=SESSION_ID,
                goal_id=goal.goal_id,
                conversation_id=CONVERSATION_ID,
                round_id="round-dead-owner",
                caused_by_message_id=appended.message_id,
                caused_by_message_seq=appended.message_seq,
                origin=ChangeOrigin.AGENTDOCK_IDLE_GOAL,
                review_policy=ReviewPolicy.AUTO_FIX,
                input_generation=snapshot.generation,
                input_etag=snapshot.etag,
            ),
        )
        services.sessions.activate_run(
            PROJECT_ID,
            SESSION_ID,
            goal_id=goal.goal_id,
            run_id="agent-run-dead-owner",
        )
        runs.transition(
            PROJECT_ID,
            "agent-run-dead-owner",
            expected_status="QUEUED",
            status="RUNNING",
        )
        # The worker dies here without persisting a terminal status; the
        # user presses stop and keeps typing into the unresponsive dock.
        services.sessions.set_session_status(
            PROJECT_ID,
            SESSION_ID,
            "INTERRUPT_REQUESTED",
        )
        services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "还在吗？"}],
        )

        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        driver._INTERRUPT_STALL_RECLAIM_SECONDS = 0.0
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: services.sessions.get_project_session(
                PROJECT_ID,
            ).status.value
            == "CANCELLED",
        )
        reclaimed = runs.get(PROJECT_ID, "agent-run-dead-owner")
        session = services.sessions.get_project_session(PROJECT_ID)
        await driver.stop()
        return reclaimed, session

    reclaimed, session = asyncio.run(scenario())

    assert reclaimed.status.value == "FAILED"
    assert (reclaimed.error or {}).get("code") == "INTERRUPTED"
    assert session.status.value == "CANCELLED"
    assert session.active_run_id is None
    assert session.last_consumed_message_seq == session.last_message_seq
