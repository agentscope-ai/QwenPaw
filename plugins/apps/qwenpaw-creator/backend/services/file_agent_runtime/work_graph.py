# -*- coding: utf-8 -*-
"""Derived work graph: the project's production plan as a DAG snapshot.

The graph is a pure projection of ``project.json`` plus runtime task
records — never a second source of truth. Node identity is canonical
(entity/element derived), dependencies mirror the deterministic gates
the Runtime already enforces (visual readiness, lineup gate, storyboard
before video), and node states are recomputed from durable facts on
every derivation. The completion-loop criterion ("element with creation
but no main video") generalizes here to the whole pipeline.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

from domain.enums import TaskKind, TaskStatus
from services.project_files.models import Project, R2VCreation


class WorkNodeStatus(StrEnum):
    DONE = "done"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    FAILED = "failed"
    GATED = "gated"
    READY = "ready"
    STALE = "stale"


# Node kinds the scheduler may dispatch without a model turn: their
# generation parameters are deterministically assembled from project.json.
DISPATCHABLE_KINDS = frozenset({"visual", "lineup", "storyboard", "video"})


@dataclass(frozen=True, slots=True)
class WorkNode:
    node_id: str
    kind: str  # visual | lineup | storyboard | video | compose
    label: str
    status: WorkNodeStatus
    deps: tuple[str, ...] = ()
    lane: str = ""
    # Actionable context for UI and the completion loop.
    task_id: str | None = None
    progress: float | None = None
    error: str | None = None
    missing: tuple[str, ...] = ()  # unmet dependency node ids / reasons
    locator: dict[str, Any] = field(default_factory=dict)
    # Dispatch recipe (command + targetRef) for scheduler / manual retry.
    command: str | None = None
    target_ref: str | None = None
    dispatch_arguments: dict[str, Any] = field(default_factory=dict)
    # Input identity for scheduler idempotency: changes only when the
    # node's prompt or upstream selections change, so a FAILED node is
    # not redispatched until something about its inputs actually moved.
    dispatch_fingerprint: str | None = None


def _fingerprint(*parts: Any) -> str:
    digest = hashlib.sha256(
        "\x1f".join(str(part) for part in parts).encode("utf-8"),
    ).hexdigest()
    return digest[:16]


@dataclass(frozen=True, slots=True)
class WorkGraph:
    nodes: tuple[WorkNode, ...]
    generation: int

    @property
    def by_id(self) -> dict[str, WorkNode]:
        return {node.node_id: node for node in self.nodes}

    def counts(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for node in self.nodes:
            summary[node.status.value] = summary.get(node.status.value, 0) + 1
        summary["total"] = len(self.nodes)
        return summary

    def ready_media_nodes(self) -> tuple[WorkNode, ...]:
        return tuple(
            node
            for node in self.nodes
            if node.status is WorkNodeStatus.READY
            and node.kind in DISPATCHABLE_KINDS
            and node.command is not None
        )

    def model_required_nodes(self) -> tuple[WorkNode, ...]:
        """Nodes the scheduler cannot progress without a model turn.

        FAILED nodes need parameter changes; GATED nodes whose unmet
        dependencies are not themselves machine-dispatchable need
        structural work (missing prompts, missing bindings).
        """

        by_id = self.by_id
        blocked: list[WorkNode] = []
        for node in self.nodes:
            if node.status is WorkNodeStatus.FAILED:
                blocked.append(node)
                continue
            if node.status is not WorkNodeStatus.GATED:
                continue
            machine_solvable = True
            for miss in node.missing:
                dep = by_id.get(miss)
                if dep is None or dep.kind not in DISPATCHABLE_KINDS:
                    machine_solvable = False
                    break
                if dep.status in (WorkNodeStatus.FAILED,):
                    machine_solvable = False
                    break
            if not machine_solvable:
                blocked.append(node)
        return tuple(blocked)

    def unfinished(self) -> tuple[WorkNode, ...]:
        return tuple(
            node
            for node in self.nodes
            if node.status is not WorkNodeStatus.DONE
        )


def _active_task_index(
    tasks: Sequence[Any],
) -> tuple[dict[tuple[str, str], Any], dict[tuple[str, str], Any]]:
    """Index tasks by (kind, targetRef): active ones and latest failures."""

    active: dict[tuple[str, str], Any] = {}
    failed: dict[tuple[str, str], Any] = {}
    for task in tasks:
        metadata = getattr(task, "metadata", None) or {}
        target = str(
            metadata.get("targetRef")
            or (task.input_refs[0] if task.input_refs else ""),
        )
        if not target:
            continue
        key = (str(task.kind), target)
        if task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
            active[key] = task
        elif task.status is TaskStatus.FAILED:
            existing = failed.get(key)
            if existing is None or task.updated_at > existing.updated_at:
                failed[key] = task
    return active, failed


def _task_error_summary(task: Any) -> str | None:
    error = getattr(task, "error", None)
    if isinstance(error, Mapping) and error.get("message"):
        return str(error["message"])[:200]
    return None


def _variant_status(
    *,
    entity: Any,
    variant: Any,
    active: Mapping[tuple[str, str], Any],
    failed: Mapping[tuple[str, str], Any],
) -> tuple[WorkNodeStatus, Any | None]:
    key = (TaskKind.IMAGE_GENERATION.value, f"asset:{entity.entity_id}")
    task = active.get(key)
    if task is not None and (
        (task.metadata or {}).get("variantId") in (None, variant.variant_id)
    ):
        return WorkNodeStatus.RUNNING, task
    if variant.selected_artifact_version_id:
        return WorkNodeStatus.DONE, None
    failure = failed.get(key)
    if failure is not None and (
        (failure.metadata or {}).get("variantId") in (None, variant.variant_id)
    ):
        return WorkNodeStatus.FAILED, failure
    return WorkNodeStatus.READY, None


def _upstream_missing(
    dep_ids: Iterable[str],
    statuses: Mapping[str, WorkNodeStatus],
) -> tuple[str, ...]:
    return tuple(
        dep for dep in dep_ids if statuses.get(dep) is not WorkNodeStatus.DONE
    )


def _slot_selected(project: Project, slot_id: str) -> str | None:
    slot = project.assets.artifact_slots_by_id.get(slot_id)
    if slot is None:
        return None
    return slot.selected_version_id


def _artifact_is_stale(
    project: Project,
    version_id: str | None,
    upstream_selected: Iterable[str | None],
) -> bool:
    """True when provenance shows an upstream selection changed since.

    Conservative: only flags when the artifact recorded provenance refs
    and an upstream node's *current* selection is absent from them. An
    empty provenance never flags.
    """

    if not version_id:
        return False
    artifact = project.assets.artifact_versions_by_id.get(version_id)
    if artifact is None or not artifact.provenance_refs:
        return False
    provenance = {
        ref.removeprefix("artifact-version:").removeprefix("asset-version:")
        for ref in artifact.provenance_refs
    }
    for selected in upstream_selected:
        if selected and selected not in provenance:
            return True
    return False


def derive_work_graph(  # pylint: disable=too-many-branches,too-many-statements
    project: Project,
    tasks: Sequence[Any] = (),
) -> WorkGraph:
    """Project the production DAG from durable facts. Pure function.

    Deliberately one long node-construction pass: every lane reads the
    same freshly built ``statuses`` map, and splitting it would thread
    half a dozen accumulators through helpers for no clarity gain.
    """

    active, failed = _active_task_index(tasks)
    nodes: list[WorkNode] = []
    statuses: dict[str, WorkNodeStatus] = {}

    def add(node: WorkNode) -> None:
        nodes.append(node)
        statuses[node.node_id] = node.status

    # ---- Lane 1: visual variants ------------------------------------
    for entity_id in project.visual.entities.order:
        entity = project.visual.entities.items[entity_id]
        for variant_id in entity.variants.order:
            variant = entity.variants.items[variant_id]
            status, task = _variant_status(
                entity=entity,
                variant=variant,
                active=active,
                failed=failed,
            )
            node_id = f"visual:{entity_id}:{variant_id}"
            add(
                WorkNode(
                    node_id=node_id,
                    kind="visual",
                    label=f"{entity.name} · {variant_id.split(':')[-1]}",
                    status=status,
                    lane="visual",
                    task_id=getattr(task, "task_id", None),
                    progress=getattr(task, "progress", None),
                    error=(
                        _task_error_summary(task)
                        if status is WorkNodeStatus.FAILED
                        else None
                    ),
                    locator={"page": "assets", "assetId": entity_id},
                    command="GENERATE_ASSET",
                    target_ref=f"asset:{entity_id}",
                    dispatch_arguments={"variantId": variant_id},
                    dispatch_fingerprint=_fingerprint(
                        node_id,
                        variant.prompt,
                        sorted(variant.reference_asset_version_ids),
                        sorted(variant.reference_artifact_version_ids),
                    ),
                ),
            )

    # ---- Lane 2: cast lineups ----------------------------------------
    def _anchor_variant_node(entity: Any) -> str | None:
        if entity.canonical_variant_id:
            return f"visual:{entity.entity_id}:{entity.canonical_variant_id}"
        for variant_id in entity.variants.order:
            return f"visual:{entity.entity_id}:{variant_id}"
        return None

    for lineup_id in project.visual.cast_lineups.order:
        lineup = project.visual.cast_lineups.items[lineup_id]
        deps: list[str] = []
        missing_anchors: list[str] = []
        for ref in lineup.character_refs:
            entity = project.visual.entities.items.get(ref)
            if entity is None:
                continue
            anchor = _anchor_variant_node(entity)
            if anchor is not None:
                deps.append(anchor)
            # Any selected artwork of the entity satisfies the lineup
            # anchor (canonical preferred, fallback accepted) — computed
            # from the entity directly: node ids contain colons and must
            # never be parsed back.
            if not _entity_has_artwork(entity):
                missing_anchors.append(anchor or ref)
        node_id = f"lineup:{lineup_id}"
        key = (TaskKind.IMAGE_GENERATION.value, f"lineup:{lineup_id}")
        task = active.get(key)
        failure = failed.get(key)
        missing = tuple(missing_anchors)
        if task is not None:
            status = WorkNodeStatus.RUNNING
        elif lineup.selected_artifact_version_id:
            status = WorkNodeStatus.DONE
        elif missing:
            status = WorkNodeStatus.GATED
        elif failure is not None:
            status = WorkNodeStatus.FAILED
        else:
            status = WorkNodeStatus.READY
        add(
            WorkNode(
                node_id=node_id,
                kind="lineup",
                label=f"{lineup.name or lineup_id} 阵容图",
                status=status,
                deps=tuple(deps),
                lane="lineup",
                task_id=getattr(task, "task_id", None),
                progress=getattr(task, "progress", None),
                error=(
                    _task_error_summary(failure)
                    if status is WorkNodeStatus.FAILED
                    else None
                ),
                missing=missing,
                locator={"page": "assets"},
                command="GENERATE_CAST_LINEUP_IMAGE",
                target_ref=f"lineup:{lineup_id}",
                dispatch_fingerprint=_fingerprint(
                    node_id,
                    lineup.description,
                    lineup.relative_notes,
                    sorted(
                        selected
                        for selected in (
                            _entity_selected_any(
                                project.visual.entities.items.get(ref),
                            )
                            for ref in lineup.character_refs
                        )
                        if selected
                    ),
                ),
            ),
        )

    # ---- Lanes per element: storyboard -> video ----------------------
    video_node_ids: list[str] = []
    for timeline_id in project.timelines.order:
        timeline = project.timelines.items[timeline_id]
        for element_id, element in timeline.elements_by_id.items():
            creation = element.creation
            if not element.enabled or not isinstance(creation, R2VCreation):
                continue
            lane = f"element:{element_id}"
            label = element.label or element_id

            deps: list[str] = []
            for ref in creation.cast_lineup_refs:
                deps.append(f"lineup:{ref}")
            for entity_id, variant_id in sorted(
                creation.visual_variant_refs.items(),
            ):
                deps.append(f"visual:{entity_id}:{variant_id}")
            # Field run 2026-08-06: the graph marked storyboards READY on
            # explicit variant bindings alone while the execution gate
            # refused them — scene/prop entities referenced by the shots
            # had no artwork yet. The dependency set must mirror
            # visual_design_readiness exactly: every referenced entity,
            # not only the explicitly bound ones.
            gate_missing = _storyboard_gate_dependencies(
                project,
                creation,
                deps,
            )

            storyboard_id = f"storyboard:{element_id}"
            storyboard_slot = _slot_selected(
                project,
                f"element:{element_id}:storyboard",
            )
            key = (TaskKind.IMAGE_GENERATION.value, f"element:{element_id}")
            task = active.get(key)
            failure = failed.get(key)
            missing = (*_upstream_missing(deps, statuses), *gate_missing)
            upstream_selected = _element_upstream_selected(project, creation)
            if task is not None:
                status = WorkNodeStatus.RUNNING
            elif storyboard_slot:
                status = (
                    WorkNodeStatus.STALE
                    if _artifact_is_stale(
                        project,
                        storyboard_slot,
                        upstream_selected,
                    )
                    else WorkNodeStatus.DONE
                )
            elif missing:
                status = WorkNodeStatus.GATED
            elif failure is not None:
                status = WorkNodeStatus.FAILED
            elif not (creation.storyboard_prompt or "").strip():
                # No prompt yet: needs model work, surfaced as GATED with
                # a non-node reason so the completion loop names it.
                status = WorkNodeStatus.GATED
                missing = ("storyboard_prompt 缺失",)
            else:
                status = WorkNodeStatus.READY
            add(
                WorkNode(
                    node_id=storyboard_id,
                    kind="storyboard",
                    label=f"{label} · 分镜",
                    status=status,
                    deps=tuple(deps),
                    lane=lane,
                    task_id=getattr(task, "task_id", None),
                    progress=getattr(task, "progress", None),
                    error=(
                        _task_error_summary(failure)
                        if status is WorkNodeStatus.FAILED
                        else None
                    ),
                    missing=missing,
                    locator={"page": "plan", "elementId": element_id},
                    command="GENERATE_STORYBOARD_IMAGE",
                    target_ref=f"element:{element_id}",
                    dispatch_fingerprint=_fingerprint(
                        storyboard_id,
                        creation.storyboard_prompt,
                        sorted(
                            selected
                            for selected in upstream_selected
                            if selected
                        ),
                    ),
                ),
            )

            video_id = f"video:{element_id}"
            video_slot = _slot_selected(project, f"element:{element_id}:main")
            key = (TaskKind.R2V_GENERATION.value, f"element:{element_id}")
            task = active.get(key)
            failure = failed.get(key)
            storyboard_done = statuses[storyboard_id] in (
                WorkNodeStatus.DONE,
                WorkNodeStatus.STALE,
            )
            if task is not None:
                status = WorkNodeStatus.RUNNING
            elif video_slot:
                status = (
                    WorkNodeStatus.STALE
                    if _artifact_is_stale(
                        project,
                        video_slot,
                        [storyboard_slot],
                    )
                    else WorkNodeStatus.DONE
                )
            elif not storyboard_done:
                status = WorkNodeStatus.GATED
            elif failure is not None:
                status = WorkNodeStatus.FAILED
            else:
                status = WorkNodeStatus.READY
            add(
                WorkNode(
                    node_id=video_id,
                    kind="video",
                    label=f"{label} · 视频",
                    status=status,
                    deps=(storyboard_id,),
                    lane=lane,
                    task_id=getattr(task, "task_id", None),
                    progress=getattr(task, "progress", None),
                    error=(
                        _task_error_summary(failure)
                        if status is WorkNodeStatus.FAILED
                        else None
                    ),
                    missing=((storyboard_id,) if not storyboard_done else ()),
                    locator={"page": "plan", "elementId": element_id},
                    command="GENERATE_R2V_VIDEO",
                    target_ref=f"element:{element_id}",
                    dispatch_fingerprint=_fingerprint(
                        video_id,
                        creation.video_prompt,
                        storyboard_slot,
                    ),
                ),
            )
            video_node_ids.append(video_id)

    # ---- Final compose ------------------------------------------------
    if video_node_ids:
        missing = _upstream_missing(video_node_ids, statuses)
        task = next(
            (
                item
                for (kind, _), item in active.items()
                if kind == TaskKind.COMPOSE.value
            ),
            None,
        )
        final_slot = next(
            (
                slot.selected_version_id
                for slot in project.assets.artifact_slots_by_id.values()
                if slot.kind == "final_video" and slot.selected_version_id
            ),
            None,
        )
        if task is not None:
            status = WorkNodeStatus.RUNNING
        elif final_slot:
            status = WorkNodeStatus.DONE
        elif missing:
            status = WorkNodeStatus.GATED
        else:
            status = WorkNodeStatus.READY
        add(
            WorkNode(
                node_id="compose:final",
                kind="compose",
                label="最终合成",
                status=status,
                deps=tuple(video_node_ids),
                lane="compose",
                task_id=getattr(task, "task_id", None),
                progress=getattr(task, "progress", None),
                missing=missing,
                locator={"page": "plan"},
                # Compose stays model/user-driven for now: not dispatchable.
                command=None,
                target_ref=None,
            ),
        )

    return WorkGraph(nodes=tuple(nodes), generation=project.generation)


def _storyboard_gate_dependencies(
    project: Project,
    creation: R2VCreation,
    deps: list[str],
) -> tuple[str, ...]:
    """Mirror visual_design_readiness for one element's storyboard.

    Machine-dispatchable gaps (unselected required variants) are appended
    to ``deps`` as media node ids the scheduler can solve; model-only
    gaps (undefined variants, missing multi-variant bindings, entities
    with no variants at all — schema invariant: declared variants always
    live in required_variant_ids) come back as plain-text reasons that
    route to the completion resume.
    """

    gate_missing: list[str] = []
    referenced = dict.fromkeys(
        [
            *creation.character_refs,
            *([creation.scene_ref] if creation.scene_ref is not None else []),
            *creation.prop_refs,
        ],
    )
    for ref in referenced:
        entity = project.visual.entities.items.get(ref)
        if entity is None:
            continue
        if not entity.required_variant_ids:
            if entity.selected_artifact_version_id is None:
                gate_missing.append(f"{ref} 尚无使用中视觉产物")
            continue
        for required_id in entity.required_variant_ids:
            variant = entity.variants.items.get(required_id)
            node = f"visual:{ref}:{required_id}"
            if variant is None:
                gate_missing.append(f"{ref}/{required_id} 尚未定义")
            elif variant.selected_artifact_version_id is None:
                if node not in deps:
                    deps.append(node)
        if len(entity.required_variant_ids) > 1 and not (
            creation.visual_variant_refs.get(ref)
        ):
            gate_missing.append(f"{ref} 缺少 variant 绑定")
    return tuple(gate_missing)


def _entity_has_artwork(entity: Any) -> bool:
    """A lineup anchor is satisfied by any selected artwork of the entity."""

    if entity.selected_artifact_version_id:
        return True
    return any(
        variant.selected_artifact_version_id
        for variant in entity.variants.items.values()
    )


def _entity_selected_any(entity: Any) -> str | None:
    if entity is None:
        return None
    if entity.canonical_variant_id:
        variant = entity.variants.items.get(entity.canonical_variant_id)
        if variant is not None and variant.selected_artifact_version_id:
            return variant.selected_artifact_version_id
    for variant in entity.variants.items.values():
        if variant.selected_artifact_version_id:
            return variant.selected_artifact_version_id
    return entity.selected_artifact_version_id


def _element_upstream_selected(
    project: Project,
    creation: R2VCreation,
) -> list[str | None]:
    selected: list[str | None] = []
    for ref in creation.cast_lineup_refs:
        lineup = project.visual.cast_lineups.items.get(ref)
        if lineup is not None:
            selected.append(lineup.selected_artifact_version_id)
    for entity_id, variant_id in creation.visual_variant_refs.items():
        entity = project.visual.entities.items.get(entity_id)
        if entity is None:
            continue
        variant = entity.variants.items.get(variant_id)
        if variant is not None:
            selected.append(variant.selected_artifact_version_id)
    return selected


__all__ = [
    "DISPATCHABLE_KINDS",
    "WorkGraph",
    "WorkNode",
    "WorkNodeStatus",
    "derive_work_graph",
]
