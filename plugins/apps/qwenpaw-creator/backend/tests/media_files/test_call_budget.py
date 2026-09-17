# -*- coding: utf-8 -*-
"""The media call budget: an honest call-count fuse, never estimated money."""
from __future__ import annotations

import asyncio

import pytest

from domain.enums import TaskKind, TaskStatus
from services.media_files.call_budget import (
    MediaCallBudgetExhausted,
    ensure_media_call_budget,
    media_call_count,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.execution_models import TaskRecord
from services.runtime_files.execution_store import ProjectExecutionStore


pytestmark = pytest.mark.unit

PROJECT_ID = "budget-project"


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(Project.new(project_id=PROJECT_ID, name="B"))
    return services


def _seed_task(services, index: int, kind: TaskKind, status: TaskStatus):
    store = ProjectExecutionStore(services.root)
    task = store.create_task(
        TaskRecord(
            task_id=f"task-{index}",
            project_id=PROJECT_ID,
            kind=kind,
            status=TaskStatus.QUEUED,
            request_fingerprint=f"sha256:{index:064d}",
        ),
    )
    if status is TaskStatus.QUEUED:
        return
    if status in (TaskStatus.RUNNING, TaskStatus.SUCCEEDED, TaskStatus.FAILED):
        store.transition_task(
            PROJECT_ID,
            task.task_id,
            expected_status={TaskStatus.QUEUED},
            status=TaskStatus.RUNNING,
        )
    if status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED):
        store.transition_task(
            PROJECT_ID,
            task.task_id,
            expected_status={TaskStatus.RUNNING},
            status=status,
        )


def test_count_covers_billable_kinds_and_all_statuses(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)
    _seed_task(services, 1, TaskKind.IMAGE_GENERATION, TaskStatus.QUEUED)
    _seed_task(services, 2, TaskKind.R2V_GENERATION, TaskStatus.RUNNING)
    # Failed calls count: safety rejections happen after the billable
    # request was sent.
    _seed_task(services, 3, TaskKind.IMAGE_GENERATION, TaskStatus.FAILED)
    # Non-billable work does not.
    _seed_task(services, 4, TaskKind.COMPOSE, TaskStatus.RUNNING)

    assert media_call_count(services, PROJECT_ID) == 3


def test_fuse_trips_at_budget_with_an_actionable_message(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch)
    _seed_task(services, 1, TaskKind.IMAGE_GENERATION, TaskStatus.RUNNING)
    monkeypatch.setattr(
        "services.media_files.call_budget.get_media_call_budget",
        lambda: 1,
    )

    with pytest.raises(MediaCallBudgetExhausted) as caught:
        ensure_media_call_budget(services, PROJECT_ID)
    assert "media_call_budget" in str(caught.value)

    # Raising the budget clears the fuse.
    monkeypatch.setattr(
        "services.media_files.call_budget.get_media_call_budget",
        lambda: 2,
    )
    ensure_media_call_budget(services, PROJECT_ID)


def test_image_entry_point_enforces_the_fuse(tmp_path, monkeypatch):
    from services.media_files.image_execution import (
        execute_file_image_command,
    )

    services = _services(tmp_path, monkeypatch)
    _seed_task(services, 1, TaskKind.IMAGE_GENERATION, TaskStatus.SUCCEEDED)
    monkeypatch.setattr(
        "services.media_files.call_budget.get_media_call_budget",
        lambda: 1,
    )

    with pytest.raises(MediaCallBudgetExhausted):
        asyncio.run(
            execute_file_image_command(
                services,
                project_id=PROJECT_ID,
                command="GENERATE_ASSET",
                target_ref="asset:char:a",
                arguments={},
                idempotency_key="fused",
            ),
        )


def test_scheduler_pauses_dispatch_when_the_fuse_is_spent(
    tmp_path,
    monkeypatch,
):
    from services.file_agent_runtime.work_scheduler import WorkGraphScheduler
    from services.project_files.models import VisualEntity, VisualVariant

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="B")
    project.visual.entities.items["char:a"] = VisualEntity(
        entity_id="char:a",
        kind="character",
        name="a",
        required_variant_ids=["var:x"],
        variants={
            "items": {"var:x": VisualVariant(variant_id="var:x")},
            "order": ["var:x"],
        },
    )
    project.visual.entities.order.append("char:a")
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )
    monkeypatch.setattr(
        "services.file_agent_runtime.work_scheduler."
        "get_execution_authorization_mode",
        lambda: "allow_all",
    )
    monkeypatch.setattr(
        "services.media_files.call_budget.get_media_call_budget",
        lambda: 1,
    )
    _seed_task(services, 1, TaskKind.IMAGE_GENERATION, TaskStatus.SUCCEEDED)

    calls: list[dict] = []

    async def dispatch(_services, **kwargs):
        calls.append(kwargs)

    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        graph = await scheduler.tick(PROJECT_ID)
        for _ in range(4):
            await asyncio.sleep(0)
        return graph

    graph = asyncio.run(scenario())

    assert graph is not None  # the view still derives for the UI
    assert not calls  # but nothing was dispatched
