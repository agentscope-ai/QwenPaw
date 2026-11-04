# -*- coding: utf-8 -*-
"""Read-only check for daily notes that were never processed.

ReMe v4 stores hot-tier daily notes under ``<daily_dir>/YYYY-MM-DD/<slug>.md``
and marks them with an optional ``status`` frontmatter field: absent means the
note is still pending, ``completed`` and ``skipped`` mean it was resolved.
QwenPaw never consumed that field, so an unprocessed note simply went quiet.

This module surfaces those notes as deduplicated Inbox events.  It is
read-only: it never edits, deletes or rewrites a note, never writes memory,
and only runs when an agent (or a cron prompt) calls the tool.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock
from agentscope.message import ToolResultState
from agentscope.tool import ToolChunk

from ...app.agent_context import get_current_agent_id
from ...app.inbox_store import append_event, list_events
from ...config.config import load_agent_config
from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)

SOURCE_TYPE = "stale_notes"
DEFAULT_DAYS = 7
DEFAULT_COOLDOWN_DAYS = 7
MAX_LIMIT = 200
MAX_SCAN = 5000

_RESOLVED = frozenset({"completed", "skipped"})
_STATUS_LINE = re.compile(
    r"^\s*status\s*:\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_DATE_PART = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$",
)


def _daily_root(agent_id: str) -> Path:
    """Resolve the daily-note directory used by *agent_id*."""
    workspace = Path(get_current_workspace_dir() or WORKING_DIR)
    name = "memory"
    try:
        config = load_agent_config(agent_id)
        configured = getattr(
            config.running.reme_light_memory_config,
            "daily_dir",
            "",
        )
        if isinstance(configured, str) and configured.strip():
            name = configured.strip()
    except Exception:  # pylint: disable=broad-except
        logger.debug("Falling back to the default daily dir", exc_info=True)
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        logger.warning("Unsafe configured daily dir %r; using 'memory'", name)
        relative = Path("memory")
    return workspace / relative


def _frontmatter_status(text: str) -> str | None:
    """Return the normalized ``status`` frontmatter value, if any."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        match = _STATUS_LINE.match(line)
        if match:
            value = match.group("value").strip().strip("'\"")
            return value.lower() or None
    return None


def _read_status(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _frontmatter_status(text)


def _note_date(path: Path, root: Path) -> date | None:
    """Prefer the ``YYYY-MM-DD`` path segment, else fall back to mtime."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    for part in relative.parts[:-1]:
        match = _DATE_PART.match(part)
        if not match:
            continue
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, timezone.utc).date()


def _iter_notes(root: Path) -> list[Path]:
    """Return ``<daily_dir>/<date>/<slug>.md`` files, sorted by path."""
    if not root.is_dir():
        return []
    found: dict[str, Path] = {}
    for path in root.glob("*/*.md"):
        if path.is_file():
            found[path.as_posix()] = path
    return [found[key] for key in sorted(found)][:MAX_SCAN]


def _is_pending(status: str | None) -> bool:
    """Absent status means pending; unknown values are left alone.

    The vocabulary belongs to ReMe, so a value QwenPaw does not recognise is
    treated as resolved rather than nagging the user about it.
    """
    return status is None or status == "pending"


async def _scan(agent_id: str, days: int) -> list[dict[str, Any]]:
    root = _daily_root(agent_id)
    today = date.today()
    pending: list[dict[str, Any]] = []
    for path in _iter_notes(root):
        status = _read_status(path)
        if status in _RESOLVED or not _is_pending(status):
            continue
        note_date = _note_date(path, root)
        if note_date is None:
            continue
        age = (today - note_date).days
        if age < days:
            continue
        pending.append(
            {
                "key": path.relative_to(root).as_posix(),
                "date": note_date.isoformat(),
                "age_days": age,
            },
        )
    return pending


async def _suppressed_keys(agent_id: str, cooldown_days: int) -> set[str]:
    """Keys that must not be reported again this run.

    With a cooldown the note stays quiet for *cooldown_days* after its last
    reminder, read or not — otherwise a user who opens the Inbox would be
    reminded again on the very next run while the note is still pending.
    With ``cooldown_days=0`` the check falls back to the issue's original
    rule: only an unread event suppresses the next reminder.
    """
    events = await list_events(
        limit=MAX_SCAN,
        source_type=SOURCE_TYPE,
        agent_id=agent_id,
    )
    cutoff = time.time() - cooldown_days * 86400 if cooldown_days > 0 else None
    keys: set[str] = set()
    for event in events:
        if cutoff is None:
            if event.get("read"):
                continue
        else:
            created = event.get("created_at")
            if not isinstance(created, (int, float)) or created < cutoff:
                continue
        payload = event.get("payload") or {}
        key = payload.get("key")
        if isinstance(key, str) and key:
            keys.add(key)
    return keys


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="CheckStaleNotes",
    decision_model_no_target_read=True,
    ui_description="List unprocessed daily notes",
    ui_icon="\U0001f5d2",
)
async def check_stale_notes(
    days: int = DEFAULT_DAYS,
    dry_run: bool = False,
    limit: int = 20,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> ToolChunk:
    """Find daily notes that are still unprocessed and push Inbox reminders.

    A note counts as stale when its ``status`` frontmatter is absent (the
    ReMe v4 convention for "pending") and its date — taken from the
    ``<daily_dir>/YYYY-MM-DD/`` path segment, falling back to the file
    mtime — is at least *days* days old.  ``completed`` and ``skipped``
    notes are ignored.

    Each ``(file, slug)`` is reported at most once per cooldown window, so a
    note the user has already seen does not fire again on the next run while
    it is still pending.  The check never edits, deletes or rewrites a note,
    never writes memory, and does nothing unless called.

    Args:
        days: Minimum age in days before a note is reported. Defaults to 7.
        dry_run: When True, report what would be pushed without pushing.
        limit: Maximum number of Inbox events to create in one call.
        cooldown_days: Days to stay quiet after a reminder. ``0`` falls back
            to "suppress only while the event is unread".

    Returns:
        `ToolChunk`: A summary listing the stale notes.
    """
    agent_id = get_current_agent_id() or "default"
    try:
        minimum = max(int(days), 0)
    except (TypeError, ValueError):
        minimum = DEFAULT_DAYS
    try:
        maximum = min(max(int(limit), 1), MAX_LIMIT)
    except (TypeError, ValueError):
        maximum = 20

    try:
        cooldown = max(int(cooldown_days), 0)
    except (TypeError, ValueError):
        cooldown = DEFAULT_COOLDOWN_DAYS

    try:
        pending = await _scan(agent_id, minimum)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Stale-note scan failed: %s", exc, exc_info=True)
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[TextBlock(type="text", text=f"Scan failed: {exc}")],
        )

    if not pending:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=f"No stale daily notes (threshold {minimum}d).",
                ),
            ],
        )

    seen = await _suppressed_keys(agent_id, cooldown)
    added = 0
    skipped = 0
    lines: list[str] = []
    for item in pending:
        key = item["key"]
        if key in seen:
            skipped += 1
            continue
        if added >= maximum:
            skipped += 1
            continue
        if not dry_run:
            try:
                await append_event(
                    agent_id=agent_id,
                    source_type=SOURCE_TYPE,
                    source_id=key,
                    event_type="stale_note",
                    status="pending",
                    severity="warning",
                    title=f"Unprocessed daily note: {key}",
                    body=(
                        f"{key} is still pending after "
                        f"{item['age_days']} days (dated {item['date']})."
                    ),
                    payload={
                        "key": key,
                        "note_date": item["date"],
                        "age_days": item["age_days"],
                    },
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Inbox push failed for %s: %s", key, exc)
                skipped += 1
                continue
        added += 1
        lines.append(f"- {key} ({item['age_days']}d)")

    verb = "would push" if dry_run else "pushed"
    header = (
        f"{len(pending)} stale daily note(s); {verb} {added}, "
        f"already reported {skipped} "
        f"(threshold {minimum}d, cooldown {cooldown}d)."
    )
    body = "\n".join([header] + lines[:maximum])
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=body)],
    )
