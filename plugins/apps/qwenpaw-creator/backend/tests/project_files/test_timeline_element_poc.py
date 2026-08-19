# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from domain.enums import CreatorCommandType
from domain.errors import ValidationError as DomainValidationError

from services.media_files.image_execution import FileImageExecutionService
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    FileLocalMediaExecutionService,
    LocalMediaInput,
    LocalMediaExecutionSpec,
    _render_element_total,
    _validate_contiguous_edit_elements,
)
from services.media_files.r2v_execution import FileR2VExecutionService
from services.project_files.agent_tools import (
    AgentProjectToolContext,
    AgentProjectTools,
)
from services.project_files.assets import AssetFileStore
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    EditCreation,
    ElementLocation,
    EntityCollection,
    Project,
    R2VCreation,
    Shot,
    TimelineElement,
    TimelineSpan,
    TransitionCreation,
)
from services.project_files.review import ReviewDecisionItem
from services.runtime_files.models import ChangeOrigin, ReviewPolicy

# pylint: disable=no-name-in-module
from utils.paths import unique_task_work_path

# pylint: enable=no-name-in-module


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"timeline-storyboard" * 16
_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"timeline-video" * 64


class _ImageProvider:
    async def generate(self, **_kwargs):
        return {"content": _PNG, "media_type": "image/png"}


class _R2VProvider:
    async def submit(self, **_kwargs) -> str:
        return "provider-task-1"

    async def poll(self, provider_task_id: str):
        path = unique_task_work_path(
            "video",
            ".mp4",
            prefix="timeline-provider-",
        )
        path.write_bytes(_MP4)
        return {
            "task_id": provider_task_id,
            "status": "SUCCEEDED",
            "result_url": path.resolve().as_uri(),
            "media_type": "video/mp4",
            "durationSeconds": 4,
        }


class _LocalRunner:
    def __init__(self) -> None:
        self.calls: list[LocalMediaExecutionSpec] = []

    async def render(self, spec: LocalMediaExecutionSpec):
        self.calls.append(spec)
        if spec.on_element_done is not None:
            total_elements = _render_element_total(spec.inputs)
            spec.on_element_done(total_elements, total_elements)
        spec.output_path.write_bytes(_MP4 + spec.command.value.encode())
        return {
            "media_type": "video/mp4",
            "duration_seconds": spec.expected_duration_seconds,
        }


def _full_canvas() -> ElementLocation:
    return ElementLocation()


def test_default_visual_location_is_a_full_frame_with_center_transform_origin() -> (
    None
):
    location = ElementLocation()
    assert (location.x, location.y) == (0.5, 0.5)
    assert (location.width, location.height) == (1.0, 1.0)
    assert (location.anchor_x, location.anchor_y) == (0.5, 0.5)


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
    graph = FfmpegLocalMediaRunner._placement_filter(
        {
            "x": 0.5,
            "y": 0.88,
            "width": 0.8,
            "height": 0.1,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
            "rotation_degrees": 0,
            "opacity": 1,
        },
        canvas_size=(1280, 720),
        duration_seconds=4,
    )
    assert "scale=1024:72" in graph
    assert "overlay=128:598" in graph


def test_ffmpeg_progress_counts_unique_elements_across_segments(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(_MP4)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    progress: list[tuple[int, int]] = []
    runner = FfmpegLocalMediaRunner(executable="ffmpeg")

    def fake_run(args, *, cwd):
        del cwd
        segment = (
            work_dir / "segments" / str(args[-1]).rsplit("/", maxsplit=1)[-1]
        )
        segment.write_bytes(_MP4)

    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(runner, "_apply_overlay", lambda *_args: [])
    monkeypatch.setattr(runner, "_apply_motion_overlays", lambda *_args: [])
    monkeypatch.setattr(
        runner,
        "_concat",
        lambda _inputs, output_path, *, work_dir: output_path.write_bytes(
            _MP4,
        ),
    )
    shared_overlay = {
        "element_id": "overlay-shared",
        "kind": "pet_os",
        "text": "跨片段",
    }

    runner._render_sync(
        LocalMediaExecutionSpec(
            command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
            target_ref="timeline:timeline:main",
            task_id="task-element-progress",
            work_dir=work_dir,
            output_path=work_dir / "output.mp4",
            inputs=tuple(
                LocalMediaInput(
                    version_id=f"version-{index}",
                    file_id=f"file-{index}",
                    checksum=str(index) * 64,
                    media_type="video/mp4",
                    path=source,
                    source_ref=f"element:edit-{index}",
                    start_seconds=index - 1,
                    end_seconds=index,
                    overlays=(shared_overlay,),
                )
                for index in (1, 2)
            ),
            transitions=(),
            audio_plan={},
            expected_duration_seconds=2,
            canvas_size=(1280, 720),
            on_element_done=lambda done, total: progress.append(
                (done, total),
            ),
        ),
    )

    assert progress == [(1, 3), (3, 3)]


def _r2v_element(element_id: str, *, start: int, duration: int = 4_000):
    shot = Shot(
        shot_id=f"{element_id}-shot",
        description="猫追逐老鼠",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=duration / 1_000,
    )
    return TimelineElement(
        element_id=element_id,
        label="猫追老鼠",
        span=TimelineSpan(start_tick=start, duration_tick=duration),
        location=_full_canvas(),
        creation=R2VCreation(
            narrative="猫发现老鼠后追逐",
            storyboard_prompt="动画分镜：猫发现并追逐老鼠",
            video_prompt="动画，猫从左向右追逐老鼠，动作连续",
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
        ),
    )


def test_project_schema_has_only_timeline_element_content_domain():
    schema = json.dumps(Project.model_json_schema(), ensure_ascii=False)
    assert '"Timeline"' in schema
    assert '"TimelineElement"' in schema
    for retired_type in (
        "Unit",
        "Section",
        "AiEditPlan",
        "EditClip",
        "ProductionFlow",
    ):
        assert retired_type not in schema


def test_elements_at_uses_half_open_intervals_and_returns_raw_elements(
    tmp_path,
):
    project = Project.new(project_id="timeline-project", name="Timeline")
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id = {
        "base": _r2v_element("base", start=10, duration=10),
        "overlay": TimelineElement(
            element_id="overlay",
            span=TimelineSpan(start_tick=12, duration_tick=4),
            location=_full_canvas(),
            z_index=10,
            creation={
                "type": "overlay",
                "text": "抓到你了",
            },
        ),
        "disabled": TimelineElement(
            element_id="disabled",
            enabled=False,
            span=TimelineSpan(start_tick=10, duration_tick=10),
            location=_full_canvas(),
            creation={
                "type": "overlay",
                "text": "hidden",
            },
        ),
    }
    validated = Project.model_validate(project.model_dump(mode="json"))
    assert [
        item.element_id for item in validated.elements_at("timeline:main", 12)
    ] == [
        "base",
        "overlay",
    ]
    assert validated.elements_at("timeline:main", 20) == []
    assert [
        item.element_id
        for item in validated.elements_at(
            "timeline:main",
            12,
            include_disabled=True,
        )
    ] == ["base", "disabled", "overlay"]

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
    timeline.elements_by_id = {
        "a": _r2v_element("a", start=0, duration=5_000),
        "b": _r2v_element("b", start=4_000, duration=5_000),
        "fade": TimelineElement(
            element_id="fade",
            span=TimelineSpan(start_tick=4_000, duration_tick=1_000),
            creation=TransitionCreation(
                from_element_id="a",
                to_element_id="b",
                transition_kind="crossfade",
            ),
        ),
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
    element = _r2v_element("r2v-output", start=0)
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
    project.timelines.items["timeline:main"].elements_by_id[
        "r2v-1"
    ] = _r2v_element("r2v-1", start=0)
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )

    image = asyncio.run(
        FileImageExecutionService(services, provider=_ImageProvider()).execute(
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
    assert (
        after_image.assets.artifact_slots_by_id[
            element.outputs["storyboard"].slot_id
        ].selected_version_id
        == image.artifact_version_id
    )
    for review in services.reviews.all_pending("r2v-project"):
        services.reviews.decide(
            project_id="r2v-project",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[
                ReviewDecisionItem(
                    operation_id=operation.operation_id,
                    decision="ACCEPT",
                )
                for operation in review.operations
            ],
        )

    async def generate():
        worker = FileR2VExecutionService(
            services,
            provider=_R2VProvider(),
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


def _install_source(services: CreatorFileServices) -> None:
    root = services.projects.project_root("edit-project")
    content = b"source-video"
    checksum = hashlib.sha256(content).hexdigest()
    relative_uri = "assets/sources/cat/source.mp4"
    store = AssetFileStore(root)
    store.publish(
        store.stage_bytes(content, staging_id="source"),
        relative_uri,
        expected_sha256=checksum,
        expected_size_bytes=len(content),
    )
    base = services.projects.read("edit-project")
    candidate = base.project.model_dump(mode="json")
    candidate["assets"]["files_by_id"]["source-file"] = {
        "file_id": "source-file",
        "kind": "source_original",
        "relative_uri": relative_uri,
        "sha256": checksum,
        "size_bytes": len(content),
        "media_type": "video/mp4",
        "created_at": datetime.now(UTC).isoformat(),
    }
    candidate["assets"]["source_versions_by_id"]["source-version"] = {
        "version_id": "source-version",
        "logical_asset_id": "cat-source",
        "name": "cat.mp4",
        "file_id": "source-file",
        "checksum": checksum,
        "media_kind": "video",
        "media_type": "video/mp4",
        "duration_seconds": 10,
        "created_at": datetime.now(UTC).isoformat(),
    }
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )


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
    _install_source(services)
    base = services.projects.read("edit-project")
    candidate = base.project.model_dump(mode="json")
    elements = candidate["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]
    for index in range(7):
        element_id = f"edit-{index + 1}"
        start_tick = index * 1_000
        source_in_tick = index * 1_000
        source_out_tick = source_in_tick + 1_000
        elements[element_id] = {
            "element_id": element_id,
            "label": f"猫咪高光 {element_id}",
            "enabled": True,
            "span": {
                "start_tick": start_tick,
                "duration_tick": source_out_tick - source_in_tick,
            },
            "location": _full_canvas().model_dump(mode="json"),
            "z_index": 0,
            "creation": {
                "type": "edit",
                "intent": "选择有明确动作的素材范围",
                "reason": "素材理解确认该时段有关键动作",
                "original_sound": "preserve",
                "source_intelligence_version_id": None,
            },
            "outputs": {},
            "render_source": {
                "type": "source_asset_version",
                "version_id": "source-version",
                "source_in_tick": source_in_tick,
                "source_out_tick": source_out_tick,
                "playback_rate": 1,
                "loop": False,
            },
            "provenance_refs": [],
        }
        overlay_id = f"overlay-{index + 1}"
        elements[overlay_id] = {
            "element_id": overlay_id,
            "label": "宠物内心独白",
            "enabled": True,
            "span": {"start_tick": start_tick + 200, "duration_tick": 500},
            "location": _full_canvas().model_dump(mode="json"),
            "z_index": 10,
            "creation": {
                "type": "overlay",
                "text": f"第 {index + 1} 段内心独白",
                "vibe": "action",
                "prompt": "",
                "reference_version_ids": [],
            },
            "outputs": {},
            "render_source": None,
            "provenance_refs": [],
        }
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )
    edit_runner = _LocalRunner()
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
    assert (
        sum(
            isinstance(element.creation, EditCreation)
            for element in timeline.elements_by_id.values()
        )
        == 7
    )
    assert (
        sum(
            element.creation.type == "overlay"
            for element in timeline.elements_by_id.values()
        )
        == 7
    )
    assert (
        snapshot.assets.artifact_slots_by_id[
            "timeline:timeline:main:render"
        ].selected_version_id
        == edit.artifact_version_id
    )
    assert len(edit_runner.calls[0].inputs) == 7
    assert edit_runner.calls[0].inputs[0].start_seconds == 0
    assert edit_runner.calls[0].inputs[0].end_seconds == 1
    assert edit_runner.calls[0].canvas_size == (1280, 720)
    assert edit_runner.calls[0].inputs[0].location["x"] == 0.5
    assert (
        edit_runner.calls[0].inputs[0].overlays[0]["element_id"] == "overlay-1"
    )
    assert edit_runner.calls[0].inputs[0].overlays[0]["location"]["x"] == 0.5
    assert all(item.overlays for item in edit_runner.calls[0].inputs)
