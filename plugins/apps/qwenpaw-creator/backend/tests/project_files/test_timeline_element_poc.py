# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from domain.errors import ValidationError as DomainValidationError

from services.media_files.image_execution import FileImageExecutionService
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    FileLocalMediaExecutionService,
    _validate_contiguous_edit_elements,
)
from services.media_files.r2v_execution import FileR2VExecutionService
from services.project_files.agent_tools import (
    AgentProjectToolContext,
    AgentProjectTools,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    EditCreation,
    ElementLocation,
    Project,
    TimelineElement,
    TimelineSpan,
    TransitionCreation,
)
from services.project_files.review import ReviewDecisionItem
from services.runtime_files.models import ChangeOrigin, ReviewPolicy

from .conftest import (
    FakeImageProvider,
    FakeR2VProvider,
    RecordingLocalRunner,
    install_edit_source,
    r2v_element,
)


pytestmark = pytest.mark.unit


def test_edit_execution_rejects_source_time_used_as_timeline_position() -> (
    None
):
    misplaced = SimpleNamespace(
        element_id="edit:source-9-13",
        span=TimelineSpan(start_tick=9_000, duration_tick=4_000),
    )

    with pytest.raises(
        DomainValidationError,
        match=r"span\.start_tick=9000，期望 0",
    ):
        _validate_contiguous_edit_elements([misplaced])


def test_ffmpeg_placement_uses_the_same_anchor_projection_as_the_ui() -> None:
    location = {
        "x": 0.5,
        "y": 0.88,
        "width": 0.8,
        "height": 0.1,
        "anchor_x": 0.5,
        "anchor_y": 0.5,
        "rotation_degrees": 0,
        "opacity": 1,
    }
    graph = FfmpegLocalMediaRunner._placement_filter(
        location,
        canvas_size=(1280, 720),
        duration_seconds=4,
    )
    assert "scale=1024:72" in graph
    assert "overlay=128:598" in graph


def test_elements_at_uses_half_open_intervals_and_returns_raw_elements(
    tmp_path,
):
    project = Project.new(project_id="timeline-project", name="Timeline")
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id = {
        "base": r2v_element("base", start=10, duration=10),
        "overlay": TimelineElement(
            element_id="overlay",
            span=TimelineSpan(start_tick=12, duration_tick=4),
            location=ElementLocation(),
            z_index=10,
            creation={"type": "overlay", "text": "抓到你了"},
        ),
        "disabled": TimelineElement(
            element_id="disabled",
            enabled=False,
            span=TimelineSpan(start_tick=10, duration_tick=10),
            location=ElementLocation(),
            creation={"type": "overlay", "text": "hidden"},
        ),
    }
    validated = Project.model_validate(project.model_dump(mode="json"))
    at_12 = [
        item.element_id for item in validated.elements_at("timeline:main", 12)
    ]
    assert at_12 == ["base", "overlay"]
    assert validated.elements_at("timeline:main", 20) == []

    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(validated)
    tools = AgentProjectTools(
        services.projects,
        context=AgentProjectToolContext(origin="runtime_task"),
    )
    result = tools.invoke(
        "elements_at",
        {
            "projectId": "timeline-project",
            "timelineId": "timeline:main",
            "tick": 12,
        },
    )
    assert [item["element_id"] for item in result["elements"]] == [
        "base",
        "overlay",
    ]


def test_transition_must_live_inside_both_endpoint_spans():
    project = Project.new(project_id="transition-project", name="Transition")
    timeline = project.timelines.items["timeline:main"]
    fade = TimelineElement(
        element_id="fade",
        span=TimelineSpan(start_tick=4_000, duration_tick=1_000),
        creation=TransitionCreation(
            from_element_id="a",
            to_element_id="b",
            transition_kind="crossfade",
        ),
    )
    timeline.elements_by_id = {
        "a": r2v_element("a", start=0, duration=5_000),
        "b": r2v_element("b", start=4_000, duration=5_000),
        "fade": fade,
    }
    Project.model_validate(project.model_dump(mode="json"))
    raw = project.model_dump(mode="json")
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"]["fade"][
        "span"
    ]["start_tick"] = 3_999
    with pytest.raises(ValidationError, match="endpoint intersection"):
        Project.model_validate(raw)


def test_named_element_output_requires_its_owned_artifact_slot():
    project = Project.new(project_id="output-project", name="Output")
    element = r2v_element("r2v-output", start=0)
    element.outputs = {"main": {"slot_id": "element:r2v-output:main"}}
    project.timelines.items["timeline:main"].elements_by_id[
        element.element_id
    ] = element
    with pytest.raises(
        ValidationError,
        match="ArtifactSlot references missing",
    ):
        Project.model_validate(project.model_dump(mode="json"))


def test_storyboard_and_r2v_publish_named_element_outputs(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id="r2v-project", name="R2V")
    elements = project.timelines.items["timeline:main"].elements_by_id
    elements["r2v-1"] = r2v_element("r2v-1", start=0)
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )

    image = asyncio.run(
        FileImageExecutionService(
            services,
            provider=FakeImageProvider(),
        ).execute(
            project_id="r2v-project",
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref="element:r2v-1",
            arguments={},
            idempotency_key="storyboard-1",
        ),
    )
    after_image = services.projects.read("r2v-project").project
    element = after_image.timelines.items["timeline:main"].elements_by_id[
        "r2v-1"
    ]
    assert element.outputs["storyboard"].slot_id == "element:r2v-1:storyboard"
    slot = after_image.assets.artifact_slots_by_id[
        element.outputs["storyboard"].slot_id
    ]
    assert slot.selected_version_id == image.artifact_version_id
    for review in services.reviews.all_pending("r2v-project"):
        services.reviews.decide(
            project_id="r2v-project",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[
                ReviewDecisionItem(
                    operation_id=o.operation_id,
                    decision="ACCEPT",
                )
                for o in review.operations
            ],
        )

    async def generate():
        worker = FileR2VExecutionService(
            services,
            provider=FakeR2VProvider(),
            poll_interval_seconds=0.01,
            poll_lease_seconds=0.1,
        )
        dispatched = await worker.dispatch(
            project_id="r2v-project",
            target_ref="element:r2v-1",
            arguments={},
            idempotency_key="video-1",
        )
        task = await worker.wait_for_task(
            "r2v-project",
            dispatched.task_id,
            timeout_seconds=3,
        )
        await worker.shutdown()
        return task

    task = asyncio.run(generate())
    assert task.status.value == "SUCCEEDED"
    finished = services.projects.read("r2v-project").project
    element = finished.timelines.items["timeline:main"].elements_by_id["r2v-1"]
    assert element.outputs["main"].slot_id == "element:r2v-1:main"
    assert element.render_source is not None
    assert element.render_source.type == "element_output"


def test_each_edit_selection_is_an_element_and_timeline_executes_them(
    tmp_path,
):
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(
        project_id="edit-project",
        name="Edit",
        scenario="video_edit",
    )
    services.projects.create(project)
    install_edit_source(services)
    base = services.projects.read("edit-project")
    candidate = base.project.model_dump(mode="json")
    elements = candidate["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]
    for index in range(7):
        element_id = f"edit-{index + 1}"
        start_tick = index * 1_000
        elements[element_id] = {
            "element_id": element_id,
            "label": f"猫咪高光 {element_id}",
            "span": {"start_tick": start_tick, "duration_tick": 1_000},
            "location": {},
            "creation": {
                "type": "edit",
                "intent": "选择有明确动作的素材范围",
                "reason": "素材理解确认该时段有关键动作",
                "original_sound": "preserve",
            },
            "render_source": {
                "type": "source_asset_version",
                "version_id": "source-version",
                "source_in_tick": start_tick,
                "source_out_tick": start_tick + 1_000,
            },
        }
        elements[f"overlay-{index + 1}"] = {
            "element_id": f"overlay-{index + 1}",
            "label": "宠物内心独白",
            "span": {"start_tick": start_tick + 200, "duration_tick": 500},
            "location": {},
            "z_index": 10,
            "creation": {
                "type": "overlay",
                "text": f"第 {index + 1} 段内心独白",
                "vibe": "action",
            },
        }
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )
    edit_runner = RecordingLocalRunner()
    edit = asyncio.run(
        FileLocalMediaExecutionService(services, runner=edit_runner).execute(
            project_id="edit-project",
            command="EXECUTE_EDIT",
            target_ref="timeline:timeline:main",
            arguments={},
            idempotency_key="edit-1",
        ),
    )
    snapshot = services.projects.read("edit-project").project
    timeline = snapshot.timelines.items["timeline:main"]
    creations = [
        element.creation for element in timeline.elements_by_id.values()
    ]
    assert (
        sum(isinstance(creation, EditCreation) for creation in creations) == 7
    )
    assert sum(creation.type == "overlay" for creation in creations) == 7
    render_slot = snapshot.assets.artifact_slots_by_id[
        "timeline:timeline:main:render"
    ]
    assert render_slot.selected_version_id == edit.artifact_version_id
    first = edit_runner.calls[0].inputs[0]
    assert len(edit_runner.calls[0].inputs) == 7
    assert (first.start_seconds, first.end_seconds) == (0, 1)
    assert edit_runner.calls[0].canvas_size == (1280, 720)
    assert first.location["x"] == 0.5
    assert first.overlays[0]["element_id"] == "overlay-1"
    assert first.overlays[0]["location"]["x"] == 0.5
    assert all(item.overlays for item in edit_runner.calls[0].inputs)
