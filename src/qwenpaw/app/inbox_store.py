# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from ..constant import WORKING_DIR

_INBOX_PATH = WORKING_DIR / "inbox_events.json"
_LOCK = asyncio.Lock()
_MAX_EVENTS = 5000


def _load_events() -> list[dict[str, Any]]:
    if not _INBOX_PATH.exists():
        return []
    data = json.loads(_INBOX_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _save_events(events: list[dict[str, Any]]) -> None:
    _INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _INBOX_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(events, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(_INBOX_PATH)


async def append_event(
    *,
    agent_id: str | None,
    source_type: str,
    source_id: str | None,
    event_type: str,
    status: str,
    title: str,
    body: str,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "id": str(uuid.uuid4()),
        "agent_id": agent_id or "default",
        "source_type": source_type,
        "source_id": source_id or "",
        "event_type": event_type,
        "status": status,
        "severity": severity,
        "title": title,
        "body": body,
        "payload": payload or {},
        "read": False,
        "created_at": time.time(),
    }
    async with _LOCK:
        events = _load_events()
        events.insert(0, event)
        del events[_MAX_EVENTS:]
        _save_events(events)
    return event


async def list_events(
    *,
    limit: int = 50,
    offset: int = 0,
    source_type: str | None = None,
    status: str | None = None,
    agent_id: str | None = None,
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    async with _LOCK:
        events = _load_events()
    if source_type:
        events = [
            event
            for event in events
            if event.get("source_type") == source_type
        ]
    if status:
        events = [event for event in events if event.get("status") == status]
    if agent_id:
        events = [
            event for event in events if event.get("agent_id") == agent_id
        ]
    if unread_only:
        events = [event for event in events if not bool(event.get("read"))]
    return events[offset : offset + max(limit, 0)]


async def mark_read(event_ids: list[str]) -> int:
    if not event_ids:
        return 0
    event_id_set = set(event_ids)
    updated = 0
    async with _LOCK:
        events = _load_events()
        for event in events:
            if event.get("id") in event_id_set and not bool(event.get("read")):
                event["read"] = True
                updated += 1
        _save_events(events)
    return updated


async def mark_all_read() -> int:
    updated = 0
    async with _LOCK:
        events = _load_events()
        for event in events:
            if not bool(event.get("read")):
                event["read"] = True
                updated += 1
        _save_events(events)
    return updated


async def delete_event(event_id: str) -> tuple[bool, str | None, bool]:
    if not event_id:
        return False, None, False
    deleted = False
    deleted_run_id: str | None = None
    run_id_still_referenced = False
    async with _LOCK:
        events = _load_events()
        kept_events = []
        for event in events:
            if not deleted and event.get("id") == event_id:
                payload = event.get("payload") or {}
                if isinstance(payload, dict) and isinstance(
                    payload.get("run_id"),
                    str,
                ):
                    deleted_run_id = payload.get("run_id")
                deleted = True
                continue
            kept_events.append(event)
        if deleted and deleted_run_id:
            for event in kept_events:
                payload = event.get("payload") or {}
                if (
                    isinstance(payload, dict)
                    and payload.get("run_id") == deleted_run_id
                ):
                    run_id_still_referenced = True
                    break
        if deleted:
            _save_events(kept_events)
    return deleted, deleted_run_id, run_id_still_referenced
