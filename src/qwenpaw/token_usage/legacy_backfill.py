# -*- coding: utf-8 -*-
"""从 Legacy 会话逐轮元数据恢复可可靠归属的用量事实。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from .turn_usage import TURN_USAGE_META_KEY


@dataclass(frozen=True, slots=True)
class LegacyUsageCandidate:
    record_id: UUID
    occurred_at: datetime
    user_id: UUID
    agent_key: str
    conversation_id: UUID
    provider_key: str
    model_key: str
    prompt_tokens: int
    completion_tokens: int


def _items(raw: object) -> list[dict]:
    if isinstance(raw, dict):
        raw = raw.get("chats", raw)
    if isinstance(raw, dict):
        raw = list(raw.values())
    return (
        [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, list)
        else []
    )


def _timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def collect_usage_candidates(working_dir: Path) -> list[LegacyUsageCandidate]:
    """只读取同时具备用户、会话、Provider 和模型归属的精确逐轮用量。"""
    candidates: dict[UUID, LegacyUsageCandidate] = {}
    workspaces = working_dir / "workspaces"
    if not workspaces.is_dir():
        return []
    for workspace in workspaces.iterdir():
        chats_path = workspace / "chats.json"
        if not workspace.is_dir() or not chats_path.is_file():
            continue
        try:
            chats = _items(json.loads(chats_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        for chat in chats:
            try:
                user_id = UUID(str(chat.get("user_id")))
                conversation_id = UUID(str(chat.get("id")))
            except (TypeError, ValueError):
                continue
            session_id = str(chat.get("session_id") or "")
            channel = str(chat.get("channel") or "console")
            if not session_id:
                continue
            matches = list(
                (workspace / "sessions" / channel).glob(f"{user_id}_{session_id}*.json")
            )
            if not matches:
                continue
            session_path = max(matches, key=lambda item: item.stat().st_mtime_ns)
            try:
                state = json.loads(session_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            context = ((state.get("agent") or {}).get("state") or {}).get(
                "context"
            ) or []
            for message in context:
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                usage = (
                    (message.get("metadata") or {}).get(TURN_USAGE_META_KEY) or {}
                ).get("usage") or {}
                provider_key = str(usage.get("provider_id") or "")
                model_key = str(usage.get("model_name") or "")
                occurred_at = _timestamp(message.get("created_at"))
                message_id = str(message.get("id") or "")
                try:
                    prompt_tokens = int(usage.get("prompt_tokens") or 0)
                    completion_tokens = int(usage.get("completion_tokens") or 0)
                except (TypeError, ValueError):
                    continue
                if (
                    not provider_key
                    or not model_key
                    or occurred_at is None
                    or not message_id
                    or prompt_tokens < 0
                    or completion_tokens < 0
                    or prompt_tokens + completion_tokens <= 0
                ):
                    continue
                record_id = uuid5(
                    NAMESPACE_URL,
                    "qwenpaw:usage-backfill:"
                    f"{workspace.name}:{conversation_id}:{message_id}",
                )
                candidates[record_id] = LegacyUsageCandidate(
                    record_id=record_id,
                    occurred_at=occurred_at,
                    user_id=user_id,
                    agent_key=workspace.name,
                    conversation_id=conversation_id,
                    provider_key=provider_key,
                    model_key=model_key,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
    return sorted(
        candidates.values(), key=lambda item: (item.occurred_at, item.record_id)
    )


__all__ = ["LegacyUsageCandidate", "collect_usage_candidates"]
