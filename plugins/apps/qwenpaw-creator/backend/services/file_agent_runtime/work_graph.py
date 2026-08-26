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
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

from domain.enums import TaskKind, TaskStatus
from services.project_files.models import (
    ArtifactVersionRenderSource,
    ElementOutputRenderSource,
    Project,
    R2VCreation,
    SourceVersionRenderSource,
)


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
DISPATCHABLE_KINDS = frozenset(
    {"visual", "lineup", "storyboard", "video", "compose"},
)


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


def _resolved_element_version(project: Project, element_id: str) -> str | None:
    """Resolve the version a Timeline Element would read during compose."""

    element = next(
        (
            item
            for timeline in project.timelines.items.values()
            for item in [timeline.elements_by_id.get(element_id)]
            if item is not None
        ),
        None,
    )
    if element is None:
        return None
    source = element.render_source
    if isinstance(source, ElementOutputRenderSource):
        target = next(
            (
                item
                for timeline in project.timelines.items.values()
                for item in [timeline.elements_by_id.get(source.element_id)]
                if item is not None
            ),
            None,
        )
        output = target.outputs.get(source.output_name) if target else None
        slot = (
            project.assets.artifact_slots_by_id.get(output.slot_id)
            if output is not None
            else None
        )
        return slot.selected_version_id if slot is not None else None
    if isinstance(source, ArtifactVersionRenderSource):
        return source.version_id
    if isinstance(source, SourceVersionRenderSource):
        return source.version_id
    # Legacy/in-progress R2V structures may not have render_source bound yet;
    # the deterministic adapter selects their canonical main output.
    if isinstance(element.creation, R2VCreation):
        slot = project.assets.artifact_slots_by_id.get(
            f"element:{element.element_id}:main",
        )
        return slot.selected_version_id if slot is not None else None
    return None


def _final_render_reads_current_versions(
    project: Project,
    version: Any,
) -> bool:
    """Reject a nominally-fresh master whose frozen inputs were superseded."""

    metadata = getattr(version, "metadata", None)
    if not isinstance(metadata, Mapping):
        return True
    selections = metadata.get("sourceSelections")
    if not isinstance(selections, list):
        # Legacy renders lack frozen selections; retain their prior behavior.
        return True
    for item in selections:
        if not isinstance(item, Mapping):
            continue
        source_ref = str(item.get("sourceRef") or "")
        if not source_ref.startswith("element:"):
            continue
        expected = _resolved_element_version(
            project,
            source_ref.removeprefix("element:"),
        )
        if expected is not None and item.get("versionId") != expected:
            return False
    return True


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


def _failure_inputs_changed(
    failure: Any,
    node_id: str,
    fingerprint: str,
) -> bool:
    """True when the parked failure was rendered from different inputs.

    The contract says a FAILED node stays parked *until a prompt or
    upstream selection actually changes* — but the parking check only
    looked at the latest task's status, so a deterministic failure
    (safety rejection) kept the node FAILED forever even after the
    agent rewrote the prompt (field run 2026-08-11: three sanitized
    character anchors were never retried and the project stalled).

    The scheduler dispatches with ``dag-{node_id}-{fingerprint}`` and
    transient retry slots only append a ``:transient-retry-N`` suffix,
    so a parked dag task whose key no longer starts with the node's
    current identity was built from older inputs — the node re-derives
    READY. Agent-dispatched tasks carry no graph identity in their key
    and stay parked.
    """

    key = str(getattr(failure, "idempotency_key", "") or "")
    if not key.startswith("dag-"):
        return False
    return not key.startswith(f"dag-{node_id}-{fingerprint}")


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


def _dialogue_match_key(text: str) -> str:
    return "".join(text.split())


# Speaker prefixes ("老板娘：…" / "Regular: …") and stage directions
# ("（回头）") belong to the shot plan, not to the spoken line itself — the
# prompt naturally rephrases them ("她温和地说：“…”"), so requiring them
# verbatim makes the gate unsatisfiable (field run 2026-08-12, project
# 27dc: three YOLO continuation rounds burned against exactly this).
_DIALOGUE_SPEAKER_PREFIX = re.compile(r"^[^：:]{1,20}[：:]\s*")
_DIALOGUE_STAGE_DIRECTION = re.compile(r"[（(][^）)]*[）)]")


def _dialogue_spoken_lines(dialogue: str) -> tuple[str, ...]:
    """The spoken sentences of a shot's dialogue field, one per line."""
    lines: list[str] = []
    for raw in dialogue.splitlines():
        line = _DIALOGUE_SPEAKER_PREFIX.sub("", raw.strip())
        line = _DIALOGUE_STAGE_DIRECTION.sub("", line).strip()
        if line:
            lines.append(line)
    return tuple(lines)


def _video_prompt_dialogue_gaps(creation: R2VCreation) -> tuple[str, ...]:
    """Shots whose spoken lines never reached the committed video prompt.

    Field run 2026-08-12 (project f5ac): the mainline planned per-shot
    dialogue in the shot list, then committed a two-sentence mood summary
    as ``video_prompt``. The scheduler dispatched that summary verbatim and
    the dialogue never reached the video provider — a silent film with a
    written script. R2V doctrine requires quoting the spoken lines 原文
    inside the video prompt, so the graph enforces it deterministically:
    the video node stays GATED (naming the offending shots) until the
    prompt quotes every planned line. Matching ignores whitespace, speaker
    prefixes and stage directions so natural prompt phrasing never causes
    a false gap.
    """
    prompt = _dialogue_match_key(creation.video_prompt or "")
    gaps: list[str] = []
    for shot_id in creation.shots.order:
        shot = creation.shots.items.get(shot_id)
        if shot is None:
            continue
        for line in _dialogue_spoken_lines(shot.dialogue or ""):
            if _dialogue_match_key(line) not in prompt:
                gaps.append(f"video_prompt 缺台词原文：{shot_id}")
                break
    return tuple(gaps)


def _element_dialogue_density_gap(
    creation: R2VCreation,
    scenario: str,
) -> str | None:
    """Element dialogue density below min_dialogue_ratio — gate the video.

    Field run 2026-08-12 (project 4cd, amodei love story): the story
    theme was "unspoken love" and the model interpreted it as "no one
    speaks anywhere" — 6 elements, 26 shots, only 1 dialogue line.
    The dialogue-coverage gate (_video_prompt_dialogue_gaps) only fires
    when dialogue *exists* and is not quoted; it silently passes when
    shot.dialogue is empty. This gate catches the other failure mode:
    characters appear but the model wrote a silent film.

    The threshold is per-element (``creation.min_dialogue_ratio``,
    default 0.3 ≈ 1 line per 2–3 shots); the review UI may override it
    per element for fine-grained control.

    Exemptions:
    - Non-narrative scenarios (video_edit, general) — no story doctrine.
    - Elements without character_refs — nothing to speak.
    - Elements whose narrative contains the explicit directorial note
      "有意静默" — a deliberate silence choice, not an oversight.
    - min_dialogue_ratio == 0 — the model (or user) explicitly opted out.
    """
    gap: str | None = None
    if (
        scenario == "short_drama"
        and creation.character_refs
        and creation.min_dialogue_ratio > 0
        and "有意静默" not in (creation.narrative or "")
    ):
        shots = [creation.shots.items.get(sid) for sid in creation.shots.order]
        shots = [s for s in shots if s is not None]
        if shots:
            dialogue_count = sum(
                1 for s in shots if (s.dialogue or "").strip()
            )
            ratio = dialogue_count / len(shots)
            if ratio < creation.min_dialogue_ratio:
                gap = (
                    f"element 对白密度 {dialogue_count}/{len(shots)}"
                    f" ({ratio:.0%}) 低于目标"
                    f" {creation.min_dialogue_ratio:.0%}；"
                    "如确需静默请在 narrative 写明「有意静默」"
                    "或将 min_dialogue_ratio 调低"
                )
    return gap


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
            node_id = f"visual:{entity_id}:{variant_id}"
            fingerprint = _fingerprint(
                node_id,
                variant.prompt,
                sorted(variant.reference_asset_version_ids),
                sorted(variant.reference_artifact_version_ids),
            )
            status, task = _variant_status(
                entity=entity,
                variant=variant,
                active=active,
                failed=failed,
            )
            if status is WorkNodeStatus.FAILED and _failure_inputs_changed(
                task,
                node_id,
                fingerprint,
            ):
                status, task = WorkNodeStatus.READY, None
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
                    dispatch_fingerprint=fingerprint,
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
        fingerprint = _fingerprint(
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
        )
        if task is not None:
            status = WorkNodeStatus.RUNNING
        elif lineup.selected_artifact_version_id:
            status = WorkNodeStatus.DONE
        elif missing:
            status = WorkNodeStatus.GATED
        elif failure is not None and not _failure_inputs_changed(
            failure,
            node_id,
            fingerprint,
        ):
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
                dispatch_fingerprint=fingerprint,
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
            # Mirrors the submit path: agent-specified references are
            # authoritative, so they (not the auto chain) must drive the
            # fingerprint and staleness — editing the explicit list has to
            # reopen dispatch and flag a stale artifact.
            storyboard_refs: list[str | None] = (
                list(creation.storyboard_reference_version_ids)
                or upstream_selected
            )
            fingerprint = _fingerprint(
                storyboard_id,
                creation.storyboard_prompt,
                sorted(selected for selected in storyboard_refs if selected),
            )
            if task is not None:
                status = WorkNodeStatus.RUNNING
            elif storyboard_slot:
                status = (
                    WorkNodeStatus.STALE
                    if _artifact_is_stale(
                        project,
                        storyboard_slot,
                        storyboard_refs,
                    )
                    else WorkNodeStatus.DONE
                )
            elif missing:
                status = WorkNodeStatus.GATED
            elif failure is not None and not _failure_inputs_changed(
                failure,
                storyboard_id,
                fingerprint,
            ):
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
                    dispatch_fingerprint=fingerprint,
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
            fingerprint = _fingerprint(
                video_id,
                creation.video_prompt,
                storyboard_slot,
                sorted(creation.video_reference_version_ids),
            )
            video_missing: tuple[str, ...] = ()
            if task is not None:
                status = WorkNodeStatus.RUNNING
            elif video_slot:
                status = (
                    WorkNodeStatus.STALE
                    if _artifact_is_stale(
                        project,
                        video_slot,
                        [
                            storyboard_slot,
                            *creation.video_reference_version_ids,
                        ],
                    )
                    else WorkNodeStatus.DONE
                )
            elif not storyboard_done:
                status = WorkNodeStatus.GATED
                video_missing = (storyboard_id,)
            elif failure is not None and not _failure_inputs_changed(
                failure,
                video_id,
                fingerprint,
            ):
                status = WorkNodeStatus.FAILED
            elif not (creation.video_prompt or "").strip():
                # No prompt yet: model work, mirrored on the storyboard
                # node's "prompt missing" reason so the completion loop
                # names the gap instead of dispatching into a
                # ValidationError.
                status = WorkNodeStatus.GATED
                video_missing = ("video_prompt 缺失",)
            elif dialogue_gaps := _video_prompt_dialogue_gaps(creation):
                # Planned dialogue must be quoted verbatim in the video
                # prompt before dispatch — see _video_prompt_dialogue_gaps.
                status = WorkNodeStatus.GATED
                video_missing = dialogue_gaps
            elif absence_gap := _element_dialogue_density_gap(
                creation,
                project.scenario,
            ):
                # Element dialogue density below min_dialogue_ratio —
                # the model wrote a silent film or too-sparse dialogue.
                # See _element_dialogue_density_gap.
                status = WorkNodeStatus.GATED
                video_missing = (absence_gap,)
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
                    missing=video_missing,
                    locator={"page": "plan", "elementId": element_id},
                    command="GENERATE_R2V_VIDEO",
                    target_ref=f"element:{element_id}",
                    dispatch_fingerprint=fingerprint,
                ),
            )
            video_node_ids.append(video_id)

    # ---- Final compose ------------------------------------------------
    # Any timeline whose main track carries enabled content (R2V, Edit or
    # motion-clip Elements) ends in one deterministic master render. The
    # node is machine-dispatchable so an unattended (delegated) project
    # reaches its final cut without a user pressing "render"; the scene
    # ledger gate mirrors validate_scene_ledger_locked so dispatch never
    # burns a compose the backend door would reject.
    from services.project_files.models import (
        EditCreation,
        MotionClipCreation,
    )

    compose_timeline_id: str | None = None
    for timeline_id in project.timelines.order:
        timeline = project.timelines.items[timeline_id]
        has_content = any(
            element.enabled
            and isinstance(
                element.creation,
                (R2VCreation, EditCreation, MotionClipCreation),
            )
            for element in timeline.elements_by_id.values()
        )
        if has_content:
            compose_timeline_id = timeline_id
            break
    if compose_timeline_id is not None:
        timeline = project.timelines.items[compose_timeline_id]
        missing = _upstream_missing(video_node_ids, statuses)
        scene_gaps: list[str] = []
        plan = getattr(timeline, "edit_plan", None)
        if (
            plan is not None
            and not plan.mechanical_exemption
            and plan.scene_ledger
        ):
            from services.render_review.scene_review import (
                scene_content_fingerprint,
            )

            for row in plan.scene_ledger:
                if row.status != "locked":
                    scene_gaps.append(f"场景未锁定: {row.scene_id}")
                elif row.locked_fingerprint != scene_content_fingerprint(
                    timeline,
                    row,
                ):
                    scene_gaps.append(f"场景锁已过期: {row.scene_id}")
        missing = (*missing, *scene_gaps)
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
        if final_slot is not None:
            # A stale master render (edit impact marked it after content
            # changes) must not read as DONE, or the unattended pipeline
            # would stop one compose short of the corrected final cut.
            version = project.assets.artifact_versions_by_id.get(final_slot)
            if version is not None and (
                getattr(version, "stale", False)
                or not _final_render_reads_current_versions(project, version)
            ):
                final_slot = None
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
                command="COMPOSE_FINAL_VIDEO",
                target_ref=f"timeline:{compose_timeline_id}",
                # The fingerprint must change whenever the rendered output
                # would: spans alone miss re-picked source ranges
                # (render_source), edited overlays/motion documents and
                # regenerated media versions, which previously replayed a
                # stale compose as an idempotent no-op.
                dispatch_fingerprint=_fingerprint(
                    "compose:final",
                    timeline.color_grade,
                    sorted(
                        (
                            element_id,
                            json.dumps(
                                element.model_dump(mode="json"),
                                sort_keys=True,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        )
                        for element_id, element in (
                            timeline.elements_by_id.items()
                        )
                        if element.enabled
                    ),
                    sorted(
                        (slot_id, slot.selected_version_id or "")
                        for slot_id, slot in (
                            project.assets.artifact_slots_by_id.items()
                        )
                        if slot.kind != "final_video"
                    ),
                ),
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

    A multi-character storyboard additionally waits for any *planned*
    lineup covering ≥2 of its characters: the lineup image is the
    pairwise-contrast anchor (relative height/build, kit discriminators),
    and field runs showed identity drift — duplicated jersey numbers —
    exactly when storyboards rendered while the lineup was still absent.
    Projects that plan no lineup are unaffected.

    Declared-but-unselected lineups gate *every* storyboard, not only the
    covering ones: the execution gate
    (assert_visual_design_ready_for_storyboards) is project-wide, and a
    graph that reports READY for a node the executor refuses poisons the
    dispatch ledger before any task record exists. Field run 2026-08-12
    (project 27dc): a single-character closing scene derived READY while
    the counter lineup was pending, its pre-spend dispatch was rejected,
    and the node stalled READY-but-undispatchable for 25 minutes until a
    restart cleared the ledger.
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
        gate_missing.extend(_entity_gate_gaps(entity, ref, creation, deps))
    for lineup_node in _covering_lineup_nodes(project, creation):
        if lineup_node not in deps:
            deps.append(lineup_node)
    for lineup_node in _declared_pending_lineup_nodes(project):
        if lineup_node not in deps:
            deps.append(lineup_node)
    return tuple(gate_missing)


def _entity_gate_gaps(
    entity: Any,
    ref: str,
    creation: R2VCreation,
    deps: list[str],
) -> list[str]:
    """One referenced entity's model-only gaps; dispatchable ones → deps."""

    gaps: list[str] = []
    if not entity.required_variant_ids:
        if entity.selected_artifact_version_id is None:
            gaps.append(f"{ref} 尚无使用中视觉产物")
        return gaps
    for required_id in entity.required_variant_ids:
        variant = entity.variants.items.get(required_id)
        node = f"visual:{ref}:{required_id}"
        if variant is None:
            gaps.append(f"{ref}/{required_id} 尚未定义")
        elif variant.selected_artifact_version_id is None:
            if node not in deps:
                deps.append(node)
    if len(entity.required_variant_ids) > 1 and not (
        creation.visual_variant_refs.get(ref)
    ):
        gaps.append(f"{ref} 缺少 variant 绑定")
    return gaps


def _declared_pending_lineup_nodes(project: Project) -> list[str]:
    """Unselected lineups any enabled element declared, project-wide.

    Mirrors _lineup_readiness_issues exactly: a declared
    ``cast_lineup_refs`` blocks every storyboard in the project until the
    lineup artwork is selected.
    """

    pending: list[str] = []
    for timeline_id in project.timelines.order:
        timeline = project.timelines.items[timeline_id]
        for element in timeline.elements_by_id.values():
            creation = element.creation
            if not element.enabled or not isinstance(creation, R2VCreation):
                continue
            for lineup_ref in creation.cast_lineup_refs:
                lineup = project.visual.cast_lineups.items.get(lineup_ref)
                node = f"lineup:{lineup_ref}"
                if (
                    lineup is None
                    or lineup.selected_artifact_version_id is None
                ) and node not in pending:
                    pending.append(node)
    return pending


def _covering_lineup_nodes(
    project: Project,
    creation: R2VCreation,
) -> list[str]:
    """Planned-but-unselected lineups this storyboard should wait for.

    Explicit ``cast_lineup_refs`` always count; otherwise any planned
    lineup sharing ≥2 characters with the element covers it. Selected
    lineups resolve to DONE nodes and never block.
    """

    if len(creation.character_refs) < 2:
        return []
    element_cast = set(creation.character_refs)
    explicit = set(creation.cast_lineup_refs)
    nodes: list[str] = []
    for lineup_id in project.visual.cast_lineups.order:
        lineup = project.visual.cast_lineups.items[lineup_id]
        covering = lineup_id in explicit or (
            len(element_cast & set(lineup.character_refs)) >= 2
        )
        if covering:
            nodes.append(f"lineup:{lineup_id}")
    return nodes


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
