# -*- coding: utf-8 -*-
"""Feedback delivery for the async media review (mirrors render_review).

Findings are admitted as a durable RUNTIME mutation-instruction message via
``admit_user_request``; the ``admission_guard`` re-validates the reviewed
artifact's slot selection inside the Project lifecycle boundary, so a
superseded artifact can never receive a mutation instruction.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from schemas.run_review import MediaReviewReport
from services.run_review import admission
from services.runtime_files import (
    MessageChannel,
    MessageClassification,
    RuntimeSessionNotFound,
)
from utils.logger import setup_logger

if TYPE_CHECKING:
    from services.project_files.facade import CreatorFileServices

logger = setup_logger("creator.run_review.feedback")


def selected_slot_version(
    services: "CreatorFileServices",
    project_id: str,
    *,
    version_id: str,
    slot_id: str | None,
) -> str | None:
    """Return the currently selected ArtifactVersion of the owning slot."""
    snapshot = services.projects.read(project_id)
    slots = snapshot.project.assets.artifact_slots_by_id
    slot = slots.get(slot_id) if slot_id else None
    if slot is None:
        slot = next(
            (
                item
                for item in slots.values()
                if version_id in item.version_ids
            ),
            None,
        )
    return slot.selected_version_id if slot is not None else None


def feedback_text(
    report: MediaReviewReport,
    *,
    target_ref: str,
    command: str,
) -> str:
    payload = {
        "type": "run_review_feedback",
        "artifact_ref": report.artifact_ref,
        "kind": report.kind,
        "round": report.round,
        "max_rounds": admission.MAX_MEDIA_REVIEW_ROUNDS,
        "verdict": report.verdict,
        "findings": [
            item.model_dump(mode="json") for item in report.failed_findings()
        ],
    }
    label = "生成图像" if report.kind == "image" else "分镜视频"
    return (
        f"【运行审阅反馈 · {label} · 第 {report.round}/"
        f"{admission.MAX_MEDIA_REVIEW_ROUNDS} 轮】\n"
        f"产物 {report.artifact_ref}（{command}）未通过旁路审阅。请针对 "
        f"{target_ref} 仅修复下列结构化审阅发现中列出的问题（重新生成或调整"
        "提示词），不要扩大改动范围。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def admit_feedback(
    services: "CreatorFileServices",
    *,
    project_id: str,
    report: MediaReviewReport,
    target_ref: str,
    command: str,
    version_id: str,
    freshness_guard: Any = None,
) -> bool:
    """Admit the findings as a durable turn message. Mirrors render_review."""
    try:
        session = services.sessions.get_project_session_snapshot(project_id)
    except RuntimeSessionNotFound:
        logger.info(
            "run review feedback skipped: project %s has no runtime session",
            project_id,
        )
        return False
    conversations = services.sessions.list_conversations(
        project_id,
        session.session_id,
    )
    default = next(
        (item for item in conversations if item.is_default),
        conversations[0] if conversations else None,
    )
    if default is None:
        return False
    request_id = f"run-review-{version_id}-round-{report.round}"
    services.sessions.admit_user_request(
        project_id,
        session.session_id,
        default.conversation_id,
        request_id=request_id,
        client_message_id=request_id,
        content_parts=[
            {
                "type": "text",
                "text": feedback_text(
                    report,
                    target_ref=target_ref,
                    command=command,
                ),
            },
        ],
        source="run_review_feedback",
        channel=MessageChannel.RUNTIME,
        classification=MessageClassification.MUTATION_INSTRUCTION,
        metadata={"runReview": report.model_dump(mode="json")},
        admission_guard=freshness_guard,
    )
    return True


__all__ = ["admit_feedback", "feedback_text", "selected_slot_version"]
