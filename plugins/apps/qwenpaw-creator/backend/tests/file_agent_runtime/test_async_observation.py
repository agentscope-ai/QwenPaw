# -*- coding: utf-8 -*-
"""Host-style async observation tools: background submit + batch harvest."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid5, NAMESPACE_URL

import pytest

from domain.enums import SpecialistRole, TaskKind
from domain.errors import ValidationError
from services.file_agent_runtime.driver import FileCreatorAgentRuntime
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.execution_store import (
    ProjectExecutionStore,
    TaskRecord,
)
from services.specialist_tools import FileSpecialistToolRegistry

PROJECT_ID = "project-1"


def _observation_task(kind: TaskKind, suffix: str) -> TaskRecord:
    return TaskRecord(
        task_id=f"task-{suffix}",
        project_id=PROJECT_ID,
        kind=kind,
        request_fingerprint=uuid5(NAMESPACE_URL, f"obs:{suffix}").hex,
        idempotency_key=f"task-{suffix}",
        input_refs=["asset:source-1"],
        metadata={},
    )


def test_harvest_guards_ownership_and_returns_a_snapshot(tmp_path) -> None:
    """Only this project's observation tasks may be harvested."""

    services = CreatorFileServices.create(tmp_path.resolve())

    def initialize(staged_root) -> None:
        services.sessions.initialize_staged_project(
            staged_root,
            PROJECT_ID,
            session_id="session-1",
            conversation_id="conversation-1",
            initial_goal="观察素材",
            goal_id="goal-1",
            initial_message_id="message-initial",
            initial_client_message_id="client-initial",
        )

    services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Harvest"),
        initialize_staged_project=initialize,
    )
    registry = FileSpecialistToolRegistry(services)
    executions = ProjectExecutionStore(services.root)
    observe = executions.create_task(
        _observation_task(TaskKind.OBSERVE_SOURCE_CLIP, "observe"),
    )
    foreign = executions.create_task(
        _observation_task(TaskKind.COMPOSE, "compose"),
    )

    async def _invoke(task_ids: list[str]):
        return await registry.invoke(
            role=SpecialistRole.SOURCE_INTELLIGENCE,
            name="check_observation_tasks",
            arguments={
                "projectId": PROJECT_ID,
                "targetRef": "asset:source-1",
                "arguments": {"taskIds": task_ids, "wait": False},
            },
            project_id=PROJECT_ID,
            admitted_target_refs=["asset:source-1"],
            project_tools=None,
            idempotency_key="call-1",
        )

    result = asyncio.run(_invoke([observe.task_id]))
    assert result.task_ids == (observe.task_id,)
    assert result.payload["tasks"] == [
        {"taskId": observe.task_id, "status": observe.status.value},
    ]

    with pytest.raises(ValidationError, match="只接受"):
        asyncio.run(_invoke([foreign.task_id]))
    with pytest.raises(ValidationError, match="不存在"):
        asyncio.run(_invoke(["task-unknown"]))


def test_batch_await_tolerates_per_task_failure() -> None:
    """One failed observation must not mask its batch peers' results."""

    from services.file_agent_runtime.driver import FileAgentRuntimeError

    async def _await_one(  # pylint: disable=unused-argument
        *,
        project_id,
        parent_run_id,
        epoch,
        task_id,
    ):
        if task_id == "task-bad":
            raise FileAgentRuntimeError("Task task-bad ended as FAILED: boom")
        return SimpleNamespace(
            task_id=task_id,
            status=SimpleNamespace(value="SUCCEEDED"),
            output_refs=(f"ref-{task_id}",),
            result={"answer": task_id},
        )

    fake_driver = SimpleNamespace(_await_specialist_task=_await_one)
    batch_await = (
        # pylint: disable-next=protected-access
        FileCreatorAgentRuntime._await_specialist_tasks
    )
    entries = asyncio.run(
        batch_await(
            fake_driver,
            project_id=PROJECT_ID,
            parent_run_id="run-1",
            epoch=1,
            task_ids=("task-good", "task-bad"),
        ),
    )
    assert entries[0]["status"] == "SUCCEEDED"
    assert entries[0]["result"] == {"answer": "task-good"}
    assert entries[1]["status"] == "FAILED"
    assert "task-bad" in entries[1]["error"]


def test_background_flag_is_read_from_the_nested_payload() -> None:
    """Field run 2026-08-10: the flag lives in arguments.arguments; the
    driver briefly read the envelope and silently kept every submission
    synchronous."""

    from services.file_agent_runtime.driver import _nested_tool_payload

    envelope = {
        "projectId": "project-1",
        "targetRef": "asset:source-1",
        "arguments": {"background": True, "budget": "small"},
    }
    assert _nested_tool_payload(envelope).get("background") is True
    assert _nested_tool_payload({"arguments": None}) == {}
    assert _nested_tool_payload({}) == {}
