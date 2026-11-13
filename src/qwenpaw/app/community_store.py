# -*- coding: utf-8 -*-
"""Private community connection and durable inbox state for one runtime owner.

Standalone QwenPaw has one deployment owner. Hub gives each user's runtime
its own WORKING_DIR and access boundary. Community credentials never share
the local/Hub login store. Events, cursors and deletion tombstones are updated
in a single atomic file, so interrupted/repeated sync cannot resurrect mail.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Any

from ..constant import WORKING_DIR
from ..utils.io_utils import read_json, run_sync_io, write_json_atomic

_STATE_PATH = WORKING_DIR / "community" / "state.json"
_LOCK = asyncio.Lock()
_MAX_VISIBLE_EVENTS = 5000


def _load() -> dict[str, Any]:
    if not _STATE_PATH.exists():
        return {"connection": None, "sync": {}, "events": {}}
    # Do not overwrite a corrupt credential/tombstone file with empty state.
    data = read_json(_STATE_PATH)
    if not isinstance(data, dict) or not isinstance(data.get("events"), dict):
        raise ValueError("Invalid community state file")
    return data


def _save(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_json_atomic(_STATE_PATH, state, new_file_mode=0o600)


def _matches(state: dict, account_id: str, connection_id: str | None) -> bool:
    connection = state.get("connection") or {}
    return connection.get("account_id") == account_id and (
        connection_id is None
        or connection.get("connection_id") == connection_id
    )


async def get_connection() -> dict | None:
    """Internal only: credentials must never be returned directly to the UI."""
    async with _LOCK:
        return (await run_sync_io(_load)).get("connection")


async def save_connection(
    connection: dict,
    expected_account_id: str | None = None,
    expected_connection_id: str | None = None,
    *,
    authorization_completed: bool = False,
) -> bool:
    """Save credentials and atomically reconcile successful authorization.

    Reauthorizing the same account preserves its latest message preferences.
    Only a completed authorization clears a previous authorization error;
    ordinary settings updates must not make expired credentials look valid.
    """
    if not connection.get("account_id"):
        raise ValueError("A community account identity is required")
    async with _LOCK:
        state = await run_sync_io(_load)
        if expected_account_id is not None and not _matches(
            state,
            expected_account_id,
            expected_connection_id,
        ):
            return False
        previous = state.get("connection") or {}
        connection = dict(connection)
        if previous.get("account_id") != connection["account_id"]:
            state = {"connection": None, "sync": {}, "events": {}}
        elif authorization_completed:
            for key in ("sync_enabled", "message_types"):
                if key in previous:
                    connection[key] = previous[key]
        if authorization_completed:
            sync = state.setdefault("sync", {})
            if sync.get("last_error") == "authorization_expired":
                sync["last_error"] = None
        connection.setdefault("connection_id", str(uuid.uuid4()))
        connection.setdefault("sync_enabled", True)
        state["connection"] = connection
        await run_sync_io(_save, state)
        return True


async def disconnect() -> None:
    """Atomically forget the account, its credentials, mail and cursors."""
    async with _LOCK:
        await run_sync_io(
            _save,
            {"connection": None, "sync": {}, "events": {}},
        )


async def get_sync_state() -> dict:
    async with _LOCK:
        return (await run_sync_io(_load)).get("sync", {})


async def update_sync_state(
    account_id: str,
    values: dict,
    connection_id: str | None = None,
) -> bool:
    async with _LOCK:
        state = await run_sync_io(_load)
        if not _matches(state, account_id, connection_id):
            return False
        state.setdefault("sync", {}).update(values)
        await run_sync_io(_save, state)
        return True


MESSAGE_TYPES = [
    "comments",
    "mentions",
    "interactions",
    "feedback",
    "notifications",
]


async def ingest(
    account_id: str,
    events: list[dict],
    cursor: dict,
    connection_id: str | None = None,
) -> int:
    """Commit one fetched page without changing existing local read state.

    Each normalized event must have a remote_id prefixed by stream/event kind.
    Deleted/retention-trimmed entries retain only their ID as tombstones.
    """
    async with _LOCK:
        state = await run_sync_io(_load)
        if not _matches(state, account_id, connection_id) or not (
            state["connection"].get("sync_enabled", True)
        ):
            return 0
        selected = state["connection"].get("message_types", MESSAGE_TYPES)
        cursor = {
            **state.get("sync", {}).get("cursor", {}),
            **{
                key: value
                for key, value in cursor.items()
                if key in selected
                or "message_types" not in state["connection"]
            },
        }
        stored = state["events"]
        inserted = 0
        for incoming in events:
            remote_id = incoming.get("remote_id")
            if not isinstance(remote_id, str) or not remote_id:
                raise ValueError("Community events require a stable remote ID")
            if (
                "message_types" in state["connection"]
                and remote_id.split(":", 1)[0] not in selected
            ):
                continue
            event_id = (
                "community:"
                + hashlib.sha256(
                    f"{account_id}\0{remote_id}".encode(),
                ).hexdigest()
            )
            if event_id in stored:
                continue
            event = dict(incoming)
            event.update(
                {
                    "id": event_id,
                    "agent_id": "",
                    "account_id": account_id,
                    "source_type": "community",
                    "source_id": remote_id,
                    "read": bool(incoming.get("read", False)),
                    "status": "info",
                    "severity": "info",
                },
            )
            event.setdefault("payload", {})
            event.setdefault("created_at", time.time())
            stored[event_id] = event
            inserted += 1
        visible = sorted(
            (e for e in stored.values() if not e.get("deleted")),
            key=lambda e: e.get("created_at", 0),
            reverse=True,
        )
        for old in visible[_MAX_VISIBLE_EVENTS:]:
            stored[old["id"]] = {"id": old["id"], "deleted": True}
        state.setdefault("sync", {}).update(
            {
                "cursor": cursor,
                "last_success_at": time.time(),
                "last_error": None,
            },
        )
        await run_sync_io(_save, state)
        return inserted


async def inbox_snapshot() -> tuple[list[dict], str | None]:
    """Read events and a public opaque account generation atomically.

    None means positively disconnected. A corrupt store raises instead of
    presenting an unknown account as a confirmed logout.
    """
    async with _LOCK:
        state = await run_sync_io(_load)
        if "connection" not in state:
            raise ValueError("Invalid community account state")
        connection = state.get("connection")
        if connection is None:
            return [], None
        if not isinstance(connection, dict) or not connection.get(
            "account_id",
        ):
            raise ValueError("Invalid community account state")
        scope_key = (
            f"{connection['account_id']}\0"
            f"{connection.get('connection_id', '')}"
        )
        scope = hashlib.sha256(scope_key.encode()).hexdigest()
        return [
            e for e in state["events"].values() if not e.get("deleted")
        ], scope


async def list_events() -> list[dict]:
    events, _ = await inbox_snapshot()
    return events


async def mark_read(event_ids: list[str] | None = None) -> int:
    """Mark selected events, or all when None, in the current account only."""
    ids = set(event_ids) if event_ids is not None else None
    updated = 0
    async with _LOCK:
        state = await run_sync_io(_load)
        for event in state["events"].values():
            if (
                not event.get("deleted")
                and not event.get("read")
                and (ids is None or event["id"] in ids)
            ):
                event["read"] = True
                updated += 1
        if updated:
            await run_sync_io(_save, state)
    return updated


async def delete_event(event_id: str) -> bool:
    async with _LOCK:
        state = await run_sync_io(_load)
        event = state["events"].get(event_id)
        if event is None or event.get("deleted"):
            return False
        state["events"][event_id] = {"id": event_id, "deleted": True}
        await run_sync_io(_save, state)
        return True
