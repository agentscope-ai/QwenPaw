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

from domain.enums import CreatorCommandType, TaskKind, TaskStatus
from services.prompt_text import missing_narrative_dialogue
from services.project_files.prompt_sync import prompt_sync_status
from services.project_files.blueprint_readiness import (
    STORY_BEFORE_VISUAL_MESSAGE,
    visual_story_missing,
)
from services.project_files.models import (
    ArtifactVersionRenderSource,
    narrative_timeline_ids,
    ElementOutputRenderSource,
    I2VCreation,
    Project,
    R2VCreation,
    S2VCreation,
    SourceVersionRenderSource,
    T2VCreation,
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
    {
        "script",
        "visual",
        "lineup",
        "storyboard",
        "video",
        "compose",
    },
)


@dataclass(frozen=True, slots=True)
class WorkNode:
    node_id: str
    kind: str  # script|visual|lineup|storyboard|video|compose
    label: str
    status: WorkNodeStatus
    deps: tuple[str, ...] = ()
    lane: str = ""
    # Narrative-node scope (方案 3.2)：script/storyboard/video/compose 节点
    # 归属的 timeline；项目级节点（visual/lineup）为 None。
    timeline_id: str | None = None
    # Actionable context for UI and the completion loop.
    task_id: str | None = None
    progress: float | None = None
    error: str | None = None
    missing: tuple[str, ...] = ()  # unmet dependency node ids / reasons
    # True when every reason in ``missing`` is repairable by rewriting
    # authored Project text (prompt, dialogue). The completion loop returns
    # these in every review mode because the repair costs no media call, so
    # it must not depend on the human-readable wording of ``missing``.
    authored_text_gap: bool = False
    # Derived from the saved prompt provenance; the automatic executor can
    # update hidden shot content before submitting media.
    prompt_sync_required: bool = False
    locator: dict[str, Any] = field(default_factory=dict)
    # Dispatch recipe (command + targetRef) for scheduler / manual retry.
    command: str | None = None
    target_ref: str | None = None
    dispatch_arguments: dict[str, Any] = field(default_factory=dict)
    # Input identity for scheduler idempotency: changes only when the
    # node's prompt or upstream selections change, so a FAILED node is
    # not redispatched until something about its inputs actually moved.
    dispatch_fingerprint: str | None = None
    # Selected obsolete artifact being replaced. This is derived, never a
    # permission flag; it gives regeneration a distinct durable replay slot.
    regeneration_of: str | None = None


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

    def regeneration_nodes(self) -> tuple[WorkNode, ...]:
        """Obsolete outputs with complete inputs, pending execution admission.

        Callers must enforce authorization/review/budget gates. Keeping these
        separate from READY prevents an edit from granting permission itself.
        """
        by_id = self.by_id
        return tuple(
            node
            for node in self.nodes
            if node.status is WorkNodeStatus.STALE
            and node.kind in DISPATCHABLE_KINDS
            and node.command is not None
            and node.regeneration_of is not None
            and not node.missing
            and all(
                dep in by_id and by_id[dep].status is WorkNodeStatus.DONE
                for dep in node.deps
            )
        )

    def model_required_nodes(
        self,
        *,
        automatic_regeneration: bool = False,
    ) -> tuple[WorkNode, ...]:
        """Nodes the scheduler cannot progress without a model turn.

        FAILED nodes need parameter changes; GATED nodes whose unmet
        dependencies are not themselves machine-dispatchable need
        structural work (missing prompts, missing bindings). Authorized
        automatic execution owns complete STALE media; other stale content
        still needs the model to repair or explicitly request generation.
        """

        by_id = self.by_id
        blocked: list[WorkNode] = []
        for node in self.nodes:
            if node.status is WorkNodeStatus.FAILED:
                blocked.append(node)
                continue
            if node.status is WorkNodeStatus.STALE:
                # In authorized unattended execution, complete stale media
                # and their machine-owned dependencies belong to scheduling.
                if (
                    automatic_regeneration
                    and node.regeneration_of
                    and all(
                        miss in by_id
                        and by_id[miss].kind in DISPATCHABLE_KINDS
                        for miss in node.missing
                    )
                ):
                    continue
                blocked.append(node)
                continue
            if node.status is not WorkNodeStatus.GATED:
                continue
            if automatic_regeneration and node.prompt_sync_required:
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


def _legacy_storyboard_task(node_id: str, task: Any) -> bool:
    return bool(
        task is not None
        and node_id.startswith("storyboard:")
        and (getattr(task, "metadata", {}) or {}).get(
            "storyboardInputContract",
        )
        != 2,
    )


def _failure_inputs_changed(
    failure: Any,
    node_id: str,
    fingerprint: str,
    media_models: tuple[str, str] | None = None,
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

    if _legacy_storyboard_task(node_id, failure):
        return False
    key = str(getattr(failure, "idempotency_key", "") or "")
    return _dispatch_inputs_changed(
        key,
        node_id,
        fingerprint,
        media_models,
    )


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


# Ledger fingerprints used to interpolate the configured model names in
# plaintext, separated by "|". Those keys cannot be compared against today's
# digest form, and reading the mismatch as drift would flip every artifact
# rendered before the upgrade from DONE to READY — re-billing the user for
# storyboards they had already accepted, and replacing them.
_LEGACY_LEDGER_KEY_MARKER = "|img:"


def dispatch_key_predates_digest_ledger(key: str) -> bool:
    """Whether a durable idempotency key predates the digest ledger format."""

    return _LEGACY_LEDGER_KEY_MARKER in key


def dispatch_ledger_fingerprint(
    base: str,
    media_models: tuple[str, str],
) -> str:
    """Pure input/model identity shared by admission and graph projection."""
    models = hashlib.sha256(
        "\x1f".join(model.strip() for model in media_models).encode("utf-8"),
    ).hexdigest()[:16]
    return f"{base}-m{models}"


def dispatch_slot(fingerprint: str) -> str:
    """Filesystem-safe durable slot for a dispatch ledger identity."""
    base, separator, regeneration = fingerprint.partition("-regen-")
    slot = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    return f"{slot}-regen-{regeneration}" if separator else slot


def _dispatch_inputs_changed(
    key: str,
    node_id: str,
    fingerprint: str,
    media_models: tuple[str, str] | None,
) -> bool:
    prefix = f"dag-{node_id}-"
    if not key.startswith(prefix) or dispatch_key_predates_digest_ledger(key):
        return False
    # The original format stored the node digest, then base + model digest;
    # current dispatches store SHA256(base + model digest). Strip only the
    # documented retry suffix; arbitrary prefix matches hide real changes.
    identity = re.sub(
        r"(?:-regen-[a-f0-9]{16})?(?::transient-retry-\d+|-r\d+)?$",
        "",
        key.removeprefix(prefix),
    )
    if identity == fingerprint:
        return False
    if media_models is None:
        # A bare 16-hex value may be either an old node digest or today's
        # opaque dispatch slot. Without model context a mismatch proves
        # nothing; retain the artifact/failure. Production supplies models.
        if re.fullmatch(r"[a-f0-9]{16}(?:-m[a-f0-9]{16})?", identity):
            return False
        return True
    ledger = dispatch_ledger_fingerprint(fingerprint, media_models)
    return identity not in {ledger, dispatch_slot(ledger)}


def _artifact_is_stale(
    project: Project,
    version_id: str | None,
    upstream_selected: Iterable[str | None],
    *,
    node_id: str = "",
    dispatch_fingerprint: str = "",
    tasks: Sequence[Any] = (),
    media_models: tuple[str, str] | None = None,
) -> bool:
    """True when provenance or an automatic dispatch input changed since.

    An explicit lifecycle ``stale`` flag is authoritative for every artifact,
    including manual ones, but returns the STALE state rather than a
    scheduler-dispatchable READY state. Otherwise this is conservative: it
    only flags recorded provenance mismatches. For scheduler-owned artifacts,
    the durable Task idempotency key also records the work-graph fingerprint;
    this catches prompt/aspect/panel-count changes that do not appear in media
    provenance. Agent/manual artifacts without a graph identity remain
    conservative instead of being invalidated by a guessed fingerprint.
    """

    if not version_id:
        return False
    artifact = project.assets.artifact_versions_by_id.get(version_id)
    if artifact is None:
        return False
    if artifact.stale:
        # STALE is intentionally excluded from ready_media_nodes(). This is a
        # visible review signal, never permission to regenerate manual media.
        return True
    if artifact.provenance_refs:
        provenance = {
            ref.removeprefix("artifact-version:").removeprefix(
                "asset-version:",
            )
            for ref in artifact.provenance_refs
        }
        # The model's reference budget can force a reference out of the
        # automatic chain. It is absent from provenance by design, so treating
        # it as drift would mark the artifact stale for good.
        budget_dropped = {
            str(item)
            for item in (
                artifact.metadata.get("budgetDroppedReferenceVersionIds") or ()
            )
        }
        for selected in upstream_selected:
            if (
                selected
                and selected not in provenance
                and selected not in budget_dropped
            ):
                return True
    if node_id and dispatch_fingerprint:
        task_id = str(artifact.metadata.get("taskId") or "")
        task = next(
            (
                candidate
                for candidate in tasks
                if str(getattr(candidate, "task_id", "")) == task_id
            ),
            None,
        )
        key = str(getattr(task, "idempotency_key", "") or "")
        # Retired hashes alone cannot invalidate a completed artifact.
        if not _legacy_storyboard_task(
            node_id,
            task,
        ) and _dispatch_inputs_changed(
            key,
            node_id,
            dispatch_fingerprint,
            media_models,
        ):
            return True
    return False


def derive_work_graph(  # pylint: disable=too-many-branches,too-many-statements
    project: Project,
    tasks: Sequence[Any] = (),
    *,
    media_models: tuple[str, str] | None = None,
) -> WorkGraph:
    """Project the production DAG from durable facts. Pure function.

    Deliberately one long node-construction pass: every lane reads the
    same freshly built ``statuses`` map, and splitting it would thread
    half a dozen accumulators through helpers for no clarity gain.
    """

    active, failed = _active_task_index(tasks)
    prompt_sync_document = project.model_dump(mode="json")
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
                media_models,
            ):
                status, task = WorkNodeStatus.READY, None
            missing: tuple[str, ...] = ()
            authored_text_gap = False
            if status is WorkNodeStatus.READY and visual_story_missing(
                project,
                entity_id,
            ):
                status = WorkNodeStatus.GATED
                missing = (STORY_BEFORE_VISUAL_MESSAGE,)
                authored_text_gap = True
            if (
                status is WorkNodeStatus.READY
                and not (variant.prompt or "").strip()
            ):
                # Entity descriptions are continuity facts, not production
                # prompts.  Dispatching their one-line fallback caused real
                # qwen-image jobs to race ahead of visual development during
                # a 60-second acceptance run (2026-08-24).  Keep the node in
                # the model-required lane until the committed Variant owns a
                # deliberate prompt, just as storyboards already do.
                status = WorkNodeStatus.GATED
                missing = ("visual_prompt 缺失",)
                authored_text_gap = True
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
                    missing=missing,
                    authored_text_gap=authored_text_gap,
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
            media_models,
        ):
            status = WorkNodeStatus.FAILED
        else:
            status = WorkNodeStatus.READY
        story_missing = any(
            visual_story_missing(project, ref) for ref in lineup.character_refs
        )
        if status is WorkNodeStatus.READY and story_missing:
            status = WorkNodeStatus.GATED
            missing = (STORY_BEFORE_VISUAL_MESSAGE,)
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
                authored_text_gap=story_missing
                and status is WorkNodeStatus.GATED,
                locator={"page": "assets"},
                command="GENERATE_CAST_LINEUP_IMAGE",
                target_ref=f"lineup:{lineup_id}",
                dispatch_fingerprint=fingerprint,
            ),
        )

    # ---- Lane: timeline scripts (blueprint script flow) ---------------
    # 每条 timeline 一个 kind="script" 节点：slot 无版本→READY，selected
    # 版本存在且未 stale→DONE，版本 stale→STALE。剧本流仅在项目启用时
    # 生效（存在 timeline_script slot 或多 timeline）；旧项目（单
    # timeline 且无 script slot）不生成 script 节点，行为零回退。
    live_timeline_ids = narrative_timeline_ids(project)
    script_flow = len(live_timeline_ids) > 1
    script_node_by_timeline: dict[str, str] = {}
    for timeline_id in live_timeline_ids:
        timeline = project.timelines.items[timeline_id]
        slot = project.assets.artifact_slots_by_id.get(
            f"script:{timeline_id}",
        )
        if slot is None and not script_flow:
            continue
        node_id = f"script:{timeline_id}"
        selected = slot.selected_version_id if slot is not None else None
        version = (
            project.assets.artifact_versions_by_id.get(selected)
            if selected
            else None
        )
        key = (TaskKind.SCRIPT_DRAFT.value, f"timeline:{timeline_id}")
        task = active.get(key)
        failure = failed.get(key)
        fingerprint = _fingerprint(
            node_id,
            timeline.title,
            timeline.synopsis,
            project.strategy.creative_brief,
        )
        if task is not None:
            status = WorkNodeStatus.RUNNING
        elif version is not None:
            status = (
                WorkNodeStatus.STALE if version.stale else WorkNodeStatus.DONE
            )
        elif failure is not None and not _failure_inputs_changed(
            failure,
            node_id,
            fingerprint,
            media_models,
        ):
            status = WorkNodeStatus.FAILED
        else:
            status = WorkNodeStatus.READY
        add(
            WorkNode(
                node_id=node_id,
                kind="script",
                label=f"{timeline.title or timeline_id} · 剧本",
                status=status,
                lane=timeline.title or f"timeline:{timeline_id}",
                timeline_id=timeline_id,
                task_id=getattr(task, "task_id", None),
                progress=getattr(task, "progress", None),
                error=(
                    _task_error_summary(failure)
                    if status is WorkNodeStatus.FAILED
                    else None
                ),
                locator={"page": "blueprint", "timelineId": timeline_id},
                command="GENERATE_TIMELINE_SCRIPT",
                target_ref=f"timeline:{timeline_id}",
                dispatch_fingerprint=fingerprint,
            ),
        )
        script_node_by_timeline[timeline_id] = node_id

    # ---- Lanes per element: storyboard -> video ----------------------
    video_nodes_by_timeline: dict[str, list[str]] = {}
    for timeline_id in live_timeline_ids:
        video_node_ids = video_nodes_by_timeline.setdefault(timeline_id, [])
        timeline = project.timelines.items[timeline_id]
        script_node = script_node_by_timeline.get(timeline_id)
        for element_id, element in timeline.elements_by_id.items():
            creation = element.creation
            if not element.enabled:
                continue
            if not isinstance(
                creation,
                (R2VCreation, T2VCreation, I2VCreation, S2VCreation),
            ):
                continue
            lane = f"element:{element_id}"
            label = element.label or element_id
            creation_type = getattr(creation, "type", "r2v")
            prompt_sync_gap = None
            if creation_type == "r2v" and not element_id.startswith(
                "snapshot:",
            ):
                sync = prompt_sync_status(
                    prompt_sync_document,
                    timeline_id,
                    element_id,
                )
                if sync["status"] in ("needs_update", "needs_confirmation"):
                    prompt_sync_gap = "镜头与提示词待同步或待审阅确认"

            storyboard_id: str | None = None
            storyboard_slot: str | None = None

            if creation_type == "r2v":
                # R2V: storyboard + video dual-node structure; only r2v
                # elements produce a storyboard (T2V/I2V/S2V creations carry
                # no shots, storyboard prompt or reference stacks).
                deps: list[str] = []
                # 剧本流下分镜等待本 timeline 的剧本节点（方案 3.3：
                # script 通过 → 该 timeline 的内容/分镜/生成）。
                if script_node is not None:
                    deps.append(script_node)
                for ref in creation.cast_lineup_refs:
                    deps.append(f"lineup:{ref}")
                for entity_id, variant_id in sorted(
                    creation.visual_variant_refs.items(),
                ):
                    deps.append(f"visual:{entity_id}:{variant_id}")
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
                key = (
                    TaskKind.IMAGE_GENERATION.value,
                    f"element:{element_id}",
                )
                task = active.get(key)
                failure = failed.get(key)
                missing = (*_upstream_missing(deps, statuses), *gate_missing)
                authored_text_gap = False
                upstream_selected = _element_upstream_selected(
                    project,
                    creation,
                )
                # Mirrors the submit path: agent-specified references are
                # authoritative, so they (not the auto chain) must drive the
                # fingerprint and staleness — editing the explicit list has
                # to reopen dispatch and flag a stale artifact.
                storyboard_refs: list[str | None] = (
                    list(
                        creation.storyboard_reference_version_ids,
                    )
                    or upstream_selected
                )
                fingerprint = _fingerprint(
                    storyboard_id,
                    creation.storyboard_prompt,
                    project.settings.aspect_ratio,
                    "narrative-v1",
                    sorted(
                        selected for selected in storyboard_refs if selected
                    ),
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
                            node_id=storyboard_id,
                            dispatch_fingerprint=fingerprint,
                            tasks=tasks,
                            media_models=media_models,
                        )
                        else WorkNodeStatus.DONE
                    )
                elif missing:
                    status = WorkNodeStatus.GATED
                elif failure is not None and not _failure_inputs_changed(
                    failure,
                    storyboard_id,
                    fingerprint,
                    media_models,
                ):
                    status = WorkNodeStatus.FAILED
                elif not (creation.storyboard_prompt or "").strip():
                    # No prompt yet: needs model work, surfaced as GATED with
                    # a non-node reason so the completion loop names it.
                    status = WorkNodeStatus.GATED
                    missing = ("storyboard_prompt 缺失",)
                    authored_text_gap = True
                else:
                    status = WorkNodeStatus.READY
                if status is WorkNodeStatus.STALE:
                    if not (creation.storyboard_prompt or "").strip():
                        status = WorkNodeStatus.GATED
                        missing = (*missing, "storyboard_prompt 缺失")
                        authored_text_gap = True
                    elif (
                        not missing
                        and failure is not None
                        and not _failure_inputs_changed(
                            failure,
                            storyboard_id,
                            fingerprint,
                            media_models,
                        )
                    ):
                        status = WorkNodeStatus.FAILED
                if prompt_sync_gap and task is None:
                    status = WorkNodeStatus.GATED
                    missing = (prompt_sync_gap,)
                    authored_text_gap = True
                add(
                    WorkNode(
                        node_id=storyboard_id,
                        kind="storyboard",
                        label=f"{label} · 分镜",
                        status=status,
                        deps=tuple(deps),
                        lane=lane,
                        timeline_id=timeline_id,
                        task_id=getattr(task, "task_id", None),
                        progress=getattr(task, "progress", None),
                        error=(
                            _task_error_summary(failure)
                            if status is WorkNodeStatus.FAILED
                            else None
                        ),
                        missing=missing,
                        authored_text_gap=authored_text_gap,
                        prompt_sync_required=bool(prompt_sync_gap),
                        locator={"page": "plan", "elementId": element_id},
                        command="GENERATE_STORYBOARD_IMAGE",
                        target_ref=f"element:{element_id}",
                        dispatch_fingerprint=fingerprint,
                        regeneration_of=(
                            storyboard_slot
                            if status
                            in (WorkNodeStatus.STALE, WorkNodeStatus.FAILED)
                            else None
                        ),
                    ),
                )

            # Video node for all types
            video_id = f"video:{element_id}"
            video_slot = _slot_selected(project, f"element:{element_id}:main")
            key = (TaskKind.R2V_GENERATION.value, f"element:{element_id}")
            task = active.get(key)
            failure = failed.get(key)

            # Determine storyboard dependency and upstream refs
            storyboard_done = True
            storyboard_dep: tuple[str, ...] = ()
            if creation_type == "r2v" and storyboard_id is not None:
                storyboard_done = (
                    statuses[storyboard_id] is WorkNodeStatus.DONE
                )
                storyboard_dep = (storyboard_id,)
            upstream_selected = _video_upstream_refs(
                creation_type,
                creation,
                project,
            )

            # Fingerprint based on creation type
            fingerprint = _fingerprint(
                *_video_fingerprint_parts(
                    creation_type,
                    creation,
                    video_id,
                    storyboard_slot,
                ),
            )

            video_missing: tuple[str, ...] = ()
            video_text_gap = False
            if task is not None:
                status = WorkNodeStatus.RUNNING
            elif creation_type in {"i2v", "s2v"} and (
                input_gaps := _video_readiness_gates(
                    creation_type,
                    creation,
                )
            ):
                # Removing a required input is an unfinished revision even
                # when an old clip remains selected. Empty upstream refs
                # cannot prove that clip current or authorize a new compose.
                status = WorkNodeStatus.GATED
                video_missing = input_gaps
            elif video_slot:
                # T2V has no upstream references (upstream_selected is []),
                # so _artifact_is_stale always returns False for T2V.
                # Prompt-only changes are caught by the dispatch fingerprint
                # for failure-parking, but do NOT trigger STALE re-generation.
                upstream_for_stale = (
                    [storyboard_slot]
                    if creation_type == "r2v"
                    else upstream_selected
                )
                status = (
                    WorkNodeStatus.STALE
                    if _artifact_is_stale(
                        project,
                        video_slot,
                        upstream_for_stale,
                    )
                    else WorkNodeStatus.DONE
                )
            elif not storyboard_done:
                status = WorkNodeStatus.GATED
                video_missing = (storyboard_id,) if storyboard_id else ()
            elif failure is not None and not _failure_inputs_changed(
                failure,
                video_id,
                fingerprint,
                media_models,
            ):
                status = WorkNodeStatus.FAILED
            elif (
                creation_type != "s2v"
                and not (creation.video_prompt or "").strip()
            ):
                # S2V uses script, not video_prompt
                status = WorkNodeStatus.GATED
                video_missing = ("video_prompt 缺失",)
                video_text_gap = True
            else:
                gates = _video_readiness_gates(
                    creation_type,
                    creation,
                )
                if gates is not None:
                    status = WorkNodeStatus.GATED
                    video_missing = gates
                    # S2V/I2V gates identify missing asset inputs.
                else:
                    status = WorkNodeStatus.READY

            if status is WorkNodeStatus.STALE:
                video_missing = _upstream_missing(
                    (*deps, *storyboard_dep),
                    statuses,
                )
                if (
                    creation_type != "s2v"
                    and not (creation.video_prompt or "").strip()
                ):
                    status = WorkNodeStatus.GATED
                    video_missing = (*video_missing, "video_prompt 缺失")
                    video_text_gap = True
                else:
                    gates = _video_readiness_gates(
                        creation_type,
                        creation,
                    )
                    if gates:
                        status = WorkNodeStatus.GATED
                        video_missing = (*video_missing, *gates)
                    elif (
                        not video_missing
                        and failure is not None
                        and not _failure_inputs_changed(
                            failure,
                            video_id,
                            fingerprint,
                            media_models,
                        )
                    ):
                        status = WorkNodeStatus.FAILED

            # Command and dispatch arguments based on creation type
            if prompt_sync_gap and task is None:
                status = WorkNodeStatus.GATED
                video_missing = (prompt_sync_gap,)
                video_text_gap = True
            if (
                task is None
                and status in {WorkNodeStatus.READY, WorkNodeStatus.STALE}
                and isinstance(creation, R2VCreation)
                and missing_narrative_dialogue(
                    creation.narrative,
                    creation.video_prompt,
                )
            ):
                status = WorkNodeStatus.GATED
                video_missing = (*video_missing, "视频提示词遗漏了片段内容中的对白或旁白原文")
                video_text_gap = True
            command, dispatch_arguments = _video_dispatch_command(
                creation_type,
            )

            add(
                WorkNode(
                    node_id=video_id,
                    kind="video",
                    label=f"{label} · 视频",
                    status=status,
                    deps=(
                        (script_node, *storyboard_dep)
                        if script_node is not None
                        else storyboard_dep
                    ),
                    lane=lane,
                    timeline_id=timeline_id,
                    task_id=getattr(task, "task_id", None),
                    progress=getattr(task, "progress", None),
                    error=(
                        _task_error_summary(failure)
                        if status is WorkNodeStatus.FAILED
                        else None
                    ),
                    missing=video_missing,
                    authored_text_gap=video_text_gap,
                    prompt_sync_required=bool(prompt_sync_gap),
                    locator={"page": "plan", "elementId": element_id},
                    command=command,
                    target_ref=f"element:{element_id}",
                    dispatch_arguments=dispatch_arguments,
                    dispatch_fingerprint=fingerprint,
                    regeneration_of=(
                        video_slot
                        if status
                        in (WorkNodeStatus.STALE, WorkNodeStatus.FAILED)
                        else None
                    ),
                ),
            )
            video_node_ids.append(video_id)

    # ---- Final compose (one node per content-bearing timeline) ---------
    # Each timeline whose main track carries enabled content (R2V, T2V, I2V,
    # S2V, Edit or motion-clip Elements) gets its own deterministic master
    # render. The node is machine-dispatchable so an unattended (delegated)
    # project reaches its final cut without a user pressing "render"; the
    # scene ledger gate mirrors validate_scene_ledger_locked so dispatch
    # never burns a compose the backend door would reject.
    from services.project_files.models import (
        EditCreation,
        MotionClipCreation,
    )

    def _timeline_has_content(tid: str) -> bool:
        tl = project.timelines.items[tid]
        return any(
            element.enabled
            and isinstance(
                element.creation,
                (
                    R2VCreation,
                    T2VCreation,
                    I2VCreation,
                    S2VCreation,
                    EditCreation,
                    MotionClipCreation,
                ),
            )
            for element in tl.elements_by_id.values()
        )

    for compose_timeline_id in (
        tid for tid in live_timeline_ids if _timeline_has_content(tid)
    ):
        timeline = project.timelines.items[compose_timeline_id]
        node_id = f"compose:{compose_timeline_id}"
        timeline_target = f"timeline:{compose_timeline_id}"
        timeline_render_slot_id = f"timeline:{compose_timeline_id}:render"
        # A timeline render reads this timeline's enabled clips. Other
        # episodes may still be generating without blocking this final cut.
        video_node_ids = video_nodes_by_timeline[compose_timeline_id]
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
                and str(
                    item.metadata.get("targetRef") or "",
                )
                == timeline_target
            ),
            None,
        )
        final_slot = next(
            (
                slot.selected_version_id
                for slot_id, slot in (
                    project.assets.artifact_slots_by_id.items()
                )
                if slot.kind == "final_video"
                and slot.selected_version_id
                and slot_id == timeline_render_slot_id
            ),
            None,
        )
        if final_slot is not None:
            version = project.assets.artifact_versions_by_id.get(final_slot)
            if version is not None and (
                getattr(version, "stale", False)
                or not _final_render_reads_current_versions(project, version)
            ):
                final_slot = None
        if task is not None:
            status = WorkNodeStatus.RUNNING
        elif missing:
            status = WorkNodeStatus.GATED
        elif final_slot:
            status = WorkNodeStatus.DONE
        else:
            status = WorkNodeStatus.READY
        add(
            WorkNode(
                node_id=node_id,
                kind="compose",
                label=f"最终合成 ({timeline.name or compose_timeline_id})",
                status=status,
                deps=tuple(video_node_ids),
                lane="compose",
                timeline_id=compose_timeline_id,
                task_id=getattr(task, "task_id", None),
                progress=getattr(task, "progress", None),
                missing=missing,
                locator={"page": "plan"},
                command="COMPOSE_FINAL_VIDEO",
                target_ref=timeline_target,
                dispatch_fingerprint=_fingerprint(
                    node_id,
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
    for timeline_id in narrative_timeline_ids(project):
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


def _video_fingerprint_parts(
    creation_type: str,
    creation: R2VCreation | T2VCreation | I2VCreation | S2VCreation,
    video_id: str,
    storyboard_slot: str | None,
) -> tuple:
    """Return the fingerprint components for a video node by creation type."""
    if creation_type == "t2v":
        return (video_id, creation.video_prompt)
    if creation_type == "i2v":
        return (
            video_id,
            creation.video_prompt,
            creation.first_frame_version_id,
        )
    if creation_type == "s2v":
        return (
            video_id,
            creation.script,
            creation.portrait_version_id,
            creation.audio_version_id,
        )
    # R2V
    assert isinstance(creation, R2VCreation)
    return (
        video_id,
        creation.video_prompt,
        storyboard_slot,
        sorted(creation.video_reference_version_ids),
    )


def _video_upstream_refs(
    creation_type: str,
    creation: R2VCreation | T2VCreation | I2VCreation | S2VCreation,
    project: Project,
) -> list[str]:
    """Return upstream version ids for staleness check by creation type.

    Returns a list of non-None version ids that this node depends on.
    Missing ids are excluded (not returned as None).
    """
    if creation_type == "r2v":
        assert isinstance(creation, R2VCreation)
        return [
            ref
            for ref in _element_upstream_selected(project, creation)
            if ref is not None
        ]
    if creation_type == "i2v":
        assert isinstance(creation, I2VCreation)
        return (
            [creation.first_frame_version_id]
            if creation.first_frame_version_id
            else []
        )
    if creation_type == "s2v":
        assert isinstance(creation, S2VCreation)
        refs: list[str] = []
        if creation.portrait_version_id:
            refs.append(creation.portrait_version_id)
        if creation.audio_version_id:
            refs.append(creation.audio_version_id)
        return refs
    return []


def _video_readiness_gates(
    creation_type: str,
    creation: R2VCreation | T2VCreation | I2VCreation | S2VCreation,
) -> tuple[str, ...] | None:
    """Return missing reasons if the video node is gated, else None.

    Note: T2V's video_prompt check is handled by the caller before invoking
    this function. This function only checks additional gates beyond the
    prompt requirement.
    """
    if creation_type == "s2v":
        assert isinstance(creation, S2VCreation)
        gaps: list[str] = []
        if not creation.portrait_version_id:
            gaps.append("portrait_version_id 缺失")
        if not creation.audio_version_id:
            gaps.append("audio_version_id 缺失")
        return tuple(gaps) if gaps else None
    if creation_type == "i2v":
        assert isinstance(creation, I2VCreation)
        if not creation.first_frame_version_id:
            return ("first_frame_version_id 缺失",)
    # t2v: no extra gates beyond video_prompt (checked by caller)
    return None


def _video_dispatch_command(
    creation_type: str,
) -> tuple[str, dict[str, Any]]:
    """Return (command, dispatch_arguments) for a video node."""
    if creation_type == "s2v":
        return CreatorCommandType.GENERATE_S2V_VIDEO.value, {}
    if creation_type == "t2v":
        return CreatorCommandType.GENERATE_R2V_VIDEO.value, {"mode": "t2v"}
    if creation_type == "i2v":
        return CreatorCommandType.GENERATE_R2V_VIDEO.value, {"mode": "i2v"}
    return CreatorCommandType.GENERATE_R2V_VIDEO.value, {}


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
