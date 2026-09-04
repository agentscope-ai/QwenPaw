# -*- coding: utf-8 -*-
"""Read Qoder SDK/IDE transcripts and optional UI indexes."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import unquote, urlparse

from ...harnesses.events import (
    HarnessHistoryItem,
    HarnessHistoryKind,
)
from ..models import SourceSession
from ._utils import find_nested_value, parse_datetime

_HISTORY_PREFIX = "lingma.chat.localHistory."
_MODE_PREFIX = "chat.chatMode.session."
_QUEST_SNAPSHOT_KEY = "aicoding.questTaskListSnapshot"
_CWD_KEYS = (
    "cwd",
    "directory",
    "project_path",
    "projectPath",
    "filePath",
    "workspaceUri",
    "folderUri",
    "folder",
)
_MAX_TRANSCRIPT_BYTES = 64 * 1024 * 1024
_MAX_TRANSCRIPT_LINE_BYTES = 4 * 1024 * 1024
_MAX_TRANSCRIPT_LINES = 100_000
_MAX_HISTORY_ITEMS = 50_000
MAX_DISCOVERED_TRANSCRIPTS = 5_000
_MAX_SCANNED_TRANSCRIPTS = 10_000


@dataclass(frozen=True)
class QoderTranscript:
    """One candidate Qoder JSONL transcript."""

    source_id: str
    path: Path
    layout: str
    modified_at: datetime


@dataclass(frozen=True)
class _HistoryInfo:
    title: str = ""
    cwd: str = ""
    updated_at: datetime | None = None
    quest: bool = False


@dataclass(frozen=True)
class QoderQuestInfo:
    """Quest task metadata joined to its execution transcript."""

    task_id: str = ""
    title: str = ""
    cwd: str = ""
    status: str = ""
    quest_type: str = ""
    execution_mode: str = ""
    design_session_id: str = ""


@dataclass
class QoderIndex:
    """Supplemental Qoder UI metadata keyed by execution session id."""

    history: dict[str, _HistoryInfo] = field(default_factory=dict)
    modes: dict[str, str] = field(default_factory=dict)
    quests: dict[str, QoderQuestInfo] = field(default_factory=dict)


def default_qoder_user_data(
    home: Path | None = None,
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return Qoder's platform-specific ``User`` data directory."""
    user_home = home or Path.home()
    platform_value = platform_name or sys.platform
    environment = environ if environ is not None else os.environ
    configured = str(environment.get("QODER_USER_DATA_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser()
    if platform_value == "darwin":
        return user_home / "Library" / "Application Support" / "Qoder" / "User"
    if platform_value == "win32":
        app_data = environment.get("APPDATA")
        base = (
            Path(app_data) if app_data else user_home / "AppData" / "Roaming"
        )
        return base / "Qoder" / "User"
    config_home = environment.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else user_home / ".config"
    return base / "Qoder" / "User"


def discover_qoder_transcripts(qoder_home: Path) -> list[QoderTranscript]:
    """Discover IDE ``transcript`` and legacy SDK JSONL layouts."""
    projects = qoder_home.expanduser() / "projects"
    if not projects.is_dir() or projects.is_symlink():
        return []
    candidates: list[QoderTranscript] = []
    scanned = 0
    try:
        project_dirs = sorted(projects.iterdir())
    except OSError:
        return []
    for project in project_dirs:
        if project.is_symlink() or not project.is_dir():
            continue
        for directory, layout in (
            (project / "transcript", "ide"),
            (project, "sdk"),
        ):
            for candidate in _transcripts_in(directory, layout):
                scanned += 1
                if scanned > _MAX_SCANNED_TRANSCRIPTS:
                    break
                candidates.append(candidate)
            if scanned > _MAX_SCANNED_TRANSCRIPTS:
                break
        if scanned > _MAX_SCANNED_TRANSCRIPTS:
            break

    # A copied/renamed project can contain the same session. Prefer the IDE
    # layout and then the newest copy, matching Qoder SDK's id de-duplication.
    by_id: dict[str, QoderTranscript] = {}
    for candidate in candidates:
        current = by_id.get(candidate.source_id)
        if current is None or _candidate_rank(candidate) > _candidate_rank(
            current,
        ):
            by_id[candidate.source_id] = candidate
    return sorted(
        by_id.values(),
        key=lambda item: item.modified_at,
        reverse=True,
    )[:MAX_DISCOVERED_TRANSCRIPTS]


def _transcripts_in(directory: Path, layout: str) -> Iterator[QoderTranscript]:
    if not directory.is_dir() or directory.is_symlink():
        return
    try:
        for path in directory.glob("*.jsonl"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                modified_at = datetime.fromtimestamp(
                    path.stat().st_mtime,
                ).astimezone()
            except OSError:
                continue
            yield QoderTranscript(
                source_id=path.name[: -len(".jsonl")],
                path=path,
                layout=layout,
                modified_at=modified_at,
            )
    except OSError:
        return


def _candidate_rank(candidate: QoderTranscript) -> tuple[int, datetime]:
    return (1 if candidate.layout == "ide" else 0, candidate.modified_at)


def load_qoder_index(
    user_data: Path | None = None,
) -> tuple[QoderIndex, list[str]]:
    """Read titles, modes and Quest task metadata from Qoder's SQLite DB."""
    root = (user_data or default_qoder_user_data()).expanduser()
    database = root / "globalStorage" / "state.vscdb"
    index = QoderIndex()
    if not database.is_file() or database.is_symlink():
        return index, []
    try:
        uri = f"{database.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute(
                "SELECT key, value FROM ItemTable "
                "WHERE key LIKE ? OR key LIKE ? OR key = ?",
                (
                    f"{_HISTORY_PREFIX}%",
                    f"{_MODE_PREFIX}%",
                    _QUEST_SNAPSHOT_KEY,
                ),
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        return index, [f"Could not read Qoder UI history index: {exc}"]

    for key, value in rows:
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if key.startswith(_HISTORY_PREFIX):
            _add_local_history(index, key, value)
        elif key.startswith(_MODE_PREFIX):
            session_id = key.removeprefix(_MODE_PREFIX)
            mode = _string_value(value)
            if session_id and mode:
                index.modes[session_id] = mode
        elif key == _QUEST_SNAPSHOT_KEY:
            _add_quest_snapshot(index, value)
    return index, []


def _json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _string_value(value: str) -> str:
    decoded = _json_value(value)
    if isinstance(decoded, str):
        return decoded
    return value.strip().strip('"')


def _add_local_history(index: QoderIndex, key: str, value: str) -> None:
    decoded = _json_value(value)
    if not isinstance(decoded, list):
        return
    is_quest = key.endswith(".quest")
    for item in decoded:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("sessionId") or item.get("id") or "")
        if not session_id:
            continue
        info = _HistoryInfo(
            title=str(item.get("title") or ""),
            cwd=_cwd_in_value(item.get("context")),
            updated_at=_parse_timestamp(item.get("timestamp")),
            quest=is_quest,
        )
        current = index.history.get(session_id)
        if current is None or _history_rank(info) >= _history_rank(current):
            index.history[session_id] = info


def _history_rank(info: _HistoryInfo) -> tuple[datetime, int]:
    timestamp = info.updated_at or datetime.min.replace(tzinfo=timezone.utc)
    return timestamp, int(info.quest)


def _add_quest_snapshot(index: QoderIndex, value: str) -> None:
    decoded = _json_value(value)
    for item in _walk_dicts(decoded):
        session_id = str(item.get("executionSessionId") or "")
        if not session_id:
            continue
        quest = QoderQuestInfo(
            task_id=str(item.get("id") or item.get("taskId") or ""),
            title=str(item.get("name") or item.get("title") or ""),
            cwd=_cwd_in_value(item),
            status=str(item.get("status") or ""),
            quest_type=str(item.get("questType") or ""),
            execution_mode=str(item.get("executionMode") or ""),
            design_session_id=str(item.get("designSessionId") or ""),
        )
        index.quests[session_id] = quest


def _walk_dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _cwd_in_value(value: Any) -> str:
    return find_nested_value(value, _CWD_KEYS, _absolute_path)


def _absolute_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    raw = value.strip()
    if raw.startswith("file:"):
        parsed = urlparse(raw)
        raw = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in {"", "localhost"}:
            raw = f"//{parsed.netloc}{raw}"
    path = Path(raw).expanduser()
    return str(path) if path.is_absolute() else ""


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and abs(value) >= 100_000_000_000:
        value = value / 1000
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
        value = number / 1000 if number >= 100_000_000_000 else number
    return parse_datetime(value)


def _skip_transcript(
    source_id: str,
    reason: str,
) -> tuple[None, list[str], bool]:
    return None, [f"Skipped Qoder session {source_id}: {reason}."], False


# pylint: disable=too-many-return-statements
# pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
def read_qoder_transcript(
    transcript: QoderTranscript,
    index: QoderIndex,
) -> tuple[SourceSession | None, list[str], bool]:
    """Parse one Qoder transcript into a provider-neutral conversation."""
    history: list[HarnessHistoryItem] = []
    warnings: list[str] = []
    timestamps: list[datetime] = []
    source_id = transcript.source_id
    cwd = ""
    mode = ""
    session_type = ""
    first_user_text = ""
    malformed = 0
    try:
        source_path = transcript.path
        if source_path.stat().st_size > _MAX_TRANSCRIPT_BYTES:
            return _skip_transcript(source_id, "file is too large")
        with source_path.open("rb") as stream:
            for line_number in range(1, _MAX_TRANSCRIPT_LINES + 1):
                line = stream.readline(_MAX_TRANSCRIPT_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > _MAX_TRANSCRIPT_LINE_BYTES:
                    return _skip_transcript(
                        source_id,
                        f"line {line_number} is too large",
                    )
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(raw, dict):
                    continue
                source_id = str(
                    raw.get("sessionId") or raw.get("session_id") or source_id,
                )
                cwd = cwd or _cwd_in_value(raw)
                timestamp = _parse_timestamp(raw.get("timestamp"))
                if timestamp is not None:
                    timestamps.append(timestamp)
                if raw.get("type") == "session_meta":
                    content = raw.get("data", {}).get("content", {})
                    if isinstance(content, dict):
                        mode = str(content.get("mode") or mode)
                        session_type = str(
                            content.get("session_type") or session_type,
                        )
                items = _raw_history_items(raw)
                history.extend(items)
                if len(history) > _MAX_HISTORY_ITEMS:
                    return _skip_transcript(source_id, "history is too large")
                if not first_user_text and raw.get("type") == "user":
                    first_user_text = _message_text(raw.get("message"))
            else:
                if stream.read(1):
                    return _skip_transcript(source_id, "too many JSONL lines")
    except OSError as exc:
        warning = f"Could not read Qoder session {source_id}: {exc}"
        return None, [warning], False

    if malformed:
        warnings.append(
            f"Qoder session {source_id} ignored {malformed} malformed "
            "JSONL line(s).",
        )
    if not source_id or not history:
        warnings.append(
            f"Skipped Qoder transcript {transcript.path.name} because it "
            "contains no supported conversation messages.",
        )
        return None, warnings, False

    conversational_kinds = {
        HarnessHistoryKind.USER,
        HarnessHistoryKind.MESSAGE,
        HarnessHistoryKind.REASONING,
    }
    has_conversation = False
    for item in history:
        if item.kind in conversational_kinds and item.text.strip():
            has_conversation = True
            break
    if not has_conversation:
        # Qoder writes each Experts/Agent child worker into the same
        # ``transcript`` directory as user-visible sessions. Those child
        # files contain only tool calls/results; the parent conversation
        # already preserves the worker name, role and final output.
        return None, warnings, True

    history_info = index.history.get(source_id, _HistoryInfo())
    quest = index.quests.get(source_id)
    mode = mode or index.modes.get(source_id, "")
    cwd = cwd or (quest.cwd if quest else "") or history_info.cwd
    title = (
        (quest.title if quest else "")
        or history_info.title
        or _title_from_text(first_user_text)
        or f"Qoder {source_id[:8]}"
    )
    metadata: dict[str, Any] = {
        "source": "qoder",
        "layout": transcript.layout,
        "source_path": str(transcript.path),
        "session_kind": (
            "quest" if quest is not None or history_info.quest else "editor"
        ),
    }
    if mode:
        metadata["mode"] = mode
    if session_type:
        metadata["qoder_session_type"] = session_type
    if quest is not None:
        metadata["quest"] = {
            "task_id": quest.task_id,
            "type": quest.quest_type,
            "status": quest.status,
            "execution_mode": quest.execution_mode,
            "design_session_id": quest.design_session_id,
        }
    created_at = min(timestamps) if timestamps else None
    updated_at = max(timestamps) if timestamps else history_info.updated_at
    return (
        SourceSession(
            source_id=source_id,
            title=_title_from_text(title)[:200],
            cwd=cwd,
            created_at=created_at,
            updated_at=updated_at or transcript.modified_at,
            history=history,
            metadata=metadata,
        ),
        warnings,
        False,
    )


def _raw_history_items(raw: dict[str, Any]) -> list[HarnessHistoryItem]:
    message = raw.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    blocks = content if isinstance(content, list) else []
    if isinstance(content, str):
        blocks = [{"type": "text", "text": content}]
    message_type = str(raw.get("type") or message.get("role") or "")
    message_id = str(raw.get("uuid") or "")
    history: list[HarnessHistoryItem] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        item_id = str(block.get("id") or block.get("tool_use_id") or "")
        if block_type == "text":
            history.append(
                HarnessHistoryItem(
                    kind=(
                        HarnessHistoryKind.USER
                        if message_type == "user"
                        else HarnessHistoryKind.MESSAGE
                    ),
                    item_id=message_id,
                    text=str(block.get("text") or ""),
                ),
            )
        elif block_type == "thinking":
            history.append(
                HarnessHistoryItem(
                    kind=HarnessHistoryKind.REASONING,
                    item_id=message_id,
                    text=str(block.get("thinking") or ""),
                ),
            )
        elif block_type == "tool_use":
            history.append(
                HarnessHistoryItem(
                    kind=HarnessHistoryKind.TOOL_CALL,
                    item_id=item_id,
                    tool_name=str(block.get("name") or "tool"),
                    data={"arguments": block.get("input") or {}},
                ),
            )
        elif block_type == "tool_result":
            history.append(
                HarnessHistoryItem(
                    kind=HarnessHistoryKind.TOOL_OUTPUT,
                    item_id=item_id,
                    text=_content_text(block.get("content")),
                    data={"is_error": bool(block.get("is_error"))},
                ),
            )
    return history


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _title_from_text(text: str) -> str:
    return " ".join(str(text).split())


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        values = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if value is not None:
                    values.append(str(value))
            else:
                values.append(str(item))
        return "\n".join(values)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False, default=str)
    return str(content)


__all__ = [
    "QoderIndex",
    "QoderQuestInfo",
    "QoderTranscript",
    "default_qoder_user_data",
    "discover_qoder_transcripts",
    "load_qoder_index",
    "read_qoder_transcript",
]
