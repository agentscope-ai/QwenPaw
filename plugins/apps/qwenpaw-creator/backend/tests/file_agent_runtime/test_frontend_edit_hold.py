# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Frontend auto-save grace: edited elements are not auto-dispatched."""
from __future__ import annotations

import asyncio

import pytest

from services.file_agent_runtime import work_scheduler
from services.file_agent_runtime.work_graph import (
    WorkGraph,
    WorkNode,
    WorkNodeStatus,
)
from services.file_agent_runtime.work_scheduler import WorkGraphScheduler
from services.project_files import frontend_edit_hold

pytestmark = pytest.mark.unit

PROJECT_ID = "scheduler-project"


@pytest.fixture(autouse=True)
def _clean_holds():
    frontend_edit_hold.clear()
    yield
    frontend_edit_hold.clear()


def test_element_ids_from_pointers_extract_only_element_paths() -> None:
    ids = frontend_edit_hold.element_ids_from_pointers(
        [
            "/timelines/items/timeline:main/elements_by_id/elem:a/creation"
            "/storyboard_prompt",
            "/timelines/items/timeline:main/elements_by_id/elem:b/span"
            "/duration_tick",
            "/assets/artifact_slots_by_id/element:elem:a:video"
            "/selected_version_id",
            "/settings/aspect_ratio",
            "",
        ],
    )
    assert ids == {"elem:a", "elem:b"}


def test_hold_opens_and_expires() -> None:
    frontend_edit_hold.note_frontend_edit(PROJECT_ID, ["elem:a"], now=100.0)
    assert frontend_edit_hold.hold_remaining(
        PROJECT_ID,
        "elem:a",
        now=100.0,
    ) == pytest.approx(frontend_edit_hold.FRONTEND_EDIT_GRACE_SECONDS)
    assert (
        frontend_edit_hold.hold_remaining(PROJECT_ID, "elem:other", now=100.0)
        == 0.0
    )
    expired = 100.0 + frontend_edit_hold.FRONTEND_EDIT_GRACE_SECONDS + 1.0
    assert (
        frontend_edit_hold.hold_remaining(PROJECT_ID, "elem:a", now=expired)
        == 0.0
    )
    # An expired probe drops the entry entirely.
    assert (PROJECT_ID, "elem:a") not in frontend_edit_hold._holds


def test_clear_scopes_to_one_project() -> None:
    frontend_edit_hold.note_frontend_edit("p1", ["e1"])
    frontend_edit_hold.note_frontend_edit("p2", ["e1"])
    frontend_edit_hold.clear("p1")
    assert frontend_edit_hold.hold_remaining("p1", "e1") == 0.0
    assert frontend_edit_hold.hold_remaining("p2", "e1") > 0.0


def _element_graph() -> WorkGraph:
    return WorkGraph(
        nodes=(
            WorkNode(
                node_id="storyboard:elem:a",
                kind="storyboard",
                label="分镜",
                status=WorkNodeStatus.READY,
                target_ref="element:elem:a",
                command="GENERATE_STORYBOARD_IMAGE",
            ),
        ),
        generation=1,
    )


class _RecordingDispatch:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, services, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True}


def _scheduler_env(
    tmp_path,
    monkeypatch,
) -> tuple[WorkGraphScheduler, "_RecordingDispatch"]:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    # Reuse the established scheduler harness: real services + a fabricated
    # element graph (the visual fixtures cannot produce element nodes).
    from services.project_files.facade import CreatorFileServices
    from services.project_files.models import Project

    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Hold"),
    )
    monkeypatch.setattr(
        "services.file_agent_runtime.work_scheduler."
        "get_execution_authorization_mode",
        lambda: "allow_all",
    )
    monkeypatch.setattr(
        work_scheduler,
        "derive_work_graph",
        lambda project, tasks=(): _element_graph(),
    )
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)
    return scheduler, dispatch


async def _drain() -> None:
    for _ in range(4):
        await asyncio.sleep(0)


def test_tick_skips_frontend_held_elements_then_dispatches(
    tmp_path,
    monkeypatch,
):
    scheduler, dispatch = _scheduler_env(tmp_path, monkeypatch)

    async def scenario():
        frontend_edit_hold.note_frontend_edit(PROJECT_ID, ["elem:a"])
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert not dispatch.calls
        # The skip arms a one-shot recheck so the final state still runs.
        assert PROJECT_ID in scheduler._sync_gate_rechecks
        frontend_edit_hold.clear(PROJECT_ID)
        await scheduler.tick(PROJECT_ID)
        await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert len(dispatch.calls) == 1
    assert dispatch.calls[0]["target_ref"] == "element:elem:a"
