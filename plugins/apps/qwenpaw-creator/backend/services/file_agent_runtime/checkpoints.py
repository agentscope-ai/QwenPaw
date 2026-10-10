# -*- coding: utf-8 -*-
"""Checkpoints for reviewable creative deliverables.

The old generic plan phase had no independent document to review. It is
retired, including pending records, without granting any media spending
authorization. Structure, script and design reviews retain their gates.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from domain.enums import SpecialistRole

CHECKPOINT_PLAN = "plan"
CHECKPOINT_DESIGN = "design"
CHECKPOINT_DIRECTION = "direction"
# Blueprint ladder (方案 3.1)：多集项目在生成开始前先确认叙事结构
# （timelines），再逐节点审阅剧本 artifact。
CHECKPOINT_STRUCTURE = "structure"
CHECKPOINT_SCRIPT = "script"

CHECKPOINT_OPERATION_PREFIX = "creation_checkpoint"
CHECKPOINT_PROVIDER = "creator-checkpoint"

_CHECKPOINT_SUMMARIES = {
    CHECKPOINT_STRUCTURE: (
        "结构检查点：确认分集结构（各集标题与梗概）之后再" "起草剧本与生成媒体。通过后本项目不再重复询问。"
    ),
    CHECKPOINT_SCRIPT: (
        "剧本检查点：确认各集剧本草稿之后再进入设计与分镜，" "文本阶段修改的成本远低于媒体阶段。通过后本项目不再重复询问。"
    ),
    CHECKPOINT_PLAN: (
        "计划检查点：确认分镜切分、镜头与各 Element 的 prompt 之后再开始生成。" "通过后本项目不再重复询问。"
    ),
    CHECKPOINT_DESIGN: (
        "设计检查点：确认角色/场景设计图之后再生成分镜图与视频，" "避免用错误的形象继续往下做。通过后本项目不再重复询问。"
    ),
    CHECKPOINT_DIRECTION: ("方向检查点：共创模式下剪辑开始前先确认创作方向（三选一）。" "选定后本项目不再重复询问。"),
}

_CHECKPOINT_LABELS = {
    CHECKPOINT_STRUCTURE: "结构确认",
    CHECKPOINT_SCRIPT: "剧本确认",
    CHECKPOINT_PLAN: "计划确认",
    CHECKPOINT_DESIGN: "设计确认",
    CHECKPOINT_DIRECTION: "方向确认",
}


def required_checkpoint_phases(  # pylint: disable=too-many-return-statements  # noqa: E501
    tool_name: str,
    role: SpecialistRole,
    *,
    timeline_count: int | None = None,
) -> tuple[str, ...]:
    """Return reviews of actual deliverables; billing is a separate gate.

    Design images cannot wait for their own review. Multi-episode visual
    design retains structure review in co_creation and fine_tuning;
    storyboard/video retain structure/script/design only in co_creation.
    Delegated execution has no creation checkpoints.
    """

    from models.config import (
        EXECUTION_MODE_DELEGATED,
        EXECUTION_MODE_FINE_TUNING,
        get_execution_mode,
    )

    execution_mode = get_execution_mode()
    if execution_mode == EXECUTION_MODE_DELEGATED:
        return ()
    script_flow = timeline_count is not None and timeline_count > 1
    if tool_name == "image_generation":
        if role is SpecialistRole.VISUAL_DEVELOPMENT:
            if script_flow:
                # 多集项目的角色/场景设计基于已确认的结构；剧本检查点
                # 在分镜/视频（storyboard 消费方）之前生效即可，设计图
                # 可与剧本审阅并行推进。
                return (CHECKPOINT_STRUCTURE,)
            return ()
    elif tool_name != "r2v_generation":
        return ()
    if execution_mode == EXECUTION_MODE_FINE_TUNING:
        return ()
    # Storyboard images consume the approved designs.
    if script_flow:
        return (
            CHECKPOINT_STRUCTURE,
            CHECKPOINT_SCRIPT,
            CHECKPOINT_DESIGN,
        )
    return (CHECKPOINT_DESIGN,)


def retire_legacy_plan_checkpoints(executions, project_id: str) -> int:
    """Expire only pending, non-billing plan records using the store's CAS.

    Preserve terminal history and concurrent user decisions. EXPIRED is
    deliberately not APPROVED: retiring a UI checkpoint grants no money.
    """
    from services.runtime_files.execution_models import (
        ExecutionAuthorizationStatus,
    )
    from services.runtime_files.execution_store import ExecutionStateConflict

    retired = 0
    for record in executions.list_execution_authorizations(project_id):
        if (
            record.status is not ExecutionAuthorizationStatus.PENDING
            or record.operation != checkpoint_operation(CHECKPOINT_PLAN)
            or record.requested_provider != CHECKPOINT_PROVIDER
        ):
            continue
        try:
            executions.decide_execution_authorization(
                project_id,
                record.authorization_id,
                authorization_token=record.authorization_token,
                status=ExecutionAuthorizationStatus.EXPIRED,
                metadata={"retiredReason": "plan_checkpoint_removed"},
            )
            retired += 1
        except ExecutionStateConflict:
            # A decision that won the CAS remains the durable authority.
            continue
    return retired


def checkpoint_operation(phase: str) -> str:
    return f"{CHECKPOINT_OPERATION_PREFIX}_{phase}"


def checkpoint_authorization_id(
    project_id: str,
    phase: str,
    attempt: int = 0,
) -> str:
    """One durable approval per Project, phase and attempt.

    Attempt 0 keeps the original seed so approvals recorded before
    attempts existed stay valid. A rejected attempt is a terminal audit
    record; the next generation call opens attempt N+1 so the user can
    approve the revised plan or designs instead of being locked out.
    """

    seed = f"qwenpaw-creator:creation-checkpoint:{project_id}:{phase}"
    if attempt > 0:
        seed = f"{seed}:attempt-{attempt}"
    return "authorization-" + uuid5(NAMESPACE_URL, seed).hex


def checkpoint_execution_request_id(
    project_id: str,
    phase: str,
    attempt: int = 0,
) -> str:
    if attempt > 0:
        return f"creation-checkpoint:{project_id}:{phase}:attempt-{attempt}"
    return f"creation-checkpoint:{project_id}:{phase}"


def checkpoint_summary(phase: str) -> str:
    return _CHECKPOINT_SUMMARIES.get(
        phase,
        f"创作检查点 {phase}：确认后继续。",
    )


def checkpoint_label(phase: str) -> str:
    return _CHECKPOINT_LABELS.get(phase, phase)


def checkpoint_recovery(phase: str) -> str:
    """Guidance handed to the model when a checkpoint blocks or is declined."""

    if phase == CHECKPOINT_PLAN:
        return (
            "旧的计划确认关卡已移除，无需用户确认。读取剧集蓝图中的真实剧情与" "剧本，补齐缺失内容后继续当前任务；实际媒体生成授权仍须遵守。"
        )
    if phase == CHECKPOINT_DESIGN:
        return (
            "用户尚未确认角色/场景设计图。请不要重试生成：向用户说明已生成的"
            "设计图，等待用户在决策托盘中确认设计检查点，"
            "或按用户的修改意见先重做设计图。"
        )
    if phase == CHECKPOINT_STRUCTURE:
        return (
            "用户尚未确认分集/分支结构。请不要重试生成：向用户说明当前的"
            "结构草案（各集标题、梗概与叙事分支），等待用户在决策托盘中确认"
            "结构检查点，或按用户的修改意见先调整结构。"
        )
    if phase == CHECKPOINT_SCRIPT:
        return (
            "用户尚未确认剧本草稿。请不要重试生成：向用户说明当前的剧本"
            "内容，等待用户在决策托盘中确认剧本检查点，"
            "或按用户的修改意见先修订剧本。"
        )
    return "用户尚未确认对应的创作检查点。请等待用户确认，不要重试生成。"
