# -*- coding: utf-8 -*-
"""Inbox notification policy for ReMe job results."""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

RESULT_JOB_NAMES = {"auto_memory", "auto_dream", "daily_paper"}
NOTIFICATION_FIELDS = {
    "auto_memory": "auto_memory_inbox_push_enabled",
    "auto_dream": "auto_dream_inbox_push_enabled",
    "daily_paper": "daily_paper_inbox_push_enabled",
}
EMITTED_METADATA_KEY = "_qwenpaw_inbox_emitted"
MAX_BODY_CHARS = 4000


def is_successful_noop(name: str, response: Any) -> bool:
    """Return whether a successful job made no meaningful change."""
    if not bool(getattr(response, "success", False)):
        return False
    metadata = getattr(response, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    if name == "auto_memory":
        return metadata.get("modified") is False
    if name == "auto_dream":
        if metadata.get("modified") is not False:
            return False
        dream = metadata.get("dream")
        return not (
            isinstance(dream, dict) and bool(dream.get("deleted_paths"))
        )
    return False


def result_title(name: str) -> str:
    return {
        "auto_memory": "Auto-memory result",
        "auto_dream": "Auto-dream result",
        "daily_paper": "Daily Paper result",
    }.get(name, "Memory job result")


def empty_result_body(name: str) -> str:
    return {
        "auto_memory": "Auto-memory completed with no returned content.",
        "auto_dream": "Auto-dream completed with no returned content.",
        "daily_paper": "Daily Paper completed with no returned content.",
    }.get(name, "Memory job completed with no returned content.")


def build_payload(
    name: str,
    kwargs: dict[str, Any],
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the stable inbox payload for a ReMe job."""
    payload: dict[str, Any] = {
        "job_name": name,
        "session_id": str(kwargs.get("session_id") or ""),
        "date": str(kwargs.get("date") or ""),
        "hint": str(kwargs.get("memory_hint") or kwargs.get("hint") or ""),
    }
    if name != "daily_paper":
        return payload
    payload["force"] = bool(kwargs.get("force", False))
    payload["topics"] = str(kwargs.get("topics") or "")
    if isinstance(metadata, dict):
        for key in (
            "digest_path",
            "selected_arxiv_ids",
            "note_paths",
            "pdf_paths",
            "skipped",
        ):
            if key in metadata:
                payload[key] = metadata[key]
    return payload


async def emit_job_result(
    *,
    agent_id: str,
    memory_config: Any,
    name: str,
    response: Any,
    kwargs: dict[str, Any],
    append_event: Callable[..., Any],
) -> bool:
    """Apply notification policy and append one ReMe result event."""
    if name not in RESULT_JOB_NAMES:
        return False
    if not getattr(memory_config, NOTIFICATION_FIELDS[name]):
        logger.info(
            "ReMe job result inbox push disabled: agent_id=%s job_name=%s",
            agent_id,
            name,
        )
        return False
    metadata = getattr(response, "metadata", None)
    if isinstance(metadata, dict) and metadata.get(EMITTED_METADATA_KEY):
        return False
    if is_successful_noop(name, response):
        logger.info(
            "ReMe inbox push skipped; successful no-op: agent_id=%s job=%s",
            agent_id,
            name,
        )
        return False

    answer = str(getattr(response, "answer", "") or "").strip()
    if len(answer) > MAX_BODY_CHARS:
        answer = f"{answer[:MAX_BODY_CHARS].rstrip()}\n..."
    success = bool(getattr(response, "success", False))
    try:
        event = await append_event(
            agent_id=agent_id,
            source_type="memory",
            source_id=name,
            event_type=f"{name}_result",
            status="success" if success else "error",
            severity="info" if success else "error",
            title=result_title(name),
            body=answer or empty_result_body(name),
            payload=build_payload(name, kwargs, metadata),
        )
        if isinstance(metadata, dict):
            metadata[EMITTED_METADATA_KEY] = True
        logger.info(
            "ReMe result pushed: agent=%s job=%s event=%s status=%s",
            agent_id,
            name,
            event.get("id"),
            event.get("status"),
        )
        return True
    except Exception:
        logger.exception(
            "failed to push ReMe result: agent=%s job=%s success=%s",
            agent_id,
            name,
            success,
        )
        return False
