# -*- coding: utf-8 -*-
"""Explicit mainline requests for existing WorkGraph media nodes.

This is admission for a user-triggered tool call, not an automatic scheduler
mode. It never creates tasks or calls a provider on its own.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from domain.enums import CreatorCommandType, SpecialistRole
from domain.errors import ReviewPendingError
from models.config import get_image_model_name, get_video_model_name
from services.file_agent_runtime.work_graph import (
    WorkNode,
    WorkNodeStatus,
    derive_work_graph,
)
from services.file_agent_runtime.work_scheduler import (
    _blocked_by_active_media_review,
    _blocked_by_active_sync_review,
)
from services.media_files.call_budget import ensure_media_call_budget
from services.media_files.review_admission import assert_media_review_admission
from services.project_files import frontend_edit_hold
from services.project_files.models import ArtifactVersion
from services.specialist_tools import SpecialistToolSpec

REQUEST_WORKGRAPH_EXECUTION = "request_workgraph_execution"
MEDIA_NODE_KINDS = frozenset(
    {"visual", "lineup", "storyboard", "video", "compose"},
)


def request_workgraph_tool_manifest() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": REQUEST_WORKGRAPH_EXECUTION,
            "description": (
                "请求生成当前用户明确要制作的就绪 WorkGraph 媒体目标。"
                "角色/场景/道具用 asset:<entity_id>，阵容用 lineup:<id>，"
                "分镜/视频用 element:<element_id>；本地成片用 timeline:<timeline_id>"
                "并指定 kinds=[compose]。可一次列出多个独立目标；"
                "媒体生成并行提出真实授权请求，用户批准后才执行；本地合成不新增付费授权。"
                "不修改项目、不修改权限、不自动纳入其他目标、不重试失败任务。"
                "用户只要求写剧本/设定或等待确认时不要调用；"
                "需要发起制作请求时调用，以返回的真实任务和产物核实进展。"
                "返回 BLOCKED 且 reason=WAITING_REVIEW 表示本次未启动，"
                "需先完成已有审阅；请求已结束、没有排队或自动续跑。"
                "PARTIAL 须逐项读取 items，不能把阻塞目标说成已提交。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "minLength": 1},
                    "targetRefs": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "maxItems": 32,
                        "uniqueItems": True,
                    },
                    "kinds": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": sorted(MEDIA_NODE_KINDS),
                        },
                        "minItems": 1,
                        "uniqueItems": True,
                    },
                },
                "required": ["projectId", "targetRefs"],
                "additionalProperties": False,
            },
        },
    }


# These reasons are produced before dispatch. An executor exception may have
# happened after admission, so missing taskId alone never proves no task.
_PRE_DISPATCH_BLOCKERS = frozenset(
    {
        "TARGET_NOT_FOUND",
        "WAITING_REVIEW",
        "EDIT_IN_PROGRESS",
        "GATED",
        "READY",
        "STALE",
        "FAILED",
        "UNSUPPORTED_EXECUTION_MODE",
        "SCENE_REVIEW_REQUIRED",
        "MOTION_DESIGN_REQUIRED",
        "MODEL_RENDER_REVIEW_ENABLED",
        "INPUTS_NOT_READY",
        "APPROVED_INPUTS_CHANGED",
    },
)


def workgraph_waits_only_for_review(result: Mapping[str, Any]) -> bool:
    """End the loop only for wholly unstarted, review-blocked requests."""
    items = result.get("items")
    return (
        result.get("status") == "BLOCKED"
        and isinstance(items, list)
        and bool(items)
        and all(
            isinstance(item, Mapping)
            and item.get("status") == "BLOCKED"
            and item.get("reason") == "WAITING_REVIEW"
            and not item.get("taskId")
            for item in items
        )
    )


def summarize_workgraph_results(items: list[dict[str, Any]]) -> str:
    """Public wording from actual per-target results, without internal refs."""
    if not items:
        return "本次没有可执行的制作目标；未创建制作任务，也未加入等待队列。"
    review = sum(
        item.get("status") == "BLOCKED"
        and item.get("reason") == "WAITING_REVIEW"
        and not item.get("taskId")
        for item in items
    )
    known_unstarted = sum(
        item.get("status") == "BLOCKED"
        and item.get("reason") in _PRE_DISPATCH_BLOCKERS
        and not item.get("taskId")
        for item in items
    )
    if known_unstarted == len(items):
        detail = []
        if review:
            detail.append(f"{review} 项需要先完成现有审阅")
        if other := known_unstarted - review:
            detail.append(f"{other} 项制作条件尚未满足")
        return (
            "尚未启动制作："
            + "，".join(detail)
            + "。本次未创建制作任务，也未加入等待队列。"
            + "条件满足后需要重新提出制作请求。"
        )
    task_ids = {
        task_id
        for item in items
        if isinstance(task_id := item.get("taskId"), str) and task_id.strip()
    }
    reused = sum(
        item.get("status") == "SUCCEEDED" and item.get("replayed") is True
        for item in items
    )
    completed = sum(
        item.get("status") == "SUCCEEDED" and item.get("replayed") is not True
        for item in items
    )
    details = [f"本次返回 {len(task_ids)} 个制作任务"] if task_ids else []
    if completed:
        details.append(f"已完成制作 {completed} 项")
    if reused:
        details.append(f"复用已有成果 {reused} 项")
    if review:
        details.append(f"{review} 项等待现有审阅，尚未开始")
    if other := known_unstarted - review:
        details.append(f"{other} 项制作条件尚未满足，尚未开始")
    failed = sum(
        item.get("status") in {"FAILED", "CANCELLED", "QUARANTINED"}
        for item in items
    )
    if failed:
        details.append(f"{failed} 项未能完成")
    unresolved = len(items) - completed - reused - known_unstarted - failed
    if unresolved:
        details.append(f"{unresolved} 项执行结果尚未确认")
    return "；".join(details) + "。"


def parse_request_targets(
    arguments: Mapping[str, Any],
    project_id: str,
) -> tuple[set[str], set[str]]:
    if set(arguments) - {"projectId", "targetRefs", "kinds"}:
        raise ValueError("制作请求包含未知参数")
    if arguments.get("projectId") != project_id:
        raise ValueError("制作请求只能操作当前项目")
    refs = arguments.get("targetRefs")
    if (
        not isinstance(refs, list)
        or not 1 <= len(refs) <= 32
        or any(not isinstance(x, str) or not x.strip() for x in refs)
        or len(set(refs)) != len(refs)
    ):
        raise ValueError("制作请求必须指定 1–32 个不重复的真实目标")
    kinds = arguments.get("kinds", sorted(MEDIA_NODE_KINDS))
    if (
        not isinstance(kinds, list)
        or not kinds
        or any(
            not isinstance(x, str) or x not in MEDIA_NODE_KINDS for x in kinds
        )
    ):
        raise ValueError(
            "制作请求仅支持设计图、阵容图、分镜、视频和本地成片合成",
        )
    return set(refs), set(kinds)


@dataclass(frozen=True)
class RequestedWorkNode:
    node: WorkNode
    snapshot: Any
    fingerprint: str
    parameters: dict[str, Any]
    spec: SpecialistToolSpec
    checkpoint_role: SpecialistRole


# Handle each publication kind without treating media as approved.
# pylint: disable-next=too-many-branches
def _publication_artifacts(review: Any) -> tuple[ArtifactVersion, ...] | None:
    """Recognize complete image-publication reviews, never mixed prose edits.

    ReviewRecord has no media/text discriminator. Its validated artifact
    records identify the exact index entries and output-selection fields a
    publication can change. Every operation must belong to that whitelist.
    Unknown operations remain a project-wide creative review fence.
    """
    operations = getattr(review, "operations", ())
    artifacts = []
    for operation in operations:
        parts = (operation.json_pointer or "").split("/")[1:]
        if len(parts) != 3 or parts[:2] != [
            "assets",
            "artifact_versions_by_id",
        ]:
            continue
        try:
            artifact = ArtifactVersion.model_validate(operation.after)
        except ValueError:
            return None
        if artifact.metadata.get("commandType") not in {
            CreatorCommandType.GENERATE_ASSET.value,
            CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE.value,
        }:
            return None
        artifacts.append(artifact)
    if not artifacts:
        return None

    allowed: set[tuple[str, ...]] = set()
    for artifact in artifacts:
        allowed.update(
            {
                ("assets", "files_by_id", artifact.file_id),
                ("assets", "artifact_versions_by_id", artifact.version_id),
                ("assets", "artifact_slots_by_id", artifact.slot_id),
            },
        )
        if artifact.thumbnail_file_id:
            allowed.add(("assets", "files_by_id", artifact.thumbnail_file_id))
        for leaf in ("candidate_version_ids", "selected_version_id"):
            allowed.add(
                ("assets", "artifact_slots_by_id", artifact.slot_id, leaf),
            )
        owner = artifact.owner_ref
        if owner.startswith("asset:"):
            prefix = ("visual", "entities", "items", owner[6:])
            allowed.add((*prefix, "selected_artifact_version_id"))
            variant = artifact.metadata.get("variantId")
            if isinstance(variant, str) and variant:
                for leaf in (
                    "selected_artifact_version_id",
                    "generated_artifact_version_ids",
                ):
                    allowed.add((*prefix, "variants", "items", variant, leaf))
        elif owner.startswith("lineup:"):
            prefix = ("visual", "cast_lineups", "items", owner[7:])
            for leaf in (
                "selected_artifact_version_id",
                "generated_artifact_version_ids",
            ):
                allowed.add((*prefix, leaf))
        else:
            return None
    for operation in operations:
        pointer = tuple(
            part.replace("~1", "/").replace("~0", "~")
            for part in (operation.json_pointer or "").split("/")[1:]
        )
        if pointer not in allowed or operation.kind not in {
            "create",
            "update",
        }:
            return None
    return tuple(artifacts)


def _design_reference_versions(project: Any, node: WorkNode) -> list[str]:
    if node.kind == "visual":
        entity = project.visual.entities.items.get((node.target_ref or "")[6:])
        variant = (
            entity.variants.items.get(node.dispatch_arguments.get("variantId"))
            if entity
            else None
        )
        if variant is not None:
            return [
                *variant.reference_asset_version_ids,
                *variant.reference_artifact_version_ids,
            ]
    if node.kind == "lineup":
        from services.media_files.image_execution import (
            _lineup_character_reference_ids,
        )

        lineup = project.visual.cast_lineups.items.get(
            (node.target_ref or "")[7:],
        )
        if lineup is not None:
            anchors, _ = _lineup_character_reference_ids(project, lineup)
            return [
                *anchors,
                *lineup.reference_asset_version_ids,
                *lineup.reference_artifact_version_ids,
            ]
    return []


def workgraph_blocking_reviews(
    services: Any,
    project_id: str,
    result: Mapping[str, Any],
) -> list:
    """Join the same review fences used by admission, scoped to this request.

    Creative/mixed reviews and heavy production retain their project fence.
    Independent visual work waits only for its own outputs or input images.
    Run on a worker thread: both snapshot and review discovery read files.
    """
    project = services.projects.read(project_id).project
    graph = derive_work_graph(project)
    requested = {
        item.get("nodeId")
        for item in result.get("items", [])
        if item.get("reason") == "WAITING_REVIEW"
    }
    nodes = [node for node in graph.nodes if node.node_id in requested]
    if not nodes:
        return []
    joined = []
    for review in services.reviews.all_pending(project_id):
        artifacts = _publication_artifacts(review)
        if artifacts is None:
            joined.append(review)
            continue
        slots = frozenset(artifact.slot_id for artifact in artifacts)
        owners = frozenset(artifact.owner_ref for artifact in artifacts)
        for node in nodes:
            if _blocked_by_active_media_review(node, slots, owners):
                joined.append(review)
                break
            if node.kind in {"visual", "lineup"}:
                try:
                    assert_media_review_admission(
                        reviews=[review],
                        command_type=node.command or "",
                        target_ref=node.target_ref or "",
                        reference_version_ids=_design_reference_versions(
                            project,
                            node,
                        ),
                        variant_id=node.dispatch_arguments.get("variantId"),
                    )
                except ReviewPendingError:
                    joined.append(review)
                    break
    return joined


# Freeze each work kind using its actual executor input contract.
# pylint: disable-next=too-many-branches
def requested_work_node(snapshot: Any, node: WorkNode) -> RequestedWorkNode:
    if node.command == CreatorCommandType.GENERATE_S2V_VIDEO.value:
        raise ValueError("数字人口播尚不支持此制作请求入口")
    parameters = dict(node.dispatch_arguments)
    project = snapshot.project
    parameters["aspectRatio"] = project.settings.aspect_ratio
    kind = "image"
    operation = "image_generation"
    role = SpecialistRole.VISUAL_DEVELOPMENT
    authored_inputs: dict[str, Any] = {}
    if node.kind == "compose":
        kind, operation = None, "compose_final_video"
        parameters["resolution"] = project.settings.resolution
        timeline = project.timelines.items.get(node.timeline_id)
        if timeline is not None:
            authored_inputs["timeline"] = timeline.model_dump(mode="json")
    if node.kind == "visual":
        entity = project.visual.entities.items.get(
            (node.target_ref or "").removeprefix("asset:"),
        )
        variant = (
            entity.variants.items.get(parameters.get("variantId"))
            if entity
            else None
        )
        if variant is not None:
            # The graph sorts refs for scheduling identity; provider image
            # blocks preserve their order. Approval must bind that order.
            authored_inputs["variant"] = variant.model_dump(mode="json")
    elif node.kind == "lineup":
        lineup = project.visual.cast_lineups.items.get(
            (node.target_ref or "").removeprefix("lineup:"),
        )
        if lineup is not None:
            authored_inputs["lineup"] = lineup.model_dump(mode="json")
            authored_inputs["characters"] = [
                project.visual.entities.items[ref].model_dump(mode="json")
                for ref in lineup.character_refs
                if ref in project.visual.entities.items
            ]
    if node.kind in {"storyboard", "video"}:
        # Role is only an existing checkpoint policy selector. No legacy
        # Specialist is registered, delegated, or created by this tool.
        role = SpecialistRole.R2V_GENERATION_DIRECTOR
        authored_inputs["visual"] = project.visual.model_dump(mode="json")
        for timeline in project.timelines.items.values():
            element = timeline.elements_by_id.get(
                (node.target_ref or "").removeprefix("element:"),
            )
            if element is not None:
                authored_inputs["element"] = element.model_dump(mode="json")
                authored_inputs["ticksPerSecond"] = timeline.ticks_per_second
                break
    if node.kind == "video":
        kind = "video"
        operation = "r2v_generation"
        parameters["resolution"] = project.settings.resolution
        for timeline in project.timelines.items.values():
            element = timeline.elements_by_id.get(
                (node.target_ref or "").removeprefix("element:"),
            )
            if element is not None:
                parameters["mode"] = element.creation.type
                parameters["durationSeconds"] = (
                    element.span.duration_tick / timeline.ticks_per_second
                )
                break
    if node.regeneration_of:
        authored_inputs["regenerationOf"] = node.regeneration_of
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "node": node.node_id,
                "command": node.command,
                "target": node.target_ref,
                "inputs": node.dispatch_fingerprint,
                "parameters": parameters,
                "authoredInputs": authored_inputs,
                "settings": project.settings.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
    ).hexdigest()
    return RequestedWorkNode(
        node=node,
        snapshot=snapshot,
        fingerprint=fingerprint,
        parameters=parameters,
        spec=SpecialistToolSpec(
            name=operation,
            description="生成当前已就绪的制作目标",
            roles=frozenset(),
            parameters={},
            requires_execution_authorization=node.kind != "compose",
            provider_kind=kind,
        ),
        checkpoint_role=role,
    )


def _local_compose_blocker(project: Any, node: WorkNode) -> str | None:
    """Never turn a local compose request into implicit model assistance."""
    from models.config import is_self_review_enabled
    from services.media_files.motion_design import (
        _is_frame_overlay,
        _is_keyword_overlay,
        _is_trusted_caption_motion,
    )
    from services.render_review.scene_review import (
        collect_scene_review_targets,
    )

    timeline = project.timelines.items.get(node.timeline_id)
    if timeline is None:
        return "TIMELINE_NOT_FOUND"
    stale, drafts = collect_scene_review_targets(timeline)
    if stale or drafts:
        return "SCENE_REVIEW_REQUIRED"
    for element in timeline.elements_by_id.values():
        if not element.enabled:
            continue
        creation = element.creation
        if _is_frame_overlay(element) or (
            getattr(creation, "type", "") == "overlay"
            and (
                getattr(creation, "text", "").strip()
                or _is_keyword_overlay(element)
            )
            and not _is_trusted_caption_motion(
                getattr(creation, "motion", None),
            )
        ):
            return "MOTION_DESIGN_REQUIRED"
    # The local executor can schedule a VLM review after publication.
    # This expressly local entry must not silently start that sidecar.
    if is_self_review_enabled():
        return "MODEL_RENDER_REVIEW_ENABLED"
    return None


async def ready_request_context(
    services: Any,
    executions: Any,
    project_id: str,
    *,
    check_media_budget: bool = True,
):
    """Read the gates for every new request and approved dispatch."""
    from services.run_review import admission
    from services.run_review.media_review import active_media_review_slots

    snapshot, tasks, reviews = await asyncio.gather(
        asyncio.to_thread(services.projects.read, project_id),
        asyncio.to_thread(executions.list_tasks, project_id),
        asyncio.to_thread(services.reviews.all_pending, project_id),
    )
    graph = derive_work_graph(
        snapshot.project,
        tasks=tasks,
        media_models=(get_image_model_name(), get_video_model_name()),
    )
    publications = [_publication_artifacts(review) for review in reviews]
    creative_review_pending = any(items is None for items in publications)
    pending_artifacts = [
        artifact for items in publications if items for artifact in items
    ]
    slots = active_media_review_slots(project_id) | frozenset(
        artifact.slot_id for artifact in pending_artifacts
    )
    owners = frozenset(
        artifact.owner_ref for artifact in pending_artifacts
    ) | frozenset(
        slot.owner_ref
        for slot_id in slots
        if (slot := snapshot.project.assets.artifact_slots_by_id.get(slot_id))
        is not None
    )
    fences = await asyncio.to_thread(
        admission.active_sync_fences,
        services.projects.project_root(project_id) / "runtime" / "run-review",
    )
    blocked: dict[str, str] = {}
    regenerable = {node.node_id for node in graph.regeneration_nodes()}
    for node in graph.nodes:
        if node.command == CreatorCommandType.GENERATE_S2V_VIDEO.value:
            # S2V uses audio duration and its own resolution defaults. Do not
            # authorize it using the unrelated timeline/video project terms.
            blocked[node.node_id] = "UNSUPPORTED_EXECUTION_MODE"
        elif creative_review_pending:
            blocked[node.node_id] = "WAITING_REVIEW"
        elif _blocked_by_active_sync_review(
            node,
            sync_review_pending=bool(fences),
        ) or _blocked_by_active_media_review(node, slots, owners):
            blocked[node.node_id] = "WAITING_REVIEW"
        elif node.target_ref and node.target_ref.startswith("element:"):
            if (
                frontend_edit_hold.hold_remaining(
                    project_id,
                    node.target_ref[8:],
                )
                > 0
            ):
                blocked[node.node_id] = "EDIT_IN_PROGRESS"
        if (
            node.status is not WorkNodeStatus.READY
            and node.node_id not in regenerable
        ) or node.command is None:
            blocked.setdefault(node.node_id, node.status.value.upper())
        if node.kind == "compose" and node.node_id not in blocked:
            reason = _local_compose_blocker(snapshot.project, node)
            if reason:
                blocked[node.node_id] = reason
        if node.kind in {"visual", "lineup"} and node.node_id not in blocked:
            try:
                assert_media_review_admission(
                    reviews=reviews,
                    command_type=node.command or "",
                    target_ref=node.target_ref or "",
                    reference_version_ids=_design_reference_versions(
                        snapshot.project,
                        node,
                    ),
                    variant_id=node.dispatch_arguments.get("variantId"),
                )
            except ReviewPendingError:
                blocked[node.node_id] = "WAITING_REVIEW"
    if check_media_budget:
        await asyncio.to_thread(ensure_media_call_budget, services, project_id)
    return snapshot, tasks, graph, blocked
