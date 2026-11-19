# -*- coding: utf-8 -*-
"""Bounded, read-only search over visible conversation transcripts."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ...config.history_path import resolve_history_db_path
from ...constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    QWENPAW_USER_CONTENT_KEY,
    SCROLL_MEMORY_MESSAGE_TAG,
    SYNTHETIC_USER_MESSAGE_TAGS,
)
from ...utils.io_utils import run_sync_io
from .models import ChatSpec
from .session import session_filename, sanitize_filename
from .utils import clean_display_text

logger = logging.getLogger(__name__)

MAX_SCAN_BYTES = 64 * 1024 * 1024
MAX_SESSION_BYTES = 16 * 1024 * 1024
MAX_SCAN_SECONDS = 5.0
SNIPPET_CHARS = 240


class ChatSearchRequest(BaseModel):
    """Search the current agent's active, Console-visible conversations."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    mode: Literal["keyword", "agent"] = "keyword"
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)

    @field_validator("query")
    @classmethod
    def nonempty_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Search query must not be blank")
        return value

    @model_validator(mode="after")
    def keyword_pagination(self) -> "ChatSearchRequest":
        if self.mode == "agent" and self.offset:
            raise ValueError("Pagination is only available for keyword search")
        return self


class ChatSearchResult(BaseModel):
    """A server-verified conversation and its matching text."""

    chat: ChatSpec
    snippet: str
    role: Literal["user", "assistant"] | None = None
    message_id: str | None = None


class ChatSearchResponse(BaseModel):
    """Search results; partial indicates an incomplete corpus or agent run."""

    query: str
    mode: Literal["keyword", "agent"]
    results: list[ChatSearchResult]
    total: int
    has_more: bool = False
    queries: list[str] = Field(default_factory=list)
    partial: bool = False


@dataclass(frozen=True)
class TranscriptText:
    """Only text actually shown in user or assistant transcript messages."""

    text: str
    role: Literal["user", "assistant"]
    message_id: str | None = None


def visible_text(  # pylint: disable=too-many-return-statements
    message: object,
) -> TranscriptText | None:
    """Exclude reasoning, tool outputs and runtime-injected messages."""
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    if not isinstance(role, str) or role not in {"user", "assistant"}:
        return None
    metadata = message.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    tag = metadata.get(QWENPAW_MESSAGE_TAG_KEY)
    tag = tag if isinstance(tag, str) else ""
    if tag == SCROLL_MEMORY_MESSAGE_TAG or (
        role == "user"
        and (
            tag in SYNTHETIC_USER_MESSAGE_TAGS
            or message.get("name") == "visual_history"
        )
    ):
        return None
    content = message.get("content", "")
    original = metadata.get(QWENPAW_USER_CONTENT_KEY)
    if role == "user" and isinstance(original, list) and original:
        content = original
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type", "text") == "text"
            and isinstance(block.get("text"), str)
        )
    else:
        return None
    if (
        role == "user"
        and message.get("name") == "memory"
        and text.lstrip().startswith("<system-info>")
        and "[context compressed]" in text
    ):
        return None
    text = clean_display_text(text, role).strip()
    if not text:
        return None
    message_id = message.get("id")
    return TranscriptText(
        text=text,
        role="user" if role == "user" else "assistant",
        message_id=message_id if isinstance(message_id, str) else None,
    )


def _snapshot_messages(state: object) -> tuple[list[TranscriptText], set[str]]:
    if not isinstance(state, dict):
        return [], set()
    agent = state.get("agent")
    if not isinstance(agent, dict):
        return [], set()
    current = agent.get("state")
    raw = current.get("context") if isinstance(current, dict) else None
    if not isinstance(raw, list) or not raw:
        memory = agent.get("memory")
        raw = memory.get("content", []) if isinstance(memory, dict) else []
    if not isinstance(raw, list):
        return [], set()
    messages = []
    ids = set()
    for item in raw:
        if isinstance(item, list) and len(item) == 2:
            item = item[0]
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.add(item["id"])
        text = visible_text(item)
        if text is not None:
            messages.append(text)
    return messages, ids


def _snippet(text: str, query: str) -> str:
    """Center excerpts on a literal Unicode-insensitive match."""
    folded = text.casefold()
    match = folded.find(query.casefold())
    # Case folding can expand characters (ß -> ss). Map the hit back to
    # the original text instead of using a folded-string offset directly.
    position = 0
    if match > 0:
        folded_position = 0
        for position, char in enumerate(text):
            folded_position += len(char.casefold())
            if folded_position > match:
                break
    start = max(0, position - 70)
    end = min(len(text), start + SNIPPET_CHARS)
    return (
        ("…" if start else "")
        + text[start:end]
        + ("…" if end < len(text) else "")
    )


@dataclass
class SearchCorpus:
    """One bounded snapshot reused by all steps of an agent search."""

    chats: list[ChatSpec]
    messages: dict[str, list[TranscriptText]] = field(default_factory=dict)
    snapshot_ids: dict[str, set[str]] = field(default_factory=dict)
    partial: bool = False

    def search(self, query: str) -> list[ChatSearchResult]:
        """Return one evidence excerpt per conversation, newest first."""
        needle = query.casefold()
        results = []
        for chat in self.chats:
            match = next(
                (
                    item
                    for item in reversed(self.messages.get(chat.id, []))
                    if needle in item.text.casefold()
                ),
                None,
            )
            if match is not None:
                results.append(
                    ChatSearchResult(
                        chat=chat,
                        snippet=_snippet(match.text, query),
                        role=match.role,
                        message_id=match.message_id,
                    ),
                )
            elif needle in chat.name.casefold():
                results.append(
                    ChatSearchResult(
                        chat=chat,
                        snippet=_snippet(chat.name, query),
                    ),
                )
        return results


@dataclass
class _ScanBudget:
    remaining: int = MAX_SCAN_BYTES
    deadline: float = field(
        default_factory=lambda: time.monotonic() + MAX_SCAN_SECONDS,
    )

    def exhausted(self) -> bool:
        return self.remaining <= 0 or time.monotonic() >= self.deadline


def _session_path(root: Path, chat: ChatSpec) -> Path | None:
    """Resolve existing current/legacy snapshots without migrating them."""
    filename = session_filename(chat.session_id, chat.user_id)
    channel = sanitize_filename(chat.channel)
    candidates = [root / channel / filename, root / filename]
    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            continue
        if resolved.is_file():
            return resolved
    return None


def _read_snapshots(corpus: SearchCorpus, root: Path, budget: _ScanBudget):
    for chat in corpus.chats:
        if budget.exhausted():
            corpus.partial = True
            break
        try:
            path = _session_path(root, chat)
            if path is None:
                continue
            size = path.stat().st_size
            cap = min(MAX_SESSION_BYTES, budget.remaining)
            if size > cap:
                corpus.partial = True
                continue
            with path.open("rb") as stream:
                raw = stream.read(cap + 1)
            budget.remaining -= len(raw)
            if len(raw) > cap:
                corpus.partial = True
                continue
            (
                corpus.messages[chat.id],
                corpus.snapshot_ids[chat.id],
            ) = _snapshot_messages(json.loads(raw))
        except (OSError, ValueError, TypeError):
            corpus.partial = True
            logger.debug("Cannot search session %s", chat.id, exc_info=True)


def _read_history(  # pylint: disable=too-many-branches,too-many-statements
    corpus: SearchCorpus,
    path: Path,
    agent_id: str,
    budget: _ScanBudget,
):
    """Include Scroll turns evicted from JSON without creating a database."""
    if not path.is_file():
        return
    if budget.exhausted():
        corpus.partial = True
        return
    by_session: dict[str, list[str]] = {}
    for chat in corpus.chats:
        by_session.setdefault(chat.session_id, []).append(chat.id)
    conn = None
    older: dict[str, list[TranscriptText]] = {}
    try:
        conn = sqlite3.connect(
            path.as_uri() + "?mode=ro",
            uri=True,
            timeout=0.2,
        )
        conn.row_factory = sqlite3.Row
        conn.set_progress_handler(lambda: int(budget.exhausted()), 1000)
        # Exact agent identity is essential when several workspaces share a
        # configured history DB. Never widen to NULL or another agent.
        seen = {
            chat_id: {(item.role, item.text) for item in items}
            for chat_id, items in corpus.messages.items()
        }
        snapshot_ids = corpus.snapshot_ids
        sessions = list(by_session)
        for start in range(0, len(sessions), 400):
            if budget.exhausted():
                corpus.partial = True
                break
            batch = sessions[start : start + 400]
            # Measure UTF-8 bytes in SQLite before materializing blobs in
            # Python. A media-heavy turn can otherwise exceed the entire
            # search budget in a single fetched row.
            row_bytes = " + ".join(
                f"length(CAST(coalesce({column}, '') AS BLOB))"
                for column in ("content", "blocks", "metadata")
            )
            fields = ", ".join(
                f"CASE WHEN ({row_bytes}) <= {MAX_SESSION_BYTES} "
                f"THEN {column} END AS {column}"
                for column in ("content", "blocks", "metadata")
            )
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                f"SELECT session_id, role, name, dedup_key, {fields}, "
                f"({row_bytes}) AS row_bytes FROM conversation_history "
                f"WHERE agent_id = ? AND session_id IN ({placeholders}) "
                "AND role IN ('user', 'assistant') "
                "AND kind != 'tool_result' ORDER BY seq DESC",
                (agent_id, *batch),
            )
            for row in rows:
                if budget.exhausted():
                    corpus.partial = True
                    break
                if row["row_bytes"] > MAX_SESSION_BYTES:
                    corpus.partial = True
                    continue
                budget.remaining -= row["row_bytes"]
                if budget.remaining < 0:
                    corpus.partial = True
                    break
                try:
                    blocks = (
                        json.loads(row["blocks"]) if row["blocks"] else None
                    )
                    metadata = json.loads(row["metadata"] or "{}")
                except (ValueError, TypeError):
                    corpus.partial = True
                    continue
                item = visible_text(
                    {
                        "id": row["dedup_key"],
                        "role": row["role"],
                        "name": row["name"],
                        "content": (
                            blocks if blocks is not None else row["content"]
                        ),
                        "metadata": metadata,
                    },
                )
                if item is None:
                    continue
                for chat_id in by_session[row["session_id"]]:
                    if item.message_id in snapshot_ids.get(chat_id, set()):
                        continue
                    keys = seen.setdefault(chat_id, set())
                    key = (item.role, item.text)
                    if key not in keys:
                        keys.add(key)
                        older.setdefault(chat_id, []).append(item)
    except (OSError, sqlite3.Error):
        corpus.partial = True
        logger.debug(
            "Cannot search durable conversation history",
            exc_info=True,
        )
    finally:
        for chat_id, items in older.items():
            corpus.messages[chat_id] = list(reversed(items)) + (
                corpus.messages.get(chat_id, [])
            )
        if conn is not None:
            conn.close()


async def load_search_corpus(workspace, chats: list[ChatSpec]) -> SearchCorpus:
    """Offload filesystem and SQLite reads, parsing and display cleanup."""

    def load() -> SearchCorpus:
        corpus = SearchCorpus(
            chats=sorted(
                chats,
                key=lambda chat: (chat.updated_at, chat.id),
                reverse=True,
            ),
        )
        budget = _ScanBudget()
        _read_snapshots(
            corpus,
            Path(workspace.session.save_dir).resolve(),
            budget,
        )
        config = workspace.config
        path = resolve_history_db_path(
            workspace.workspace_dir,
            config.running.light_context_config.scroll_config.db_filename,
        )
        _read_history(corpus, path, workspace.agent_id, budget)
        return corpus

    return await run_sync_io(load)


def keyword_search(corpus: SearchCorpus, payload: ChatSearchRequest):
    """Paginate complete conversation matches without involving a model."""
    results = corpus.search(payload.query)
    end = payload.offset + payload.limit
    return ChatSearchResponse(
        query=payload.query,
        mode=payload.mode,
        results=results[payload.offset : end],
        total=len(results),
        has_more=end < len(results),
        queries=[payload.query],
        partial=corpus.partial,
    )
