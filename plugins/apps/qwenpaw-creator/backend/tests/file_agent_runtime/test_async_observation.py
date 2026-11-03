# -*- coding: utf-8 -*-
"""Host-style async observation tools: background submit + batch harvest."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid5, NAMESPACE_URL

import pytest

from domain.enums import SpecialistRole, TaskKind, TaskStatus
from domain.errors import ValidationError
from services.file_agent_runtime.driver import FileCreatorAgentRuntime
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.execution_store import (
    ProjectExecutionStore,
    TaskRecord,
)
from services.source_analysis import SourceAgentToolContext
from services.specialist_tools import FileSpecialistToolRegistry

PROJECT_ID = "project-1"
TARGET_REF = "asset:source-1"


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
        fence,
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
            fence=SimpleNamespace(assert_alive=lambda: None),
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


def _prepare_project(tmp_path):
    """One real Project plus its durable Runtime store."""

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
    return services, ProjectExecutionStore(services.root)


def _run_task(kind: TaskKind, suffix: str, run_id: str) -> TaskRecord:
    return TaskRecord(
        task_id=f"task-{suffix}",
        project_id=PROJECT_ID,
        kind=kind,
        request_fingerprint=uuid5(NAMESPACE_URL, f"obs:{suffix}").hex,
        idempotency_key=f"task-{suffix}",
        input_refs=[TARGET_REF],
        caused_by_request_id=run_id,
        metadata={},
    )


def _context(run_id: str) -> SourceAgentToolContext:
    return SourceAgentToolContext(
        specialist_run_id=run_id,
        tool_call_id="call-1",
        assistant_message_id="message-1",
        provider_message_id=None,
        provider="configured_vlm",
        model="qwen-vl",
    )


def _harvest(registry, *, arguments, context=None):
    return registry.invoke(
        role=SpecialistRole.SOURCE_INTELLIGENCE,
        name="check_observation_tasks",
        arguments={
            "projectId": PROJECT_ID,
            "targetRef": TARGET_REF,
            **arguments,
        },
        project_id=PROJECT_ID,
        admitted_target_refs=[TARGET_REF],
        project_tools=None,
        idempotency_key="call-harvest",
        context=context,
    )


def test_harvest_without_task_ids_collects_this_runs_observations(
    tmp_path,
) -> None:
    """省略 taskIds 就收割本 Run 的全部观察任务，不碰别的 Run。

    批量并行提交是快路，而“记住每个 taskId”正是模型不肯批量的原因。
    """

    services, executions = _prepare_project(tmp_path)
    registry = FileSpecialistToolRegistry(services)
    mine = [
        executions.create_task(
            _run_task(
                TaskKind.OBSERVE_SOURCE_CLIP,
                "mine-observe",
                "specialist-run-1",
            ),
        ),
        executions.create_task(
            _run_task(
                TaskKind.READ_SOURCE_VIDEO,
                "mine-read",
                "specialist-run-1",
            ),
        ),
    ]
    foreign_run = executions.create_task(
        _run_task(
            TaskKind.OBSERVE_SOURCE_CLIP,
            "other-run",
            "specialist-run-2",
        ),
    )
    executions.create_task(
        _run_task(TaskKind.COMPOSE, "not-observation", "specialist-run-1"),
    )

    result = asyncio.run(
        _harvest(
            registry,
            arguments={"arguments": {"wait": False}},
            context=_context("specialist-run-1"),
        ),
    )

    assert set(result.task_ids) == {task.task_id for task in mine}
    assert foreign_run.task_id not in result.task_ids
    assert {entry["taskId"] for entry in result.payload["tasks"]} == set(
        result.task_ids,
    )
    # 没触发上限时不多塞一个 note，免得每回合都往上下文里加噪声。
    assert "note" not in result.payload


def test_harvest_all_without_arguments_object_reports_a_note(
    tmp_path,
) -> None:
    """没有可收割任务时给可读提示，而不是报“arguments 必须是 object”。"""

    services, _executions = _prepare_project(tmp_path)
    registry = FileSpecialistToolRegistry(services)

    result = asyncio.run(_harvest(registry, arguments={}))

    assert result.task_ids == ()
    assert result.payload["tasks"] == []
    assert "background=true" in result.payload["note"]


def test_harvest_all_bound_reports_the_tasks_it_left_out(tmp_path) -> None:
    """上限不能静默丢任务：那些观察已经付费了，必须告知怎么收割。

    重复调用 harvest-all 会拿到同一批（已终态的任务也算本 Run 的待收割
    结果），所以溢出部分只能靠显式 taskIds，提示里就得把 id 给出来。
    """

    from services.specialist_tools import _MAX_HARVEST_TASKS

    services, executions = _prepare_project(tmp_path)
    registry = FileSpecialistToolRegistry(services)
    total = _MAX_HARVEST_TASKS + 2
    created = [
        executions.create_task(
            _run_task(
                TaskKind.OBSERVE_SOURCE_CLIP,
                f"batch-{index:03d}",
                "specialist-run-1",
            ),
        ).task_id
        for index in range(total)
    ]

    result = asyncio.run(
        _harvest(
            registry,
            arguments={"arguments": {"wait": False}},
            context=_context("specialist-run-1"),
        ),
    )

    # 最早提交的一批被收割，溢出的是最后两个。
    assert list(result.task_ids) == created[:_MAX_HARVEST_TASKS]
    note = result.payload["note"]
    assert f"共 {total} 个观察任务" in note
    for task_id in created[_MAX_HARVEST_TASKS:]:
        assert task_id in note
    assert "taskIds" in note
    assert len(result.payload["tasks"]) == _MAX_HARVEST_TASKS


def test_harvest_all_pages_through_every_task_with_harvest_offset(
    tmp_path,
) -> None:
    """溢出批次靠 harvestOffset 翻页取全：49 个任务两次收割全覆盖。

    回合预算提高后，一个 Run 可能提交远超一次收割上限（32）的观察。
    默认调用只返回前 32 个，提示窗也只列得下 16 个 id，第 49 个既不在
    返回里、也不在提示里——若没有可推进的游标，模型只能回查原始提交响应
    才能找齐，与“省略 taskIds 收割本 Run 全部任务”的承诺相悖。
    """

    from services.specialist_tools import _MAX_HARVEST_TASKS

    services, executions = _prepare_project(tmp_path)
    registry = FileSpecialistToolRegistry(services)
    total = _MAX_HARVEST_TASKS + 17  # 49：一页收割 + 一页显式 id 都盖不住
    created = [
        executions.create_task(
            _run_task(
                TaskKind.OBSERVE_SOURCE_CLIP,
                f"batch-{index:03d}",
                "specialist-run-1",
            ),
        ).task_id
        for index in range(total)
    ]

    # 第一页：默认 offset=0 收割前 32 个，提示给出下一页游标。
    first = asyncio.run(
        _harvest(
            registry,
            arguments={"arguments": {"wait": False}},
            context=_context("specialist-run-1"),
        ),
    )
    assert list(first.task_ids) == created[:_MAX_HARVEST_TASKS]
    assert len(first.payload["tasks"]) == _MAX_HARVEST_TASKS
    note = first.payload["note"]
    assert f"共 {total} 个观察任务" in note
    assert f"harvestOffset={_MAX_HARVEST_TASKS}" in note
    # 第 49 个任务既不在返回里，也溢出了 16 个 id 的提示窗——正是旧实现
    # 永远够不到的那一个。
    assert created[-1] not in note
    assert created[-1] not in first.task_ids

    # 第二页：回填游标收割剩下的 17 个，含此前够不到的第 49 个。
    second = asyncio.run(
        _harvest(
            registry,
            arguments={
                "arguments": {
                    "wait": False,
                    "harvestOffset": _MAX_HARVEST_TASKS,
                },
            },
            context=_context("specialist-run-1"),
        ),
    )
    assert list(second.task_ids) == created[_MAX_HARVEST_TASKS:]
    assert len(second.payload["tasks"]) == total - _MAX_HARVEST_TASKS
    assert created[-1] in second.task_ids
    # 全部收割完，没有剩余，就不再塞溢出提示。
    assert "note" not in second.payload

    # 两页合起来正好覆盖全部 49 个，无重复无遗漏。
    paged = list(first.task_ids) + list(second.task_ids)
    assert paged == created
    assert len(set(paged)) == total

    # 游标越过末尾：幂等地返回空，并说明已收割完。
    exhausted = asyncio.run(
        _harvest(
            registry,
            arguments={"arguments": {"wait": False, "harvestOffset": total}},
            context=_context("specialist-run-1"),
        ),
    )
    assert exhausted.task_ids == ()
    assert exhausted.payload["tasks"] == []
    assert "已越过全部" in exhausted.payload["note"]


def _complete(executions, task_id: str) -> None:
    """Drive a QUEUED observation to SUCCEEDED (refreshes its updated_at)."""

    executions.transition_task(
        PROJECT_ID,
        task_id,
        expected_status=TaskStatus.QUEUED,
        status=TaskStatus.RUNNING,
    )
    executions.transition_task(
        PROJECT_ID,
        task_id,
        expected_status=TaskStatus.RUNNING,
        status=TaskStatus.SUCCEEDED,
    )


def test_harvest_offset_cursor_is_stable_when_page_one_completes(
    tmp_path,
) -> None:
    """翻页游标必须建在不可变顺序上：第一页收割后转终态，第二页仍要精确
    返回剩下的任务，而不是重复第一页、永久漏掉尾部。

    harvest-all 默认 wait=true 会把本页任务推进到终态，刷新它们的
    updated_at；若发现顺序依赖 updated_at，这批任务会移到列表另一端，
    令 offset 游标错位（重复已收割项、丢失未收割项且不再报溢出）。
    """

    from services.specialist_tools import _MAX_HARVEST_TASKS

    services, executions = _prepare_project(tmp_path)
    registry = FileSpecialistToolRegistry(services)
    total = _MAX_HARVEST_TASKS + 17
    created = [
        executions.create_task(
            _run_task(
                TaskKind.OBSERVE_SOURCE_CLIP,
                f"batch-{index:03d}",
                "specialist-run-1",
            ),
        ).task_id
        for index in range(total)
    ]

    first = asyncio.run(
        _harvest(
            registry,
            arguments={"arguments": {"wait": False}},
            context=_context("specialist-run-1"),
        ),
    )
    assert list(first.task_ids) == created[:_MAX_HARVEST_TASKS]

    # 第一页收割（wait=true）会把这些任务推进到终态，刷新 updated_at。
    for task_id in first.task_ids:
        _complete(executions, task_id)

    second = asyncio.run(
        _harvest(
            registry,
            arguments={
                "arguments": {
                    "wait": False,
                    "harvestOffset": _MAX_HARVEST_TASKS,
                },
            },
            context=_context("specialist-run-1"),
        ),
    )
    # 游标稳定：第二页正好是剩下的 17 个，与第一页无交集，合起来全覆盖。
    assert list(second.task_ids) == created[_MAX_HARVEST_TASKS:]
    assert set(second.task_ids).isdisjoint(first.task_ids)
    assert list(first.task_ids) + list(second.task_ids) == created
