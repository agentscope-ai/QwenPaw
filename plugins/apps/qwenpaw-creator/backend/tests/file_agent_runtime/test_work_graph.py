# -*- coding: utf-8 -*-
# Pytest fixtures and contract probes retain exact types and private seams.
# pylint: disable=protected-access
# pylint: disable=use-implicit-booleaness-not-comparison
"""Work graph derivation: the production DAG projected from durable facts.

Every status is recomputed from project.json plus task records — the
graph is a view, never a second authority. These tests pin the node
identities, dependency edges and all seven states.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from domain.enums import TaskStatus
from services.file_agent_runtime.work_graph import (
    WorkNodeStatus,
    derive_work_graph,
    dispatch_ledger_fingerprint,
    dispatch_slot,
)
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    ElementLocation,
    IndexedFile,
    Project,
    R2VCreation,
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
                    prompt="专业视觉资产 prompt",
                    selected_artifact_version_id=selected,
                )
                for variant_id, selected in variants.items()
            },
            "order": list(variants),
        },
    )


def _element(element_id: str, **creation_kwargs) -> TimelineElement:
    defaults = {
        "narrative": "叙事",
        "storyboard_prompt": "分镜 prompt",
        "video_prompt": "视频 prompt",
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
    task_id: str | None = None,
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
        metadata={"taskId": task_id} if task_id else {},
        created_at="2026-08-05T00:00:00Z",
    )


def _task(kind: str, target: str, status: TaskStatus, **extra):
    return SimpleNamespace(
        task_id=f"task-{kind}-{target}",
        kind=kind,
        status=status,
        input_refs=[target],
        metadata={
            "targetRef": target,
            "storyboardInputContract": 2,
            **extra.pop("metadata", {}),
        },
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
    # Same inputs: stay parked.
    assert (
        status_with_failed_key(f"dag-{node_id}-{current}")
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
        {"var:x": "art:a", "var:later-state": None},
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
    assert graph.by_id["compose:timeline:main"].status is WorkNodeStatus.GATED

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
    assert graph.by_id["compose:timeline:main"].status is WorkNodeStatus.READY


def test_missing_storyboard_prompt_is_a_model_required_gap() -> None:
    project = _project()
    _add_element(project, _element("elem:one", storyboard_prompt=""))

    graph = derive_work_graph(project)
    storyboard = graph.by_id["storyboard:elem:one"]
    assert storyboard.status is WorkNodeStatus.GATED
    assert storyboard.missing == ("storyboard_prompt 缺失",)
    assert storyboard.authored_text_gap
    # The scheduler cannot solve this: it needs a model turn.
    assert storyboard in graph.model_required_nodes()


@pytest.mark.parametrize("base_state", ["none", "waiting", "selected"])
def test_missing_visual_prompt_is_a_model_required_gap(base_state) -> None:
    project = _project()
    variants = {"var:default": None}
    if base_state != "none":
        variants["var:base"] = (
            "artifact:base" if base_state == "selected" else None
        )
    entity = _entity("char:hero", variants)
    entity.variants.items["var:default"].prompt = ""
    if base_state != "none":
        entity.variants.items[
            "var:default"
        ].derived_from_variant_id = "var:base"
    project.visual.entities.items[entity.entity_id] = entity
    project.visual.entities.order.append(entity.entity_id)

    graph = derive_work_graph(project)
    visual = graph.by_id["visual:char:hero:var:default"]
    assert visual.status is WorkNodeStatus.GATED
    if base_state == "waiting":
        assert visual.missing == ("visual:char:hero:var:base",)
        assert not visual.authored_text_gap
        assert visual not in graph.model_required_nodes()
    else:
        assert visual.missing == ("visual_prompt 缺失",)
        assert visual.authored_text_gap
        assert visual in graph.model_required_nodes()
    # A one-line entity description fallback must never start a paid image
    # task before visual development has committed its production prompt.
    assert visual not in graph.ready_media_nodes()


def _element_with_landed_storyboard(
    project: Project,
    **creation_kwargs,
) -> None:
    _add_element(project, _element("elem:one", **creation_kwargs))
    _select_slot(
        project,
        slot_id="element:elem:one:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:one",
        version_id="art:sb",
    )


def test_pending_lineup_only_gates_storyboards_that_reference_it() -> None:
    """The graph and executor both scope readiness to actual shot inputs."""

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
            cast_lineup_refs=["lineup:duo"],
        ),
    )
    # The closing scene has one character and never references the lineup.
    _add_element(
        project,
        _element(
            "elem:solo",
            character_refs=["char:a"],
            visual_variant_refs={"char:a": "var:a"},
        ),
    )

    graph = derive_work_graph(project)
    solo = graph.by_id["storyboard:elem:solo"]
    assert solo.status is WorkNodeStatus.READY
    assert "lineup:lineup:duo" not in solo.deps
    assert graph.by_id["storyboard:elem:pair"].status is WorkNodeStatus.GATED

    # Its consuming pair opens only after the required group anchor lands.
    project.visual.cast_lineups.items[
        "lineup:duo"
    ].selected_artifact_version_id = "art:lineup"
    graph = derive_work_graph(project)
    assert graph.by_id["storyboard:elem:solo"].status is WorkNodeStatus.READY
    assert graph.by_id["storyboard:elem:pair"].status is WorkNodeStatus.READY


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


def test_stale_manual_storyboard_is_visible_but_not_dispatched() -> None:
    """The lifecycle flag is authoritative, never automatic spend authority."""

    project = _project()
    _add_element(project, _element("elem:one"))
    _select_slot(
        project,
        slot_id="element:elem:one:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:one",
        version_id="art:manual-storyboard",
    )
    project.assets.artifact_versions_by_id[
        "art:manual-storyboard"
    ].stale = True

    graph = derive_work_graph(project)
    node = graph.by_id["storyboard:elem:one"]

    assert node.status is WorkNodeStatus.STALE
    assert node not in graph.ready_media_nodes()


@pytest.mark.parametrize(
    ("changed_input", "legacy", "expected"),
    [
        ("aspect_ratio", False, WorkNodeStatus.STALE),
        ("storyboard_prompt", False, WorkNodeStatus.STALE),
        ("media_models", False, WorkNodeStatus.DONE),
        ("media_models", True, WorkNodeStatus.DONE),
    ],
)
def test_completed_storyboard_reacts_only_to_its_content_inputs(
    changed_input,
    legacy,
    expected,
) -> None:
    project = _project()
    _add_element(project, _element("elem:one"))
    node_id = "storyboard:elem:one"
    original = derive_work_graph(project).by_id[node_id].dispatch_fingerprint
    models = ("old-image", "old-video")
    ledger = dispatch_ledger_fingerprint(original, models)
    slot = (
        hashlib.sha256(ledger.encode()).hexdigest()[:16]
        if legacy
        else dispatch_slot(ledger)
    )
    task = _task(
        "image_generation",
        "element:elem:one",
        TaskStatus.SUCCEEDED,
        idempotency_key=f"dag-{node_id}-{slot}",
    )
    _select_slot(
        project,
        slot_id="element:elem:one:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:one",
        version_id="art:sb",
        task_id=task.task_id,
    )
    assert (
        derive_work_graph(
            project,
            tasks=[task],
            media_models=models,
        )
        .by_id[node_id]
        .status
        is WorkNodeStatus.DONE
    )

    if changed_input == "aspect_ratio":
        project.settings.aspect_ratio = "9:16"
    elif changed_input == "storyboard_prompt":
        creation = (
            project.timelines.items["timeline:main"]
            .elements_by_id["elem:one"]
            .creation
        )
        creation.storyboard_prompt += "主角挥手。"
    else:
        models = ("new-image", "new-video")

    before = project.model_dump(mode="json")
    graph = derive_work_graph(
        project,
        tasks=[task],
        media_models=models,
    )
    assert graph.by_id[node_id].status is expected
    if expected is WorkNodeStatus.DONE:
        assert node_id not in {
            node.node_id for node in graph.regeneration_nodes()
        }
    assert project.model_dump(mode="json") == before


def test_failed_storyboard_reopens_when_aspect_ratio_changes() -> None:
    project = _project()
    _add_element(project, _element("elem:one"))
    node_id = "storyboard:elem:one"
    original = derive_work_graph(project).by_id[node_id].dispatch_fingerprint
    failed = _task(
        "image_generation",
        "element:elem:one",
        TaskStatus.FAILED,
        error={"message": "provider rejected layout"},
        idempotency_key=f"dag-{node_id}-{original}",
    )
    assert (
        derive_work_graph(
            project,
            tasks=[failed],
            media_models=("image", "video"),
        )
        .by_id[node_id]
        .status
        is WorkNodeStatus.FAILED
    )

    project.settings.aspect_ratio = "9:16"
    assert (
        derive_work_graph(
            project,
            tasks=[failed],
            media_models=("image", "video"),
        )
        .by_id[node_id]
        .status
        is WorkNodeStatus.READY
    )


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
    assert graph.by_id["compose:timeline:main"].status is WorkNodeStatus.DONE

    project.assets.artifact_versions_by_id["art:final"].stale = True
    graph = derive_work_graph(project)
    compose = graph.by_id["compose:timeline:main"]
    assert compose.status is WorkNodeStatus.READY
    assert compose in graph.ready_media_nodes()


def test_superseded_render_source_reopens_compose_without_stale_flag() -> None:
    """Frozen selections are authoritative even if impact missed stale."""

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
        version_id="art:vid-old",
    )
    _select_slot(
        project,
        slot_id="timeline:timeline:main:render",
        kind="final_video",
        owner_ref="timeline:timeline:main",
        version_id="art:final",
    )
    project.assets.artifact_versions_by_id["art:final"].metadata = {
        "sourceSelections": [
            {
                "sourceRef": "element:elem:one",
                "versionId": "art:vid-old",
            },
        ],
    }
    assert (
        derive_work_graph(project).by_id["compose:timeline:main"].status
        is WorkNodeStatus.DONE
    )

    _select_slot(
        project,
        slot_id="element:elem:one:main",
        kind="element_video",
        owner_ref="element:elem:one",
        version_id="art:vid-new",
    )
    # The lifecycle bug observed in the real run left this false.
    assert not project.assets.artifact_versions_by_id["art:final"].stale
    graph = derive_work_graph(project)
    compose = graph.by_id["compose:timeline:main"]
    assert compose.status is WorkNodeStatus.READY
    assert compose in graph.ready_media_nodes()


def test_budget_dropped_reference_does_not_stale_the_artifact() -> None:
    """A reference the model budget forced out of the automatic chain is
    absent from provenance by design. Field run 2026-08-26: reading that as
    drift marked all four truncated portrait storyboards permanently stale,
    a false "needs review" on artifacts that were correct.
    """
    from services.file_agent_runtime.work_graph import _artifact_is_stale

    project = Project.new(project_id="p-stale", name="Stale")
    project.assets.artifact_versions_by_id["art:sb"] = ArtifactVersion(
        version_id="art:sb",
        slot_id="element:elem:1:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:1",
        name="分镜图",
        file_id="file-sb",
        checksum="0" * 64,
        based_on_generation=1,
        created_at="2026-08-26T00:00:00Z",
        provenance_refs=["artifact-version:art:kept"],
        metadata={"budgetDroppedReferenceVersionIds": ["art:dropped"]},
    )

    # The dropped reference must not count as drift...
    assert not _artifact_is_stale(
        project,
        "art:sb",
        ["art:kept", "art:dropped"],
    )
    # ...while a genuinely new upstream selection still does.
    assert _artifact_is_stale(
        project,
        "art:sb",
        ["art:kept", "art:something-new"],
    )


def test_upgrade_does_not_restale_artifacts_from_the_old_ledger() -> None:
    """The ledger fingerprint dropped the plaintext model names, and the
    storyboard graph fingerprint gained aspect ratio and shot count. Every
    durable key minted before that therefore mismatches today's digest. Reading
    the mismatch as drift would flip every pre-existing storyboard from DONE to
    READY and auto-dispatch a paid re-render, replacing artifacts the user had
    already accepted.
    """
    from services.file_agent_runtime.work_graph import (
        _artifact_is_stale,
        dispatch_key_predates_digest_ledger,
    )

    project = Project.new(project_id="p-upgrade", name="Upgrade")
    project.assets.artifact_versions_by_id["art:sb"] = ArtifactVersion(
        version_id="art:sb",
        slot_id="element:elem:1:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:1",
        name="分镜图",
        file_id="file-sb",
        checksum="0" * 64,
        based_on_generation=1,
        created_at="2026-08-20T00:00:00Z",
        metadata={"taskId": "task-legacy"},
    )
    node_id = "storyboard:elem:1"
    legacy_key = (
        f"dag-{node_id}-a1b2c3d4e5f60718"
        "|img:qwen-image-3.0-pro|vid:wan3.0-video"
    )
    assert dispatch_key_predates_digest_ledger(legacy_key)

    legacy_task = SimpleNamespace(
        task_id="task-legacy",
        idempotency_key=legacy_key,
    )
    assert not _artifact_is_stale(
        project,
        "art:sb",
        [],
        node_id=node_id,
        dispatch_fingerprint="9f8e7d6c5b4a3210",
        tasks=[legacy_task],
    )

    # A key already in the digest format is still compared, so a genuine input
    # change after the upgrade is still caught.
    versions = project.assets.artifact_versions_by_id
    versions["art:sb2"] = versions["art:sb"].model_copy(
        update={"version_id": "art:sb2", "metadata": {"taskId": "task-new"}},
    )
    new_task = SimpleNamespace(
        task_id="task-new",
        metadata={"storyboardInputContract": 2},
        idempotency_key=f"dag-{node_id}-a1b2c3d4e5f60718-mdeadbeefdeadbeef",
    )
    assert _artifact_is_stale(
        project,
        "art:sb2",
        [],
        node_id=node_id,
        dispatch_fingerprint="9f8e7d6c5b4a3210",
        tasks=[new_task],
        media_models=("image", "video"),
    )


@pytest.mark.parametrize(
    "mode,inputs,command",
    [
        ("t2v", {"video_prompt": "A beautiful sunset"}, "GENERATE_R2V_VIDEO"),
        (
            "i2v",
            {
                "video_prompt": "A beautiful sunset",
                "first_frame_version_id": "img:first-frame",
            },
            "GENERATE_R2V_VIDEO",
        ),
        (
            "s2v",
            {
                "portrait_version_id": "img:portrait",
                "audio_version_id": "aud:voice",
            },
            "GENERATE_S2V_VIDEO",
        ),
    ],
)
@pytest.mark.parametrize("ready", [True, False])
def test_non_r2v_modes_schedule_video_only_when_inputs_ready(
    mode,
    inputs,
    command,
    ready,
):
    project = _project()
    _add_element(
        project,
        TimelineElement.model_validate(
            {
                "element_id": "elem:video",
                "label": "Video",
                "span": {"start_tick": 0, "duration_tick": 4000},
                "location": {},
                "creation": {"type": mode, **(inputs if ready else {})},
            },
        ),
    )
    graph = derive_work_graph(project)
    assert "storyboard:elem:video" not in graph.by_id
    node = graph.by_id["video:elem:video"]
    if ready:
        assert node.status is WorkNodeStatus.READY
        assert node.command == command
        assert node.dispatch_arguments == (
            {} if mode == "s2v" else {"mode": mode}
        )
    else:
        assert node.status is WorkNodeStatus.GATED
        for field in inputs:
            if mode == "i2v" and field == "video_prompt":
                continue  # I2V can animate the first frame without extra text.
            assert f"{field} 缺失" in node.missing


def test_mixed_timeline_compose_includes_t2v_i2v_s2v() -> None:
    """Compose node includes T2V/I2V/S2V video nodes as dependencies."""
    from services.project_files.models import (
        I2VCreation,
        S2VCreation,
        T2VCreation,
    )

    project = _project()

    # Add T2V element
    t2v_element = TimelineElement(
        element_id="elem:t2v",
        label="T2V",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=T2VCreation(video_prompt="T2V prompt"),
    )
    _add_element(project, t2v_element)

    # Add I2V element
    i2v_element = TimelineElement(
        element_id="elem:i2v",
        label="I2V",
        span=TimelineSpan(start_tick=4_000, duration_tick=4_000),
        location=ElementLocation(),
        creation=I2VCreation(
            video_prompt="I2V prompt",
            first_frame_version_id="img:first",
        ),
    )
    _add_element(project, i2v_element)

    # Add S2V element
    s2v_element = TimelineElement(
        element_id="elem:s2v",
        label="S2V",
        span=TimelineSpan(start_tick=8_000, duration_tick=4_000),
        location=ElementLocation(),
        creation=S2VCreation(
            portrait_version_id="img:portrait",
            audio_version_id="aud:voice",
        ),
    )
    _add_element(project, s2v_element)

    graph = derive_work_graph(project)
    by_id = graph.by_id

    # All three video nodes exist
    assert "video:elem:t2v" in by_id
    assert "video:elem:i2v" in by_id
    assert "video:elem:s2v" in by_id

    # Compose node exists and depends on all video nodes
    compose = by_id["compose:timeline:main"]
    assert compose is not None
    assert "video:elem:t2v" in compose.deps
    assert "video:elem:i2v" in compose.deps
    assert "video:elem:s2v" in compose.deps


@pytest.mark.parametrize(
    "command_name",
    ["COMPOSE_FINAL_VIDEO", "EXECUTE_EDIT"],
)
def test_episode_compilation_reuses_artifacts_with_original_audio(
    command_name: str,
) -> None:
    """Saved Edit facts must reach a render recipe without new generation."""
    from domain.enums import CreatorCommandType
    from pydantic import ValidationError
    from services.media_files.local_execution import _timeline_execution
    from services.project_files.models import (
        ArtifactVersionRenderSource,
        EditCreation,
    )

    project = _project()
    for episode in range(1, 7):
        version_id = f"art:episode-{episode}"
        _select_slot(
            project,
            slot_id=f"timeline:timeline:ep{episode}:render",
            kind="final_video",
            owner_ref=f"timeline:timeline:ep{episode}",
            version_id=version_id,
        )
        project.assets.files_by_id[
            f"file-{version_id}"
        ].media_type = "video/mp4"
        project.assets.artifact_versions_by_id[
            version_id
        ].duration_seconds = 10.0
        _add_element(
            project,
            TimelineElement(
                element_id=f"elem:episode-{episode}",
                location=ElementLocation(),
                span=TimelineSpan(
                    start_tick=(episode - 1) * 3000,
                    duration_tick=3000,
                ),
                creation=EditCreation(intent="按集序复用已有成片"),
                render_source=ArtifactVersionRenderSource(
                    version_id=version_id,
                    source_in_tick=1000,
                    source_out_tick=7000,
                    playback_rate=2.0,
                ),
            ),
        )
    project = Project.model_validate(project.model_dump(mode="json"))
    graph = derive_work_graph(project)
    compose = graph.by_id["compose:timeline:main"]
    assert compose.status is WorkNodeStatus.READY
    assert compose.deps == ()
    assert not any(
        node.kind in {"storyboard", "video"} for node in graph.nodes
    )

    resolved = _timeline_execution(
        project=project,
        timeline=project.timelines.items["timeline:main"],
        target_ref="timeline:timeline:main",
        command=CreatorCommandType[command_name],
    )
    assert [item.version_id for item in resolved.inputs] == [
        f"art:episode-{episode}" for episode in range(1, 7)
    ]
    for item in resolved.inputs:
        assert (item.start_seconds, item.end_seconds) == (1.0, 7.0)
        assert item.playback_rate == 2.0
        assert item.original_sound == "preserve"
    assert all(
        item["ref"].startswith("artifact-version:")
        for item in resolved.read_set
    )
    assert [item["startTick"] for item in resolved.source_selections] == list(
        range(0, 18000, 3000),
    )

    # Allowing generated inputs must retain the exact trim/span contract.
    raw = project.model_dump(mode="json")
    source = raw["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "elem:episode-1"
    ]["render_source"]
    source["source_out_tick"] = None
    with pytest.raises(ValidationError, match="requires source_out_tick"):
        Project.model_validate(raw)
    source["source_out_tick"] = 5000
    with pytest.raises(ValidationError, match="duration mismatch"):
        Project.model_validate(raw)


def test_stale_nodes_are_model_required() -> None:
    """STALE nodes are included in model_required_nodes()."""
    project = _project()

    # Create an R2V element with storyboard and video
    element = _element("elem:one")
    _add_element(project, element)

    # Set up storyboard slot with a selected version
    _select_slot(
        project,
        slot_id="element:elem:one:storyboard",
        kind="storyboard",
        owner_ref="element:elem:one",
        version_id="art:storyboard",
        provenance=[],  # Empty provenance - not stale
    )

    # Set up video slot with provenance that doesn't include storyboard
    # This makes the video node STALE because storyboard selection changed
    _select_slot(
        project,
        slot_id="element:elem:one:main",
        kind="element_video",
        owner_ref="element:elem:one",
        version_id="art:video",
        provenance=["asset-version:old-storyboard"],  # Not current storyboard
    )

    graph = derive_work_graph(project)
    video_node = graph.by_id["video:elem:one"]
    assert video_node.status is WorkNodeStatus.STALE

    # STALE nodes should be in model_required_nodes
    required = graph.model_required_nodes()
    assert video_node in required


# ---- Blueprint script lane（方案 3.2/3.3）--------------------------------


def _add_second_timeline(project: Project) -> None:
    from services.project_files.models import Timeline

    project.timelines.items["timeline:ep2"] = Timeline(
        timeline_id="timeline:ep2",
        title="第二集 · 旧宅疑云",
        synopsis="林晚发现母亲遗物的秘密。",
    )
    project.timelines.order.append("timeline:ep2")


def test_legacy_single_timeline_project_has_no_script_node() -> None:
    """旧项目（单 timeline 且无 script slot）零回退：不生成 script 节点。"""

    project = _project()
    _add_element(project, _element("elem:one"))
    graph = derive_work_graph(project)
    assert not [node for node in graph.nodes if node.kind == "script"]
    storyboard = graph.by_id["storyboard:elem:one"]
    assert "script:timeline:main" not in storyboard.deps


def test_multi_timeline_project_derives_script_nodes_gating_elements() -> None:
    project = _project()
    _add_second_timeline(project)
    _add_element(project, _element("elem:one"))

    graph = derive_work_graph(project)
    main_script = graph.by_id["script:timeline:main"]
    ep2_script = graph.by_id["script:timeline:ep2"]
    # slot 无版本 → READY，可被调度器直接派发。
    assert main_script.status is WorkNodeStatus.READY
    assert ep2_script.status is WorkNodeStatus.READY
    assert main_script.command == "GENERATE_TIMELINE_SCRIPT"
    assert main_script.timeline_id == "timeline:main"
    assert ep2_script.lane == "第二集 · 旧宅疑云"
    assert ep2_script.locator == {
        "page": "blueprint",
        "timelineId": "timeline:ep2",
    }
    assert main_script in graph.ready_media_nodes()

    # 该 timeline 的 storyboard/video 等待剧本节点。
    storyboard = graph.by_id["storyboard:elem:one"]
    video = graph.by_id["video:elem:one"]
    assert "script:timeline:main" in storyboard.deps
    assert storyboard.status is WorkNodeStatus.GATED
    assert "script:timeline:main" in storyboard.missing
    assert video.deps == ("script:timeline:main", "storyboard:elem:one")
    assert storyboard.timeline_id == "timeline:main"

    # 剧本版本选定后分镜解除门禁。
    _select_slot(
        project,
        slot_id="script:timeline:main",
        kind="timeline_script",
        owner_ref="timeline:timeline:main",
        version_id="art:script-main",
    )
    graph = derive_work_graph(project)
    assert graph.by_id["script:timeline:main"].status is WorkNodeStatus.DONE
    assert graph.by_id["storyboard:elem:one"].status is WorkNodeStatus.READY


def test_stale_script_version_marks_script_node_stale() -> None:
    project = _project()
    _add_second_timeline(project)
    project.timelines.items["timeline:ep2"].description = "已有旧正文"
    _select_slot(
        project,
        slot_id="script:timeline:ep2",
        kind="timeline_script",
        owner_ref="timeline:timeline:ep2",
        version_id="art:script-ep2",
    )
    project.assets.artifact_versions_by_id["art:script-ep2"].stale = True

    graph = derive_work_graph(project)
    node = graph.by_id["script:timeline:ep2"]
    assert node.status is WorkNodeStatus.STALE
    # STALE is terminal for the scheduler: not READY, not dispatched.
    assert node not in graph.ready_media_nodes()


@pytest.mark.parametrize("body", ["已发布正文：孙老四端茶，说完台词。", "", "  \n"])
def test_authored_episode_body_satisfies_script_dependency(body: str) -> None:
    project = _project()
    _add_second_timeline(project)
    project.timelines.items["timeline:main"].description = body
    project.timelines.items["timeline:main"].synopsis = "仅梗概不足以制作"
    _add_element(project, _element("elem:one"))

    graph = derive_work_graph(project)
    script = graph.by_id["script:timeline:main"]
    storyboard = graph.by_id["storyboard:elem:one"]
    assert (script.status is WorkNodeStatus.DONE) == bool(body.strip())
    assert (storyboard.status is WorkNodeStatus.READY) == bool(body.strip())
    assert graph.by_id["script:timeline:ep2"].status is WorkNodeStatus.READY

    # Once artifact versioning is used, deselecting/rejecting its result
    # must not silently fall back to an older inline body.
    project.assets.artifact_slots_by_id["script:timeline:main"] = ArtifactSlot(
        slot_id="script:timeline:main",
        kind="timeline_script",
        owner_ref="timeline:timeline:main",
    )
    graph = derive_work_graph(project)
    assert graph.by_id["script:timeline:main"].status is WorkNodeStatus.READY
    assert graph.by_id["storyboard:elem:one"].status is WorkNodeStatus.GATED


def test_single_timeline_with_script_slot_opts_into_script_flow() -> None:
    """存在 timeline_script slot 的单 timeline 项目也进入剧本流。"""

    project = _project()
    _select_slot(
        project,
        slot_id="script:timeline:main",
        kind="timeline_script",
        owner_ref="timeline:timeline:main",
        version_id="art:script-main",
    )
    _add_element(project, _element("elem:one"))

    graph = derive_work_graph(project)
    script = graph.by_id["script:timeline:main"]
    assert script.status is WorkNodeStatus.DONE
    assert "script:timeline:main" in graph.by_id["storyboard:elem:one"].deps


def test_running_script_task_projects_running_status() -> None:
    project = _project()
    _add_second_timeline(project)
    graph = derive_work_graph(
        project,
        tasks=[
            _task(
                "script_draft",
                "timeline:timeline:ep2",
                TaskStatus.RUNNING,
                progress=0.5,
            ),
        ],
    )
    node = graph.by_id["script:timeline:ep2"]
    assert node.status is WorkNodeStatus.RUNNING
    assert node.progress == 0.5


# ---- History snapshots are frozen: never part of the production graph ----


def _append_snapshot(project: Project, base_id: str = "timeline:main") -> None:
    """Clone *base_id* as a frozen history snapshot (mirrors auto_snapshot)."""

    from services.project_files.models import Timeline

    raw = project.timelines.items[base_id].model_dump(mode="json")
    snapshot_id = f"snapshot:{base_id}:1"
    raw["timeline_id"] = snapshot_id
    remapped = {}
    for element_id, element in raw["elements_by_id"].items():
        element = dict(element)
        element["element_id"] = f"{snapshot_id}:{element_id}"
        remapped[f"{snapshot_id}:{element_id}"] = element
    raw["elements_by_id"] = remapped
    project.timelines.items[snapshot_id] = Timeline.model_validate(raw)
    project.timelines.order.append(snapshot_id)


def test_snapshot_never_enters_the_work_graph() -> None:
    """单正式 timeline + 快照仍是单集：不开 script flow，也没有任何
    script/storyboard/video/compose 节点指向 snapshot:*。"""

    project = _project()
    _add_element(project, _element("elem:one"))
    _append_snapshot(project)

    graph = derive_work_graph(project)

    assert not [node for node in graph.nodes if node.kind == "script"]
    snapshot_nodes = [
        node.node_id for node in graph.nodes if "snapshot:" in node.node_id
    ]
    assert snapshot_nodes == []
    # The live element still gets its lane.
    assert "storyboard:elem:one" in graph.by_id


def test_snapshot_does_not_count_toward_script_flow() -> None:
    """多正式 timeline 按正式数量判定；快照不改变 script 节点集合。"""

    project = _project()
    _add_element(project, _element("elem:one"))
    _add_second_timeline(project)
    _append_snapshot(project)

    graph = derive_work_graph(project)

    script_nodes = sorted(
        node.node_id for node in graph.nodes if node.kind == "script"
    )
    assert script_nodes == ["script:timeline:ep2", "script:timeline:main"]


def test_style_anchor_gates_then_rides_the_base_selection() -> None:
    """`visual:<entity>:<variant>` refs plan a spatial group up front.

    Field run 2026-09-11 (卧室/家门口/电梯口): related scenes rendered in
    parallel with zero cross references. The anchor gates the dependent
    scene until the base image is selected, then resolves into the dispatch
    fingerprint so a re-selected base re-identifies the node.
    """

    project = _project()
    project.visual.entities.items["scene:bedroom"] = _entity(
        "scene:bedroom",
        {"var:base": None},
    )
    project.visual.entities.order.append("scene:bedroom")
    project.visual.entities.items["scene:door"] = _entity(
        "scene:door",
        {"var:base": None},
    )
    project.visual.entities.order.append("scene:door")
    anchor_ref = "visual:scene:bedroom:var:base"
    door = project.visual.entities.items["scene:door"].variants.items[
        "var:base"
    ]
    door.reference_artifact_version_ids = [anchor_ref]
    node_id = "visual:scene:door:var:base"

    gated = derive_work_graph(project).by_id[node_id]
    assert gated.status is WorkNodeStatus.GATED
    assert gated.missing == (anchor_ref,)
    assert gated.deps == (anchor_ref,)

    bedroom = project.visual.entities.items["scene:bedroom"].variants.items[
        "var:base"
    ]
    bedroom.selected_artifact_version_id = "art:bed-1"
    ready = derive_work_graph(project).by_id[node_id]
    assert ready.status is WorkNodeStatus.READY
    first = ready.dispatch_fingerprint

    # The anchor resolves to the concrete base image: choosing another base
    # version changes the dependent's input identity.
    bedroom.selected_artifact_version_id = "art:bed-2"
    second = derive_work_graph(project).by_id[node_id].dispatch_fingerprint
    assert first != second

    # A repaint in flight re-gates the dependent: rendering against the
    # outgoing base image burns a paid call that the update quarantines.
    repainting = derive_work_graph(
        project,
        tasks=[
            _task(
                "image_generation",
                "asset:scene:bedroom",
                TaskStatus.RUNNING,
                metadata={"variantId": "var:base"},
            ),
        ],
    ).by_id[node_id]
    assert repainting.status is WorkNodeStatus.GATED
    assert repainting.missing == (anchor_ref,)


def test_completed_dependent_goes_stale_when_the_base_reselects() -> None:
    """A finished related scene must surface as STALE once its anchor's
    image changes — silently staying DONE hid the drift (CR 2026-09-11)."""

    project = _project()
    project.visual.entities.items["scene:bedroom"] = _entity(
        "scene:bedroom",
        {"var:base": "art:bed-1"},
    )
    project.visual.entities.order.append("scene:bedroom")
    project.visual.entities.items["scene:door"] = _entity(
        "scene:door",
        {"var:door": "art:door-1"},
    )
    project.visual.entities.order.append("scene:door")
    door = project.visual.entities.items["scene:door"].variants.items[
        "var:door"
    ]
    door.reference_artifact_version_ids = ["visual:scene:bedroom:var:base"]
    _select_slot(
        project,
        slot_id="asset:scene:door:variant:var:door:image",
        kind="visual_asset_image",
        owner_ref="asset:scene:door",
        version_id="art:door-1",
        provenance=["artifact-version:art:bed-1"],
    )
    node_id = "visual:scene:door:var:door"

    assert derive_work_graph(project).by_id[node_id].status is (
        WorkNodeStatus.DONE
    )

    repainting = _task(
        "image_generation",
        "asset:scene:bedroom",
        TaskStatus.RUNNING,
        metadata={"variantId": "var:base"},
    )
    held = derive_work_graph(project, tasks=[repainting]).by_id[node_id]
    assert held.status is WorkNodeStatus.GATED
    assert held.missing == ("visual:scene:bedroom:var:base",)

    bedroom = project.visual.entities.items["scene:bedroom"].variants.items[
        "var:base"
    ]
    bedroom.selected_artifact_version_id = "art:bed-2"
    graph = derive_work_graph(project)
    assert graph.by_id[node_id].status is WorkNodeStatus.STALE
    assert graph.by_id[node_id].regeneration_of == "art:door-1"
    assert node_id in {node.node_id for node in graph.regeneration_nodes()}

    held = derive_work_graph(project, tasks=[repainting])
    assert held.by_id[node_id].missing == ("visual:scene:bedroom:var:base",)
    assert held.regeneration_nodes() == ()


def test_failed_reroll_is_not_masked_by_the_old_success() -> None:
    """A failure newer than the selected artifact surfaces as FAILED and
    stays parked (reopening would replay the finished base slot forever);
    an older, already-superseded failure keeps the node DONE."""

    project = _project()
    project.visual.entities.items["char:a"] = _entity(
        "char:a",
        {"var:x": "art:x"},
    )
    project.visual.entities.order.append("char:a")
    _select_slot(
        project,
        slot_id="asset:char:a:variant:var:x:image",
        kind="visual_asset_image",
        owner_ref="asset:char:a",
        version_id="art:x",
    )
    node_id = "visual:char:a:var:x"

    def status_with_failure(updated_at: str) -> WorkNodeStatus:
        return (
            derive_work_graph(
                project,
                tasks=[
                    _task(
                        "image_generation",
                        "asset:char:a",
                        TaskStatus.FAILED,
                        metadata={"variantId": "var:x"},
                        error={"message": "orphaned before claim"},
                        idempotency_key=f"dag-{node_id}-reroll-slot",
                        updated_at=updated_at,
                    ),
                ],
            )
            .by_id[node_id]
            .status
        )

    # The artifact fixture is created at 2026-08-05.
    assert status_with_failure("2026-08-06T00:00:00Z") is (
        WorkNodeStatus.FAILED
    )
    assert status_with_failure("2026-08-04T00:00:00Z") is WorkNodeStatus.DONE


@pytest.mark.parametrize("reverse_tasks", [False, True])
@pytest.mark.parametrize("status", [TaskStatus.RUNNING, TaskStatus.FAILED])
def test_visual_tasks_keep_each_variant_and_anchor_isolated(
    reverse_tasks: bool,
    status: TaskStatus,
) -> None:
    project = _project()
    entity = _entity("scene:room", {"var:base": "art:base", "var:alt": None})
    dependent = _entity("scene:door", {"var:door": None})
    anchor_ref = "visual:scene:room:var:base"
    dependent.variants.items["var:door"].reference_artifact_version_ids = [
        anchor_ref,
    ]
    project.visual.entities.items.update(
        {entity.entity_id: entity, dependent.entity_id: dependent},
    )
    project.visual.entities.order.extend(
        [entity.entity_id, dependent.entity_id],
    )
    tasks = [
        _task(
            "image_generation",
            "asset:scene:room",
            status,
            metadata={"variantId": variant_id},
            updated_at=f"2026-08-0{6 + index}T00:00:00Z",
        )
        for index, variant_id in enumerate(entity.variants.order)
    ]
    graph = derive_work_graph(
        project,
        list(reversed(tasks)) if reverse_tasks else tasks,
    )
    expected = (
        WorkNodeStatus.RUNNING
        if status is TaskStatus.RUNNING
        else WorkNodeStatus.FAILED
    )
    assert graph.by_id[anchor_ref].status is expected
    assert graph.by_id["visual:scene:room:var:alt"].status is expected
    assert (
        graph.by_id["visual:scene:door:var:door"].status
        is WorkNodeStatus.GATED
    )
    assert graph.by_id["visual:scene:door:var:door"].missing == (anchor_ref,)


@pytest.mark.parametrize("reverse_entities", [False, True])
def test_anchor_chain_waits_for_stale_intermediate_before_initial_render(
    reverse_entities: bool,
) -> None:
    project = _project()
    ids = ["scene:base", "scene:middle", "scene:leaf"]
    for entity_id, selected in zip(ids, ["art:base-2", "art:middle-1", None]):
        project.visual.entities.items[entity_id] = _entity(
            entity_id,
            {"var:x": selected},
        )
    project.visual.entities.order.extend(
        reversed(ids) if reverse_entities else ids,
    )
    middle_ref = "visual:scene:middle:var:x"
    for entity_id, anchor in zip(ids[1:], ids):
        project.visual.entities.items[entity_id].variants.items[
            "var:x"
        ].reference_artifact_version_ids = [f"visual:{anchor}:var:x"]
    _select_slot(
        project,
        slot_id="asset:scene:middle:variant:var:x:image",
        kind="visual_asset_image",
        owner_ref="asset:scene:middle",
        version_id="art:middle-1",
        provenance=["artifact-version:art:base-1"],
    )
    graph = derive_work_graph(project)
    assert graph.by_id[middle_ref].status is WorkNodeStatus.STALE
    leaf = graph.by_id["visual:scene:leaf:var:x"]
    assert leaf.status is WorkNodeStatus.GATED
    assert leaf.missing == (middle_ref,)
    assert graph.ready_media_nodes() == ()
    assert [node.node_id for node in graph.regeneration_nodes()] == [
        middle_ref,
    ]
