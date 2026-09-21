# -*- coding: utf-8 -*-
"""Explicit migration from Scroll history into the chat transcript."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agentscope.message import Msg

from ...schemas import Message
from ...utils.io_utils import read_json
from .models import ChatSpec, ChatsFile
from .transcript_catalog import TranscriptCatalog
from .utils import agentscope_msg_to_message

_MIGRATION_SCHEMA_VERSION = 1
_HISTORY_COLUMNS = (
    "seq, session_id, kind, role, name, content, tool_call_id, "
    "tool_state, blocks, metadata, created_at, dedup_key"
)


@dataclass(frozen=True)
class HistoryMessage:
    """One reconstructed AgentScope message and its source position."""

    seq: int
    session_id: str
    created_at: str | None
    message: Msg


@dataclass
class TranscriptMigrationResult:
    """Machine-readable summary for one migration attempt."""

    dry_run: bool
    fingerprint: str
    source_sessions: int = 0
    eligible_sessions: int = 0
    imported_sessions: int = 0
    imported_turns: int = 0
    imported_messages: int = 0
    skipped_unmapped: int = 0
    skipped_ambiguous: int = 0
    skipped_existing: int = 0
    already_imported: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


def _decode_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _tool_result_block(row: sqlite3.Row) -> dict[str, Any]:
    blocks = _decode_json(row["blocks"], [])
    if isinstance(blocks, list) and blocks:
        block = blocks[0]
        if isinstance(block, dict):
            return block
    return {
        "type": "tool_result",
        "id": row["tool_call_id"],
        "name": row["name"],
        "output": row["content"] or "",
        "state": row["tool_state"],
    }


def _insert_tool_result(message: Msg, block: dict[str, Any]) -> bool:
    call_id = block.get("id")
    if not call_id:
        return False
    validated = Msg(
        name=message.name,
        role=message.role,
        content=[block],
    ).content[0]
    for index, candidate in enumerate(message.content):
        if (
            getattr(candidate, "type", None) == "tool_call"
            and getattr(candidate, "id", None) == call_id
        ):
            message.content.insert(index + 1, validated)
            return True
    return False


def _message_from_row(row: sqlite3.Row) -> Msg:
    blocks = _decode_json(row["blocks"], [])
    if not isinstance(blocks, list):
        raise ValueError("history blocks must be a list")
    if not blocks and row["content"] is not None:
        blocks = [{"type": "text", "text": row["content"]}]
    metadata = _decode_json(row["metadata"], {})
    if not isinstance(metadata, dict):
        raise ValueError("history metadata must be an object")
    role = row["role"] or "assistant"
    kwargs: dict[str, Any] = {
        "id": row["dedup_key"] or f"history-{row['seq']}",
        "name": row["name"] or role,
        "role": role,
        "content": blocks,
        "metadata": metadata,
    }
    if row["created_at"] is not None:
        kwargs["created_at"] = row["created_at"]
    return Msg(**kwargs)


def _read_history(
    db_path: Path,
) -> tuple[dict[str, list[HistoryMessage]], str]:
    if not db_path.is_file():
        raise FileNotFoundError(f"history database not found: {db_path}")
    digest = hashlib.sha256()
    messages: dict[str, list[HistoryMessage]] = {}
    current: HistoryMessage | None = None
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"SELECT {_HISTORY_COLUMNS} FROM conversation_history "
            "ORDER BY session_id, seq",
        )
        for row in rows:
            digest.update(
                json.dumps(
                    dict(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            digest.update(b"\n")
            session_id = str(row["session_id"])
            if row["kind"] == "tool_result":
                block = _tool_result_block(row)
                if (
                    current is not None
                    and current.session_id == session_id
                    and _insert_tool_result(current.message, block)
                ):
                    continue
                row_message = Msg(
                    id=row["dedup_key"] or f"history-{row['seq']}",
                    name=row["name"] or "assistant",
                    role="assistant",
                    content=[block],
                    metadata=_decode_json(row["metadata"], {}),
                )
            else:
                row_message = _message_from_row(row)
            current = HistoryMessage(
                seq=int(row["seq"]),
                session_id=session_id,
                created_at=row["created_at"],
                message=row_message,
            )
            messages.setdefault(session_id, []).append(current)
    return messages, digest.hexdigest()


def _chat_mapping(chats_path: Path) -> dict[str, list[ChatSpec]]:
    if not chats_path.is_file():
        return {}
    registry = ChatsFile.model_validate(read_json(chats_path))
    mapping: dict[str, list[ChatSpec]] = {}
    for chat in registry.chats:
        mapping.setdefault(chat.session_id, []).append(chat)
    return mapping


def _existing_target_state(
    catalog_path: Path,
    *,
    source_identity: str,
    fingerprint: str,
) -> tuple[set[str], bool]:
    if not catalog_path.is_file():
        return set(), False
    uri = f"{catalog_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
        if "transcript_files" not in tables:
            return set(), False
        sessions = {
            str(row[0])
            for row in connection.execute(
                "SELECT session_id FROM transcript_files "
                "WHERE deleted_at IS NULL",
            )
        }
        if "transcript_imports" not in tables:
            return sessions, False
        imported = connection.execute(
            "SELECT 1 FROM transcript_imports WHERE source_kind = ? "
            "AND source_identity = ? AND fingerprint = ? "
            "AND schema_version = ?",
            (
                "history.db",
                source_identity,
                fingerprint,
                _MIGRATION_SCHEMA_VERSION,
            ),
        ).fetchone()
        return sessions, imported is not None


def _group_turns(
    messages: list[HistoryMessage],
) -> list[list[HistoryMessage]]:
    turns: list[list[HistoryMessage]] = []
    for message in messages:
        if not turns or message.message.role == "user":
            turns.append([])
        turns[-1].append(message)
    return turns


def _converted_messages(source: HistoryMessage) -> list[Message]:
    converted = agentscope_msg_to_message(source.message)
    return [
        message.model_copy(
            update={"id": f"history-{source.seq}-{index}"},
        ).completed()
        for index, message in enumerate(converted)
    ]


def migrate_history_transcript(  # pylint: disable=too-many-branches
    workspace_dir: Path,
    *,
    agent_id: str,
    dry_run: bool,
) -> TranscriptMigrationResult:
    """Import mapped ``history.db`` sessions without replacing live data."""
    workspace = workspace_dir.expanduser().resolve()
    history_path = workspace / "history.db"
    catalog_path = workspace / "transcript_catalog.db"
    source_identity = str(history_path.resolve())
    history, fingerprint = _read_history(history_path)
    chats = _chat_mapping(workspace / "chats.json")
    existing, already_imported = _existing_target_state(
        catalog_path,
        source_identity=source_identity,
        fingerprint=fingerprint,
    )
    result = TranscriptMigrationResult(
        dry_run=dry_run,
        fingerprint=fingerprint,
        source_sessions=len(history),
        already_imported=already_imported,
    )
    if already_imported:
        return result

    eligible: list[tuple[str, ChatSpec, list[HistoryMessage]]] = []
    for session_id, messages in history.items():
        candidates = chats.get(session_id, [])
        if not candidates:
            result.skipped_unmapped += 1
            continue
        if len(candidates) != 1:
            result.skipped_ambiguous += 1
            continue
        if session_id in existing:
            result.skipped_existing += 1
            continue
        eligible.append((session_id, candidates[0], messages))
    result.eligible_sessions = len(eligible)
    if dry_run:
        return result

    catalog = TranscriptCatalog(workspace, retention_days=0)
    try:
        for session_id, chat, messages in eligible:
            if catalog.has_session(session_id):
                result.skipped_existing += 1
                result.eligible_sessions -= 1
                continue
            turns: list[tuple[str, list[Message]]] = []
            for turn_index, turn in enumerate(_group_turns(messages)):
                turn_id = f"history-import-{turn_index}-{turn[0].seq}"
                converted: list[Message] = []
                for source in turn:
                    converted.extend(_converted_messages(source))
                turns.append((turn_id, converted))
            imported = catalog.import_history_if_missing(
                session_id=session_id,
                user_id=chat.user_id,
                channel=chat.channel,
                source=f"history_import:{agent_id}",
                turns=turns,
                source_complete=False,
            )
            if not imported:
                result.skipped_existing += 1
                result.eligible_sessions -= 1
                continue
            result.imported_sessions += 1
            result.imported_turns += len(turns)
            result.imported_messages += sum(
                len(turn_messages) for _, turn_messages in turns
            )
        catalog.record_import(
            source_kind="history.db",
            source_identity=source_identity,
            fingerprint=fingerprint,
            schema_version=_MIGRATION_SCHEMA_VERSION,
            result=result.as_dict(),
        )
    finally:
        catalog.close()
    return result


__all__ = ["TranscriptMigrationResult", "migrate_history_transcript"]
