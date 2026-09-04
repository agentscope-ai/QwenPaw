# -*- coding: utf-8 -*-
"""Bounded, read-only fallback reader for Codex rollout JSONL files."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator, Mapping

from ..events import HarnessHistoryItem, HarnessHistoryKind

_UUID_PATTERN = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_MAX_HISTORY_BYTES = 64 * 1024 * 1024
_MAX_HISTORY_ITEMS = 20_000
_MAX_LINE_BYTES = 4 * 1024 * 1024
_MAX_HEADER_LINE_BYTES = 1024 * 1024
_MAX_HEADER_LINES = 64
_MAX_INDEX_FILES = 10_000
_EVENT_KINDS = {
    "user_message": HarnessHistoryKind.USER,
    "agent_message": HarnessHistoryKind.MESSAGE,
    "agent_reasoning": HarnessHistoryKind.REASONING,
}
_TOOL_CALL_TYPES = {
    "custom_tool_call",
    "function_call",
    "local_shell_call",
    "computer_call",
    "web_search_call",
}
_TOOL_OUTPUT_TYPES = {
    "custom_tool_call_output",
    "function_call_output",
    "local_shell_call_output",
    "computer_call_output",
}


def _source_label(value: Any) -> str:
    """Return a stable label for a serialized Codex source variant."""
    if isinstance(value, str):
        return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
    if not isinstance(value, Mapping):
        return "unknown"
    key, child = next(iter(value.items()), ("unknown", None))
    label = _source_label(key)
    return _source_label(child) if label == "other" else label


def codex_non_root_session_kind(metadata: Mapping[str, Any]) -> str:
    """Classify non-root sessions structurally, never by message text."""
    source = metadata.get("source")
    if isinstance(source, Mapping):
        for raw_key, value in source.items():
            key = _source_label(raw_key)
            if key == "internal":
                return f"internal:{_source_label(value)}"
            if key in {"subagent", "sub_agent"}:
                return f"subagent:{_source_label(value)}"
    elif isinstance(source, str):
        label = _source_label(source)
        if label.startswith(("internal", "subagent", "sub_agent")):
            return label

    thread_source = metadata.get("thread_source")
    if thread_source is None:
        thread_source = metadata.get("threadSource")
    label = _source_label(thread_source)
    if label in {
        "subagent",
        "sub_agent",
        "memory_consolidation",
        "automation",
    }:
        return label
    return ""


@dataclass(frozen=True)
class CodexRolloutRecord:
    """Small index entry for one local Codex rollout."""

    thread_id: str
    path: Path
    cwd: str = ""
    title: str = ""
    created_at: str = ""
    updated_at: str = ""
    non_root_kind: str = ""
    parent_thread_id: str = ""
    lineage_paths: tuple[Path, ...] = ()

    def as_thread(self) -> dict[str, Any]:
        """Return app-server-compatible thread metadata."""
        return {
            "id": self.thread_id,
            "preview": self.title or f"Codex {self.thread_id[:8]}",
            "cwd": self.cwd,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "rolloutPath": str(self.path),
            "rolloutLineageLength": len(self.paths),
            "source": "codex-rollout-jsonl",
            "parentThreadId": self.parent_thread_id or None,
        }

    @property
    def paths(self) -> tuple[Path, ...]:
        """Return every rollout segment in chronological order."""
        return self.lineage_paths or (self.path,)


@dataclass
class _RolloutMetadataState:
    """Mutable metadata accumulated while scanning one rollout."""

    thread_id: str
    cwd: str = ""
    title: str = ""
    created_at: str = ""
    updated_at: str = ""
    non_root_kind: str = ""
    parent_thread_id: str = ""
    metadata_seen: bool = False

    def update(self, entry: dict[str, Any]) -> None:
        """Merge metadata carried by one rollout entry."""
        if timestamp := str(entry.get("timestamp") or ""):
            self.created_at = self.created_at or timestamp
            self.updated_at = timestamp
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return
        entry_type = str(entry.get("type") or "")
        if entry_type == "session_meta":
            if self.metadata_seen:
                return
            self.metadata_seen = True
            thread_id = str(
                payload.get("id")
                or payload.get("session_id")
                or self.thread_id,
            )
            self.thread_id = thread_id
            self.cwd = str(payload.get("cwd") or self.cwd)
            self.created_at = str(
                payload.get("timestamp") or self.created_at,
            )
            self.parent_thread_id = str(
                payload.get("parent_thread_id")
                or payload.get("parentThreadId")
                or self.parent_thread_id,
            )
            self.non_root_kind = (
                codex_non_root_session_kind(payload) or self.non_root_kind
            )
        elif entry_type == "turn_context":
            self.cwd = str(payload.get("cwd") or self.cwd)
        elif (
            not self.title
            and entry_type == "event_msg"
            and payload.get("type") == "user_message"
        ):
            self.title = _visible_text(payload)[:200]


class CodexRolloutReader:
    """Index and normalize local Codex JSONL without changing source data."""

    def __init__(self, codex_home: Path | None = None) -> None:
        configured = os.environ.get("CODEX_HOME", "").strip()
        self.codex_home = (
            codex_home
            or (Path(configured).expanduser() if configured else None)
            or (Path.home() / ".codex")
        )
        self._records: dict[str, CodexRolloutRecord] | None = None
        self.index_truncated = False

    def list_threads(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return newest user-facing root rollout metadata records."""
        records = self._ordered_records(non_root=False)
        return [item.as_thread() for item in records[: max(0, limit)]]

    def list_non_root_thread_ids(self, *, limit: int = 5000) -> list[str]:
        """Return bounded child/internal IDs for prior-import cleanup."""
        records = self._ordered_records(non_root=True)
        return [item.thread_id for item in records[: max(0, limit)]]

    def _ordered_records(self, *, non_root: bool) -> list[CodexRolloutRecord]:
        return sorted(
            (
                item
                for item in self._index().values()
                if bool(item.non_root_kind) is non_root
            ),
            key=lambda item: (item.updated_at, str(item.path)),
            reverse=True,
        )

    def read_thread(self, thread_id: str) -> list[HarnessHistoryItem]:
        """Normalize visible chat and tool events from one rollout."""
        record = self._index().get(thread_id)
        if record is None:
            raise FileNotFoundError(f"Codex rollout not found: {thread_id}")
        history: list[HarnessHistoryItem] = []
        seen: set[tuple[str, str]] = set()
        total_bytes = 0
        for path in record.paths:
            try:
                total_bytes += path.stat().st_size
            except OSError as exc:
                raise FileNotFoundError(path) from exc
            if total_bytes > _MAX_HISTORY_BYTES:
                raise ValueError(
                    f"Codex rollout exceeds its safety limit: {path.name}",
                )
            for item in _read_rollout_history(path):
                stable_id = item.item_id
                key = (item.kind.value, stable_id)
                if stable_id:
                    if key in seen:
                        continue
                    seen.add(key)
                history.append(item)
                if len(history) > _MAX_HISTORY_ITEMS:
                    raise ValueError(
                        "Codex rollout exceeds its item safety limit: "
                        f"{path.name}",
                    )
        return history

    def skill_records(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Find local Codex/Agents/Plugin Skills
        when app-server is unavailable."""
        roots = [
            self.codex_home / "skills",
            self.codex_home / "plugins" / "cache",
            Path.home() / ".agents" / "skills",
        ]
        records: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for root in roots:
            if not root.is_dir():
                continue
            try:
                for path in root.rglob("SKILL.md"):
                    if len(records) >= limit:
                        return records
                    if path.is_symlink() or not path.is_file():
                        continue
                    resolved = path.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    records.append(
                        {
                            "name": resolved.parent.name,
                            "description": "",
                            "path": str(resolved),
                            "scope": "local-fallback",
                        },
                    )
            except OSError:
                continue
        return records

    def _index(self) -> dict[str, CodexRolloutRecord]:
        if self._records is None:
            self._records = {}
            indexed = 0
            for root in (
                self.codex_home / "sessions",
                self.codex_home / "archived_sessions",
            ):
                if not root.is_dir():
                    continue
                for path in root.rglob("*.jsonl"):
                    indexed += 1
                    if indexed > _MAX_INDEX_FILES:
                        self.index_truncated = True
                        break
                    record = _read_rollout_metadata(path)
                    if record is None:
                        continue
                    existing = self._records.get(record.thread_id)
                    if existing is None:
                        self._records[record.thread_id] = record
                        continue
                    lineage = tuple(
                        sorted({*existing.paths, *record.paths}, key=str),
                    )
                    latest = max(
                        (record, existing),
                        key=lambda item: item.updated_at,
                    )
                    self._records[record.thread_id] = replace(
                        latest,
                        created_at=min(
                            existing.created_at or record.created_at,
                            record.created_at or existing.created_at,
                        ),
                        non_root_kind=existing.non_root_kind
                        or record.non_root_kind,
                        parent_thread_id=(
                            latest.parent_thread_id
                            or existing.parent_thread_id
                            or record.parent_thread_id
                        ),
                        lineage_paths=lineage,
                    )
                if self.index_truncated:
                    break
        return self._records


def _read_rollout_metadata(path: Path) -> CodexRolloutRecord | None:
    try:
        if not path.is_file():
            return None
    except OSError:
        return None
    match = _UUID_PATTERN.search(path.stem)
    state = _RolloutMetadataState(match.group(1) if match else "")
    try:
        with path.open("rb") as stream:
            for _, entry in _jsonl_entries(
                stream,
                limit=_MAX_HEADER_LINES,
                max_line_bytes=_MAX_HEADER_LINE_BYTES,
            ):
                state.update(entry)
    except (OSError, ValueError):
        return None
    if not state.thread_id:
        return None
    return CodexRolloutRecord(
        thread_id=state.thread_id,
        path=path.resolve(),
        cwd=state.cwd,
        title=" ".join(state.title.split()),
        created_at=state.created_at,
        updated_at=state.updated_at or state.created_at,
        non_root_kind=state.non_root_kind,
        parent_thread_id=state.parent_thread_id,
    )


def _read_rollout_history(path: Path) -> list[HarnessHistoryItem]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    if size > _MAX_HISTORY_BYTES:
        raise ValueError(
            f"Codex rollout exceeds its safety limit: {path.name}",
        )
    history: list[HarnessHistoryItem] = []
    with path.open("rb") as stream:
        for _, entry in _jsonl_entries(stream):
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            item = _history_item(
                str(entry.get("type") or ""),
                payload,
                str(entry.get("timestamp") or ""),
            )
            history.extend(item)
    return history


def _jsonl_entries(
    stream: Any,
    *,
    limit: int | None = None,
    max_line_bytes: int = _MAX_LINE_BYTES,
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield valid, bounded JSON objects from a rollout stream."""
    for index, raw_line in enumerate(stream, start=1):
        if limit is not None and index > limit:
            break
        if len(raw_line) > max_line_bytes:
            raise ValueError(
                f"Codex rollout line {index} exceeds its safety limit",
            )
        try:
            entry = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(entry, dict):
            yield index, entry


def _history_item(
    entry_type: str,
    payload: dict[str, Any],
    timestamp: str,
) -> list[HarnessHistoryItem]:
    payload_type = str(payload.get("type") or "")
    item_id = str(
        payload.get("id")
        or payload.get("call_id")
        or _fallback_item_id(entry_type, payload, timestamp),
    )
    if entry_type == "event_msg":
        kind = _EVENT_KINDS.get(payload_type)
        return _text_item(kind, payload, item_id) if kind is not None else []
    if entry_type != "response_item":
        return []
    if payload_type in _TOOL_CALL_TYPES:
        tool_name = str(
            payload.get("name")
            or (
                "shell" if payload_type == "local_shell_call" else payload_type
            ),
        )
        arguments = (
            payload.get("input")
            if "input" in payload
            else payload.get("arguments", payload.get("action", {}))
        )
        return [
            HarnessHistoryItem(
                kind=HarnessHistoryKind.TOOL_CALL,
                item_id=item_id,
                tool_name=tool_name,
                data={"arguments": arguments, "provider_type": payload_type},
            ),
        ]
    if payload_type in _TOOL_OUTPUT_TYPES:
        return [
            HarnessHistoryItem(
                kind=HarnessHistoryKind.TOOL_OUTPUT,
                text=_visible_text(payload),
                item_id=item_id,
                data={"provider_type": payload_type},
            ),
        ]
    return []


def _fallback_item_id(
    entry_type: str,
    payload: dict[str, Any],
    timestamp: str,
) -> str:
    """Build a stable ID for copied lineage events lacking provider IDs."""
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        serialized = repr(payload)
    digest = hashlib.sha256(
        f"{timestamp}\0{entry_type}\0{serialized}".encode(
            "utf-8",
            errors="replace",
        ),
    ).hexdigest()[:24]
    return f"rollout-{digest}"


def _text_item(
    kind: HarnessHistoryKind,
    payload: dict[str, Any],
    item_id: str,
) -> list[HarnessHistoryItem]:
    text = _visible_text(payload)
    if not text:
        return []
    return [HarnessHistoryItem(kind=kind, text=text, item_id=item_id)]


def _visible_text(payload: dict[str, Any]) -> str:
    for key in ("message", "text", "output"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        values: list[str] = []
        for block in content:
            if isinstance(block, str):
                values.append(block)
            elif isinstance(block, dict):
                value = block.get("text") or block.get("output_text")
                if value:
                    values.append(str(value))
        return "\n".join(values)
    if payload.get("output") is not None:
        try:
            return json.dumps(payload["output"], ensure_ascii=False)
        except (TypeError, ValueError):
            return str(payload["output"])
    return ""
