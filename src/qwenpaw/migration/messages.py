"""遗留会话快照消息到 PostgreSQL 的安全幂等迁移。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text

from ..app.chats.models import ChatsFile
from ..app.chats.session import session_relative_paths
from ..constant import CHATS_FILE, WORKING_DIR
from .common import content_hash, migration_session, table
from .report import MigrationExecutionReport, MigrationRejectedItem


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _messages(value: object) -> list[object]:
    if not isinstance(value, dict):
        return []
    agent = value.get("agent")
    agent = agent if isinstance(agent, dict) else value
    state = agent.get("state")
    if isinstance(state, dict) and isinstance(state.get("context"), list):
        return state["context"]
    memory = agent.get("memory")
    if isinstance(memory, dict) and isinstance(memory.get("content"), list):
        return [
            item[0] if isinstance(item, list) and len(item) == 2 else item
            for item in memory["content"]
        ]
    return []


def _parts_hash(parts: list[tuple[str, bytes]]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for name, raw in sorted(parts):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _source_sessions(
    working_dir: Path,
) -> tuple[list[dict[str, object]], str, list[MigrationRejectedItem]]:
    workspaces = working_dir / "workspaces"
    if not workspaces.is_dir():
        return [], content_hash([]), []
    sources: list[dict[str, object]] = []
    parts: list[tuple[str, bytes]] = []
    rejected: list[MigrationRejectedItem] = []
    for workspace in sorted(path for path in workspaces.iterdir() if path.is_dir()):
        chats_path = workspace / CHATS_FILE
        sessions_dir = workspace / "sessions"
        if not chats_path.is_file() or not sessions_dir.is_dir():
            continue
        try:
            chats = ChatsFile.model_validate_json(chats_path.read_bytes()).chats
        except (OSError, UnicodeDecodeError, ValidationError, ValueError):
            rejected.append(
                MigrationRejectedItem(
                    code="invalid_conversation_registry",
                    source=f"work/workspaces/{workspace.name}/{CHATS_FILE}",
                    detail="会话清单无法解析，未映射对应消息快照",
                )
            )
            continue
        registry: dict[str, list[object]] = {}
        for chat in chats:
            for relative in session_relative_paths(
                chat.session_id, chat.user_id, chat.channel
            ):
                registry.setdefault(relative, []).append(chat)
        for path in sorted(sessions_dir.rglob("*.json")):
            relative = path.relative_to(sessions_dir)
            if any(part.startswith(".") for part in relative.parts):
                continue
            logical = (
                f"work/workspaces/{workspace.name}/sessions/{relative.as_posix()}"
            )
            try:
                raw = path.read_bytes()
                value = json.loads(raw.decode("utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
                rejected.append(
                    MigrationRejectedItem(
                        code="invalid_message_source",
                        source=logical,
                        detail="消息快照无法解析",
                    )
                )
                continue
            snapshot = _messages(value)
            if not snapshot:
                continue
            parts.append((logical, raw))
            candidates = registry.get(relative.as_posix(), [])
            if len(candidates) != 1:
                rejected.append(
                    MigrationRejectedItem(
                        code="ambiguous_message_conversation",
                        source=logical,
                        detail="消息快照无法唯一映射到会话",
                    )
                )
                continue
            sources.append(
                {
                    "source": logical,
                    "conversation_id": candidates[0].id,
                    "messages": snapshot,
                }
            )
    return sources, _parts_hash(parts), rejected


def _created_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        local_timezone = datetime.now().astimezone().tzinfo or UTC
        parsed = parsed.replace(tzinfo=local_timezone)
    return parsed.astimezone(UTC)


def _project(
    item: object, *, conversation_id: UUID, sequence: int, owner_id: UUID
) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None
    message_id = _uuid(item.get("id"))
    created_at = _created_at(item.get("created_at") or item.get("timestamp"))
    role = str(item.get("role") or "")
    if message_id is None or created_at is None or not role:
        return None
    return {
        "id": message_id,
        "conversation_id": conversation_id,
        "run_id": None,
        "sequence": sequence,
        "role": role,
        "message_type": "legacy_snapshot",
        "content": item,
        "status": "completed",
        "created_by": owner_id if role == "user" else None,
        "created_at": created_at,
    }


def _same_history(rows, expected: list[dict[str, object]]) -> bool:
    if len(rows) != len(expected):
        return False
    keys = tuple(expected[0]) if expected else ()
    return all(
        all(row[key] == item[key] for key in keys)
        for row, item in zip(rows, expected, strict=True)
    )


async def migrate_messages(
    *,
    working_dir: Path = WORKING_DIR,
    schema: str = "qwenpaw",
    session_factory=None,
) -> MigrationExecutionReport:
    """仅向空目标会话补录完整快照；已有历史整段保留。"""
    sources, source_hash, rejected = _source_sessions(working_dir)
    source_count = sum(len(source["messages"]) for source in sources)
    if not sources and not rejected:
        target_count, target_hash = await _target_snapshot(schema, session_factory)
        return MigrationExecutionReport(
            domain="messages",
            status="empty",
            execution_order=4,
            source_count=0,
            target_count=target_count,
            inserted_count=0,
            unchanged_count=0,
            source_hash=source_hash,
            target_hash=target_hash,
            transaction_committed=False,
        )

    conversations = table(schema, "conversations")
    messages = table(schema, "messages")
    inserted = unchanged = 0
    async with migration_session(session_factory) as session:
        owners = {
            row.id: row.owner_user_id
            for row in (
                await session.execute(
                    text(f"SELECT id,owner_user_id FROM {conversations}")
                )
            ).all()
        }
        for source in sources:
            conversation_id = _uuid(source["conversation_id"])
            owner_id = owners.get(conversation_id)
            if conversation_id is None or owner_id is None:
                rejected.append(
                    MigrationRejectedItem(
                        code="missing_target_conversation",
                        source=str(source["source"]),
                        detail="目标会话不存在",
                    )
                )
                continue
            projected = [
                _project(
                    item,
                    conversation_id=conversation_id,
                    sequence=index,
                    owner_id=owner_id,
                )
                for index, item in enumerate(source["messages"], start=1)
            ]
            if any(item is None for item in projected):
                rejected.append(
                    MigrationRejectedItem(
                        code="invalid_message_record",
                        source=str(source["source"]),
                        detail="消息缺少有效标识、角色或创建时间",
                    )
                )
                continue
            expected = [item for item in projected if item is not None]
            rows = (
                await session.execute(
                    text(
                        "SELECT id,conversation_id,run_id,sequence,role,message_type,"
                        f"content,status,created_by,created_at FROM {messages} "
                        "WHERE conversation_id=:id ORDER BY sequence"
                    ),
                    {"id": conversation_id},
                )
            ).mappings().all()
            if rows:
                if _same_history(rows, expected):
                    unchanged += len(expected)
                else:
                    rejected.append(
                        MigrationRejectedItem(
                            code="target_message_history_conflict",
                            source=str(source["source"]),
                            detail="目标会话已有不同的丰富事件消息，已整段保留目标历史",
                        )
                    )
                continue
            identifiers = [item["id"] for item in expected]
            collision = await session.scalar(
                text(f"SELECT count(*) FROM {messages} WHERE id=ANY(:ids)"),
                {"ids": identifiers},
            )
            if collision:
                rejected.append(
                    MigrationRejectedItem(
                        code="message_identifier_conflict",
                        source=str(source["source"]),
                        detail="消息标识已被其他会话使用",
                    )
                )
                continue
            for item in expected:
                values = dict(item)
                values["content"] = json.dumps(
                    values["content"], ensure_ascii=False
                )
                await session.execute(
                    text(
                        f"INSERT INTO {messages} "
                        "(id,conversation_id,run_id,sequence,role,message_type,"
                        "content,status,created_by,created_at) VALUES "
                        "(:id,:conversation_id,:run_id,:sequence,:role,:message_type,"
                        "CAST(:content AS jsonb),:status,:created_by,:created_at)"
                    ),
                    values,
                )
            inserted += len(expected)

    target_count, target_hash = await _target_snapshot(schema, session_factory)
    processed = inserted + unchanged
    status = (
        "completed_with_rejections"
        if rejected and processed
        else "rejected"
        if rejected
        else "completed"
    )
    return MigrationExecutionReport(
        domain="messages",
        status=status,
        execution_order=4,
        source_count=source_count,
        target_count=target_count,
        inserted_count=inserted,
        unchanged_count=unchanged,
        source_hash=source_hash,
        target_hash=target_hash,
        transaction_committed=True,
        rejected=rejected,
    )


async def _target_snapshot(schema: str, session_factory) -> tuple[int, str]:
    messages = table(schema, "messages")
    async with migration_session(session_factory) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id,conversation_id,run_id,sequence,role,message_type,"
                    f"content,status,created_by,created_at FROM {messages} "
                    "ORDER BY conversation_id,sequence"
                )
            )
        ).mappings().all()
    projection = [dict(row) for row in rows]
    return len(projection), content_hash(projection)
