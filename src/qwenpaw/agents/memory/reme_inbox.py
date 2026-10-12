# -*- coding: utf-8 -*-
"""Inbox notification policy for ReMe job results."""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

RESULT_JOB_NAMES = {"auto_memory", "auto_dream", "daily_paper", "auto_fin"}
# The proactive agenda is deliberately *not* in RESULT_JOB_NAMES: a manual
# `/reme proactive` read must not advance the user's inbox. The idle trigger
# and the daily cron call emit_proactive_agenda() explicitly instead.
PROACTIVE_JOB_NAME = "proactive"
PROACTIVE_EVENT_TYPE = "proactive_agenda_result"
PROACTIVE_NOTIFICATION_FIELD = "proactive_inbox_push_enabled"
NOTIFICATION_FIELDS = {
    "auto_memory": "auto_memory_inbox_push_enabled",
    "auto_dream": "auto_dream_inbox_push_enabled",
    "daily_paper": "daily_paper_inbox_push_enabled",
    "auto_fin": "auto_fin_inbox_push_enabled",
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
    noop = False
    if name == "auto_memory":
        noop = metadata.get("modified") is False
    elif name == "auto_dream":
        if metadata.get("modified") is not False:
            return False
        dream = metadata.get("dream")
        noop = not (
            isinstance(dream, dict) and bool(dream.get("deleted_paths"))
        )
    elif name == "auto_fin":
        noop = metadata.get("skipped") is True
    return noop


def result_title(name: str) -> str:
    return {
        "auto_memory": "Auto-memory result",
        "auto_dream": "Auto-dream result",
        "daily_paper": "Daily Paper result",
        "auto_fin": "Auto Fin result",
    }.get(name, "Memory job result")


def empty_result_body(name: str) -> str:
    return {
        "auto_memory": "Auto-memory completed with no returned content.",
        "auto_dream": "Auto-dream completed with no returned content.",
        "daily_paper": "Daily Paper completed with no returned content.",
        "auto_fin": "Auto Fin completed with no returned content.",
    }.get(name, "Memory job completed with no returned content.")


def empty_error_body(name: str) -> str:
    label = {
        "auto_memory": "Auto-memory",
        "auto_dream": "Auto-dream",
        "daily_paper": "Daily Paper",
        "auto_fin": "Auto Fin",
    }.get(name, "Memory job")
    return (
        f"{label} failed with no returned error details. "
        "Check the application logs for more information."
    )


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
    if name not in {"daily_paper", "auto_fin"}:
        return payload
    payload["topics"] = str(kwargs.get("topics") or "")
    if name == "auto_fin":
        payload["window_hours"] = float(kwargs.get("window_hours") or 24)
    else:
        payload["force"] = bool(kwargs.get("force", False))
    if isinstance(metadata, dict):
        if not payload["date"]:
            payload["date"] = str(metadata.get("date") or "")
        keys = (
            (
                "digest_path",
                "selected_arxiv_ids",
                "note_paths",
                "pdf_paths",
                "skipped",
            )
            if name == "daily_paper"
            else (
                "digest_path",
                "selected_news_count",
                "relevant_news_count",
                "skipped",
                "skip_reason",
            )
        )
        for key in keys:
            if key in metadata:
                payload[key] = metadata[key]
        if name == "auto_fin" and isinstance(metadata.get("topics"), list):
            payload["effective_topics"] = [
                str(topic) for topic in metadata["topics"]
            ]
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
            body=answer
            or (
                empty_result_body(name) if success else empty_error_body(name)
            ),
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


def build_proactive_agenda_body(items: list[Any], language: str) -> str:
    """Render the reading-only inbox body for an agenda push."""
    from .proactive.proactive_prompts import build_inbox_body  # noqa: PLC0415

    return build_inbox_body(list(items), language)


def proactive_agenda_payload(
    items: list[Any],
    *,
    date: str,
    channel: str,
    language: str,
) -> dict[str, Any]:
    """Stable inbox payload for one proactive agenda push."""
    from .proactive.proactive_prompts import inbox_title  # noqa: PLC0415

    return {
        "job_name": PROACTIVE_JOB_NAME,
        "date": date,
        "channel": channel,
        "count": len(items),
        "title": inbox_title(len(items), language, channel=channel),
        "agenda": [
            {
                "topic_id": item.topic_id,
                "title": item.title,
                "kind": item.kind,
                "opener": item.opener,
                "next_action": item.next_action,
                "due_at": item.due_at,
            }
            for item in items
        ],
    }


async def emit_proactive_agenda(
    *,
    agent_id: str,
    memory_config: Any,
    date: str,
    items: list[Any],
    append_event: Callable[..., Any],
    channel: str = "cron",
    language: str = "en",
) -> dict[str, Any] | None:
    """Append one proactive agenda card, honouring the inbox switch.

    Returns the created event, or ``None`` when the push is disabled, there
    is nothing to show, or the inbox rejected the event. An empty agenda
    stays silent by design: the inbox is a reading surface, so a card that
    says "nothing today" is pure noise.
    """
    if not items:
        logger.info("proactive inbox push skipped; empty agenda")
        return None
    if not getattr(memory_config, PROACTIVE_NOTIFICATION_FIELD, False):
        logger.info(
            "proactive inbox push disabled: agent_id=%s channel=%s",
            agent_id,
            channel,
        )
        return None
    body = build_proactive_agenda_body(items, language)
    if len(body) > MAX_BODY_CHARS:
        body = f"{body[:MAX_BODY_CHARS].rstrip()}\n..."
    payload = proactive_agenda_payload(
        items,
        date=date,
        channel=channel,
        language=language,
    )
    try:
        event = await append_event(
            agent_id=agent_id,
            source_type="memory",
            source_id=PROACTIVE_JOB_NAME,
            event_type=PROACTIVE_EVENT_TYPE,
            status="success",
            severity="info",
            title=payload["title"],
            body=body,
            payload=payload,
        )
    except Exception:
        logger.exception(
            "failed to push the proactive agenda: agent=%s channel=%s",
            agent_id,
            channel,
        )
        return None
    logger.info(
        "proactive agenda pushed: agent=%s channel=%s items=%d event=%s",
        agent_id,
        channel,
        len(items),
        event.get("id") if isinstance(event, dict) else event,
    )
    return event if isinstance(event, dict) else {"id": str(event or "")}
