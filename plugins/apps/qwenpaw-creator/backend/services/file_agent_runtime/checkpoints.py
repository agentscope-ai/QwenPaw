# -*- coding: utf-8 -*-
"""Creation pit-stop checkpoints for the file-native Creator Runtime.

Two hard stops protect the user's money from compounding mistakes:
planning errors are cheap to fix as text and expensive to fix as media,
and a wrong character design silently poisons every storyboard and video
built on top of it.

- ``plan``:   confirmed before *any* visual generation. Cuts, shot lists
  and prompts are reviewable as text at this point.
- ``design``: confirmed after character/scene design images exist but
  before storyboards and videos consume them, so the user judges the
  designs with their eyes rather than from a description.

The gate is deterministic: it lives in tool admission, not in a prompt,
so an agent cannot skip a checkpoint by forgetting to ask. Approvals are
persisted as ordinary execution authorizations, which already own the
token CAS, idempotent decisions and the blocking decision-tray card.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from domain.enums import SpecialistRole

CHECKPOINT_PLAN = "plan"
CHECKPOINT_DESIGN = "design"
CHECKPOINT_DIRECTION = "direction"

CHECKPOINT_OPERATION_PREFIX = "creation_checkpoint"
CHECKPOINT_PROVIDER = "creator-checkpoint"

_CHECKPOINT_SUMMARIES = {
    CHECKPOINT_PLAN: (
        "计划检查点：确认分镜切分、镜头与各 Element 的 prompt 之后再开始生成。" "通过后本项目不再重复询问。"
    ),
    CHECKPOINT_DESIGN: (
        "设计检查点：确认角色/场景设计图之后再生成分镜图与视频，" "避免用错误的形象继续往下做。通过后本项目不再重复询问。"
    ),
    CHECKPOINT_DIRECTION: ("方向检查点：共创模式下剪辑开始前先确认创作方向（三选一）。" "选定后本项目不再重复询问。"),
}

_CHECKPOINT_LABELS = {
    CHECKPOINT_PLAN: "计划确认",
    CHECKPOINT_DESIGN: "设计确认",
    CHECKPOINT_DIRECTION: "方向确认",
}


def required_checkpoint_phases(
    tool_name: str,
    role: SpecialistRole,
) -> tuple[str, ...]:
    """Return the checkpoints a media tool call must clear, in order.

    Character/scene design images only need the plan checkpoint — they
    are the very artifacts the design checkpoint later reviews, so
    requiring it here would deadlock the workflow.

    The execution mode scales the set (upstream three governance modes):
    ``delegated`` drops the pit stops entirely (billing authorizations
    are a separate gate and stay); ``fine_tuning`` keeps one plan-phase
    scope confirmation; ``co_creation`` keeps the full ladder. The
    creative direction gate itself is conversational (the editing
    director proposes three cards and blocks for the user's pick), not a
    tool-admission phase — see the editing-director prompt.
    """

    from models.config import (
        EXECUTION_MODE_DELEGATED,
        EXECUTION_MODE_FINE_TUNING,
        get_execution_mode,
    )

    execution_mode = get_execution_mode()
    if execution_mode == EXECUTION_MODE_DELEGATED:
        return ()
    if tool_name == "image_generation":
        if role is SpecialistRole.VISUAL_DEVELOPMENT:
            return (CHECKPOINT_PLAN,)
    elif tool_name != "r2v_generation":
        return ()
    if execution_mode == EXECUTION_MODE_FINE_TUNING:
        # One scope confirmation for iterations on a delivered cut.
        return (CHECKPOINT_PLAN,)
    # Storyboard images consume the approved designs.
    return (CHECKPOINT_PLAN, CHECKPOINT_DESIGN)


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
            "用户尚未确认创作计划。请不要重试生成：向用户说明当前的分镜切分、"
            "镜头安排与关键 prompt，等待用户在决策托盘中确认计划检查点，"
            "或按用户的修改意见先更新计划。"
        )
    if phase == CHECKPOINT_DESIGN:
        return (
            "用户尚未确认角色/场景设计图。请不要重试生成：向用户说明已生成的"
            "设计图，等待用户在决策托盘中确认设计检查点，"
            "或按用户的修改意见先重做设计图。"
        )
    return "用户尚未确认对应的创作检查点。请等待用户确认，不要重试生成。"
