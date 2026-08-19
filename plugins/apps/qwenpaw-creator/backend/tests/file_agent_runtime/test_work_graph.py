# -*- coding: utf-8 -*-
"""Work graph derivation: the production DAG projected from durable facts.

Every status is recomputed from project.json plus task records — the
graph is a view, never a second authority. These tests pin the node
identities, dependency edges and all seven states.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.enums import TaskStatus
from services.file_agent_runtime.work_graph import (
    WorkNodeStatus,
    derive_work_graph,
)
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    ElementLocation,
    IndexedFile,
    Project,
    R2VCreation,
    Shot,
    TimelineElement,
    TimelineSpan,
    VisualCastLineup,
    VisualEntity,
    VisualVariant,
)


pytestmark = pytest.mark.unit


def _entity(entity_id: str, variants: dict[str, str | None]) -> VisualEntity:
    return VisualEntity(
        entity_id=entity_id,
        kind="character",
        name=entity_id.removeprefix("char:"),
        required_variant_ids=list(variants),
        variants={
            "items": {
                variant_id: VisualVariant(
                    variant_id=variant_id,
                    selected_artifact_version_id=selected,
                )
                for variant_id, selected in variants.items()
            },
            "order": list(variants),
        },
    )


def _element(element_id: str, **creation_kwargs) -> TimelineElement:
    shot = Shot(
        shot_id=f"{element_id}-shot",
        description="镜头",
        camera="⊙ 静止",
        framing="全景",
        duration_seconds=4,
    )
    defaults = {
        "narrative": "叙事",
        "storyboard_prompt": "分镜 prompt",
        "shots": {"items": {shot.shot_id: shot}, "order": [shot.shot_id]},
    }
    defaults.update(creation_kwargs)
    return TimelineElement(
        element_id=element_id,
        label=element_id,
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(**defaults),
    )


def _project() -> Project:
    return Project.new(project_id="p-graph", name="Graph")


def _add_element(project: Project, element: TimelineElement) -> None:
    project.timelines.items["timeline:main"].elements_by_id[
        element.element_id
    ] = element


def _select_slot(
    project: Project,
    *,
    slot_id: str,
    kind: str,
    owner_ref: str,
    version_id: str,
    provenance: list[str] | None = None,
) -> None:
    project.assets.artifact_slots_by_id[slot_id] = ArtifactSlot(
        slot_id=slot_id,
        kind=kind,
        owner_ref=owner_ref,
        version_ids=[version_id],
        selected_version_id=version_id,
    )
    project.assets.files_by_id[f"file-{version_id}"] = IndexedFile(
        file_id=f"file-{version_id}",
        kind="artifact_payload",
        media_type="image/png",
        relative_uri=f"assets/artifacts/file-{version_id}.png",
        sha256="0" * 64,
        size_bytes=1,
        created_at="2026-08-05T00:00:00Z",
    )
    project.assets.artifact_versions_by_id[version_id] = ArtifactVersion(
        version_id=version_id,
        name=version_id,
        slot_id=slot_id,
        kind=kind,
        owner_ref=owner_ref,
        file_id=f"file-{version_id}",
        checksum="0" * 64,
        input_fingerprint="sha256:" + "1" * 64,
        based_on_generation=1,
        provenance_refs=provenance or [],
        created_at="2026-08-05T00:00:00Z",
    )


def _task(kind: str, target: str, status: TaskStatus, **extra):
    return SimpleNamespace(
        task_id=f"task-{kind}-{target}",
        kind=kind,
        status=status,
        input_refs=[target],
        metadata={"targetRef": target, **extra.pop("metadata", {})},
        progress=extra.pop("progress", None),
        error=extra.pop("error", None),
        updated_at=extra.pop("updated_at", "2026-08-05T00:00:00Z"),
        idempotency_key=extra.pop("idempotency_key", None),
    )


def test_variant_nodes_cover_ready_running_failed_done() -> None:
    project = _project()
    project.visual.entities.items["char:a"] = _entity(
        "char:a",
        {"var:x": "art:x", "var:y": None},
    )
    project.visual.entities.order.append("char:a")
    project.visual.entities.items["char:b"] = _entity(
        "char:b",
        {"var:z": None},
    )
    project.visual.entities.order.append("char:b")

    graph = derive_work_graph(
        project,
        tasks=[
            _task(
                "image_generation",
                "asset:char:b",
                TaskStatus.RUNNING,
                metadata={"variantId": "var:z"},
                progress=0.4,
            ),
        ],
    )
    by_id = graph.by_id
    assert by_id["visual:char:a:var:x"].status is WorkNodeStatus.DONE
    assert by_id["visual:char:a:var:y"].status is WorkNodeStatus.READY
    running = by_id["visual:char:b:var:z"]
    assert running.status is WorkNodeStatus.RUNNING
    assert running.progress == 0.4


def test_failed_variant_carries_the_error_summary() -> None:
    project = _project()
    project.visual.entities.items["char:a"] = _entity(
        "char:a",
        {"var:x": None},
    )
    project.visual.entities.order.append("char:a")

    graph = derive_work_graph(
        project,
        tasks=[
            _task(
                "image_generation",
                "asset:char:a",
                TaskStatus.FAILED,
                error={"message": "safety rejected"},
            ),
        ],
    )
    node = graph.by_id["visual:char:a:var:x"]
    assert node.status is WorkNodeStatus.FAILED
    assert "safety rejected" in (node.error or "")


def test_prompt_rewrite_reopens_a_deterministically_failed_node() -> None:
    """FAILED parks a node only while its inputs are unchanged.

    Field run 2026-08-11: three safety-rejected character anchors kept
    their nodes FAILED after the agent rewrote the prompts, so the
    scheduler never retried and the project stalled. The dag idempotency
    key carries the dispatch fingerprint: an input change re-derives
    READY, while same-input failures (including transient retry slots)
    and agent-dispatched failures without a dag key stay parked.
    """

    project = _project()
    project.visual.entities.items["char:a"] = _entity(
        "char:a",
        {"var:x": None},
    )
    project.visual.entities.order.append("char:a")
    node_id = "visual:char:a:var:x"
    current = derive_work_graph(project).by_id[node_id].dispatch_fingerprint

    def status_with_failed_key(key: str | None) -> WorkNodeStatus:
        graph = derive_work_graph(
            project,
            tasks=[
                _task(
                    "image_generation",
                    "asset:char:a",
                    TaskStatus.FAILED,
                    metadata={"variantId": "var:x"},
                    error={"message": "safety rejected"},
                    idempotency_key=key,
                ),
            ],
        )
        return graph.by_id[node_id].status

    # The prompt (and thus the fingerprint) moved on: reopen.
    assert (
        status_with_failed_key(f"dag-{node_id}-stale-fingerprint")
        is WorkNodeStatus.READY
    )
    # Same inputs, including the transient retry slots: stay parked.
    assert (
        status_with_failed_key(f"dag-{node_id}-{current}")
        is WorkNodeStatus.FAILED
    )
    assert (
        status_with_failed_key(f"dag-{node_id}-{current}:transient-retry-1")
        is WorkNodeStatus.FAILED
    )
    # Agent-dispatched failures carry no graph identity: stay parked.
    assert status_with_failed_key(None) is WorkNodeStatus.FAILED


def test_lineup_gates_until_members_have_artwork() -> None:
    project = _project()
    project.visual.entities.items["char:a"] = _entity(
        "char:a",
        {"var:x": "art:a"},
    )
    project.visual.entities.order.append("char:a")
    project.visual.entities.items["char:b"] = _entity(
        "char:b",
        {"var:y": None},
    )
    project.visual.entities.order.append("char:b")
    project.visual.cast_lineups.items["lineup:main"] = VisualCastLineup(
        lineup_id="lineup:main",
        name="主阵容",
        character_refs=["char:a", "char:b"],
    )
    project.visual.cast_lineups.order.append("lineup:main")

    graph = derive_work_graph(project)
    node = graph.by_id["lineup:lineup:main"]
    assert node.status is WorkNodeStatus.GATED
    assert node.missing == ("visual:char:b:var:y",)

    # Give char:b artwork: the lineup becomes READY (dispatchable).
    project.visual.entities.items["char:b"].variants.items[
        "var:y"
    ].selected_artifact_version_id = "art:b"
    graph = derive_work_graph(project)
    node = graph.by_id["lineup:lineup:main"]
    assert node.status is WorkNodeStatus.READY
    assert node.command == "GENERATE_CAST_LINEUP_IMAGE"


def test_element_lane_storyboard_then_video() -> None:
    project = _project()
    project.visual.entities.items["char:a"] = _entity(
        "char:a",
        {"var:x": "art:a"},
    )
    project.visual.entities.order.append("char:a")
    _add_element(
        project,
        _element(
            "elem:one",
            character_refs=["char:a"],
            visual_variant_refs={"char:a": "var:x"},
        ),
    )

    graph = derive_work_graph(project)
    storyboard = graph.by_id["storyboard:elem:one"]
    video = graph.by_id["video:elem:one"]
    assert storyboard.status is WorkNodeStatus.READY
    assert video.status is WorkNodeStatus.GATED
    assert video.missing == ("storyboard:elem:one",)
    assert graph.by_id["compose:final"].status is WorkNodeStatus.GATED

    # Storyboard lands: video becomes READY.
    _select_slot(
        project,
        slot_id="element:elem:one:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:one",
        version_id="art:sb",
    )
    graph = derive_work_graph(project)
    assert graph.by_id["storyboard:elem:one"].status is WorkNodeStatus.DONE
    assert graph.by_id["video:elem:one"].status is WorkNodeStatus.READY

    # Video lands: compose becomes READY.
    _select_slot(
        project,
        slot_id="element:elem:one:main",
        kind="element_video",
        owner_ref="element:elem:one",
        version_id="art:vid",
    )
    graph = derive_work_graph(project)
    assert graph.by_id["video:elem:one"].status is WorkNodeStatus.DONE
    assert graph.by_id["compose:final"].status is WorkNodeStatus.READY


def test_missing_storyboard_prompt_is_a_model_required_gap() -> None:
    project = _project()
    _add_element(project, _element("elem:one", storyboard_prompt=""))

    graph = derive_work_graph(project)
    storyboard = graph.by_id["storyboard:elem:one"]
    assert storyboard.status is WorkNodeStatus.GATED
    assert storyboard.missing == ("storyboard_prompt 缺失",)
    # The scheduler cannot solve this: it needs a model turn.
    assert storyboard in graph.model_required_nodes()


def test_multi_character_storyboard_waits_for_the_planned_lineup() -> None:
    """The lineup image is the pairwise-contrast anchor.

    Field run (project-bb49): storyboards rendered while the planned
    lineup was still absent and identities drifted (duplicated jersey
    numbers). A planned lineup covering ≥2 of the element's characters
    must gate the storyboard until its image is selected.
    """

    project = _project()
    for ref in ("char:a", "char:b"):
        project.visual.entities.items[ref] = _entity(
            ref,
            {f"var:{ref[-1]}": f"art:{ref[-1]}"},
        )
        project.visual.entities.order.append(ref)
    project.visual.cast_lineups.items["lineup:duo"] = VisualCastLineup(
        lineup_id="lineup:duo",
        name="双人阵容",
        character_refs=["char:a", "char:b"],
    )
    project.visual.cast_lineups.order.append("lineup:duo")
    _add_element(
        project,
        _element(
            "elem:pair",
            character_refs=["char:a", "char:b"],
            visual_variant_refs={"char:a": "var:a", "char:b": "var:b"},
        ),
    )

    graph = derive_work_graph(project)
    storyboard = graph.by_id["storyboard:elem:pair"]
    assert storyboard.status is WorkNodeStatus.GATED
    assert "lineup:lineup:duo" in storyboard.missing

    # The lineup image lands: the storyboard unblocks.
    project.visual.cast_lineups.items[
        "lineup:duo"
    ].selected_artifact_version_id = "art:lineup"
    graph = derive_work_graph(project)
    assert graph.by_id["storyboard:elem:pair"].status is (WorkNodeStatus.READY)


def test_single_character_storyboard_ignores_planned_lineups() -> None:
    project = _project()
    for ref in ("char:a", "char:b"):
        project.visual.entities.items[ref] = _entity(
            ref,
            {f"var:{ref[-1]}": f"art:{ref[-1]}"},
        )
        project.visual.entities.order.append(ref)
    project.visual.cast_lineups.items["lineup:duo"] = VisualCastLineup(
        lineup_id="lineup:duo",
        name="双人阵容",
        character_refs=["char:a", "char:b"],
    )
    project.visual.cast_lineups.order.append("lineup:duo")
    _add_element(
        project,
        _element(
            "elem:solo",
            character_refs=["char:a"],
            visual_variant_refs={"char:a": "var:a"},
        ),
    )

    graph = derive_work_graph(project)
    assert graph.by_id["storyboard:elem:solo"].status is (WorkNodeStatus.READY)


def test_stale_marks_but_does_not_regenerate() -> None:
    project = _project()
    project.visual.entities.items["char:a"] = _entity(
        "char:a",
        {"var:x": "art:new"},
    )
    project.visual.entities.order.append("char:a")
    _add_element(
        project,
        _element(
            "elem:one",
            character_refs=["char:a"],
            visual_variant_refs={"char:a": "var:x"},
        ),
    )
    # Storyboard was drawn from art:old; the variant now selects art:new.
    _select_slot(
        project,
        slot_id="element:elem:one:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:one",
        version_id="art:sb",
        provenance=["artifact-version:art:old"],
    )

    graph = derive_work_graph(project)
    node = graph.by_id["storyboard:elem:one"]
    assert node.status is WorkNodeStatus.STALE
    # STALE is terminal for the scheduler: not READY, not dispatched.
    assert node not in graph.ready_media_nodes()


def test_waiting_review_never_counts_as_running() -> None:
    # A storyboard parked in review has no active task and no selected
    # slot yet — the graph reports GATED/READY truthfully; review-hold
    # visibility arrives through the review chip, not a fake RUNNING.
    project = _project()
    _add_element(project, _element("elem:one"))
    graph = derive_work_graph(project)
    assert graph.by_id["storyboard:elem:one"].status is WorkNodeStatus.READY


def test_storyboard_waits_for_all_referenced_entities_not_just_bindings() -> (
    None
):
    """Field run 2026-08-06: the graph said READY, the execution gate said
    no — shots referenced scene entities that had no artwork yet. The
    graph's dependency set must mirror visual_design_readiness."""
    project = _project()
    project.visual.entities.items["char:a"] = _entity(
        "char:a",
        {"var:x": "art:a"},
    )
    project.visual.entities.order.append("char:a")
    # Scene without required variants and without artwork: entity-level
    # readiness, machine-solvable through its single variant.
    scene = _entity("scene:home", {"var:day": None})
    project.visual.entities.items["scene:home"] = scene
    project.visual.entities.order.append("scene:home")
    _add_element(
        project,
        _element(
            "elem:one",
            character_refs=["char:a"],
            scene_ref="scene:home",
            visual_variant_refs={"char:a": "var:x"},
        ),
    )

    graph = derive_work_graph(project)
    storyboard = graph.by_id["storyboard:elem:one"]
    assert storyboard.status is WorkNodeStatus.GATED
    assert "visual:scene:home:var:day" in storyboard.missing
    # The gap is a media node: the scheduler can solve it, no model turn.
    assert storyboard not in graph.model_required_nodes()

    # Scene artwork lands (single-variant entities auto-select at entity
    # level on write-back, mirrored here): the storyboard opens up.
    scene.variants.items["var:day"].selected_artifact_version_id = "art:s"
    scene.selected_artifact_version_id = "art:s"
    graph = derive_work_graph(project)
    assert graph.by_id["storyboard:elem:one"].status is WorkNodeStatus.READY


def test_unset_entity_selection_is_a_model_gap_not_a_dispatch() -> None:
    project = _project()
    scene = _entity("scene:home", {})
    # No variants at all: the model must define one before anything is
    # drawable — a gap the scheduler must not paper over.
    project.visual.entities.items["scene:home"] = scene
    project.visual.entities.order.append("scene:home")
    _add_element(project, _element("elem:one", scene_ref="scene:home"))

    graph = derive_work_graph(project)
    storyboard = graph.by_id["storyboard:elem:one"]
    assert storyboard.status is WorkNodeStatus.GATED
    assert any("尚无使用中视觉产物" in reason for reason in storyboard.missing)
    assert storyboard in graph.model_required_nodes()


def test_ready_media_nodes_exclude_compose() -> None:
    project = _project()
    _add_element(project, _element("elem:one"))
    _select_slot(
        project,
        slot_id="element:elem:one:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:one",
        version_id="art:sb",
    )
    _select_slot(
        project,
        slot_id="element:elem:one:main",
        kind="element_video",
        owner_ref="element:elem:one",
        version_id="art:vid",
    )

    graph = derive_work_graph(project)
    compose = graph.by_id["compose:final"]
    assert compose.status is WorkNodeStatus.READY
    # The master render is machine-dispatchable: an unattended project
    # reaches its final cut without a user pressing "render".
    assert graph.ready_media_nodes() == (compose,)
    assert compose.command == "COMPOSE_FINAL_VIDEO"
    assert compose.target_ref == "timeline:timeline:main"
    assert graph.unfinished() == (compose,)


def test_stale_final_render_reopens_compose() -> None:
    # Render review revises an overlay after the master render: edit
    # impact marks the final_video version stale. The compose node must
    # drop back to READY so the unattended loop re-renders the corrected
    # cut instead of reporting DONE one compose short.
    project = _project()
    _add_element(project, _element("elem:one"))
    _select_slot(
        project,
        slot_id="element:elem:one:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:one",
        version_id="art:sb",
    )
    _select_slot(
        project,
        slot_id="element:elem:one:main",
        kind="element_video",
        owner_ref="element:elem:one",
        version_id="art:vid",
    )
    _select_slot(
        project,
        slot_id="timeline:timeline:main:render",
        kind="final_video",
        owner_ref="timeline:timeline:main",
        version_id="art:final",
    )

    graph = derive_work_graph(project)
    assert graph.by_id["compose:final"].status is WorkNodeStatus.DONE

    project.assets.artifact_versions_by_id["art:final"].stale = True
    graph = derive_work_graph(project)
    compose = graph.by_id["compose:final"]
    assert compose.status is WorkNodeStatus.READY
    assert compose in graph.ready_media_nodes()
