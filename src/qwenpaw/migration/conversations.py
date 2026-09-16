"""遗留会话清单到 PostgreSQL 会话元数据的幂等迁移。"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text

from ..access.agent_repository import agent_database_id
from ..app.chats.models import ChatsFile
from ..constant import CHATS_FILE, WORKING_DIR
from .common import content_hash, migration_session, table
from .report import MigrationExecutionReport, MigrationRejectedItem


def _source_conversations(
    working_dir: Path,
) -> tuple[list[dict[str, object]], str, list[MigrationRejectedItem]]:
    workspaces = working_dir / "workspaces"
    if not workspaces.is_dir():
        return [], content_hash([]), []
    records: list[dict[str, object]] = []
    parts: list[tuple[str, bytes]] = []
    rejected: list[MigrationRejectedItem] = []
    for path in sorted(workspaces.glob(f"*/{CHATS_FILE}")):
        logical = f"work/workspaces/{path.parent.name}/{CHATS_FILE}"
        try:
            raw = path.read_bytes()
            chats = ChatsFile.model_validate_json(raw).chats
        except (OSError, UnicodeDecodeError, ValidationError, ValueError):
            rejected.append(
                MigrationRejectedItem(
                    code="invalid_conversation_source",
                    source=logical,
                    detail="会话清单无法解析",
                )
            )
            continue
        parts.append((logical, raw))
        for chat in chats:
            records.append(
                {
                    "source": logical,
                    "id": chat.id,
                    "agent_key": path.parent.name,
                    "legacy_user_id": chat.user_id,
                    "title": chat.name,
                    "status": "archived" if chat.archived else "active",
                    "created_at": chat.created_at,
                    "updated_at": chat.updated_at,
                }
            )
    return records, _parts_hash(parts), rejected


def _parts_hash(parts: list[tuple[str, bytes]]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for name, raw in sorted(parts):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _matches(row, source: dict[str, object], owner_id: UUID, agent_id: UUID) -> bool:
    return (
        row["agent_id"] == agent_id
        and row["owner_user_id"] == owner_id
        and row["title"] == source["title"]
        and row["status"] == source["status"]
        and row["created_at"] == source["created_at"]
        and row["updated_at"] == source["updated_at"]
    )


async def migrate_conversations(
    *,
    working_dir: Path = WORKING_DIR,
    schema: str = "qwenpaw",
    session_factory=None,
) -> MigrationExecutionReport:
    """补录可确定归属的会话；已有不同目标记录一律保留。"""
    sources, source_hash, rejected = _source_conversations(working_dir)
    if not sources and not rejected:
        target_count, target_hash = await _target_snapshot(schema, session_factory)
        return MigrationExecutionReport(
            domain="conversations",
            status="empty",
            execution_order=3,
            source_count=0,
            target_count=target_count,
            inserted_count=0,
            unchanged_count=0,
            source_hash=source_hash,
            target_hash=target_hash,
            transaction_committed=False,
        )

    users = table(schema, "users")
    agents = table(schema, "agents")
    conversations = table(schema, "conversations")
    inserted = unchanged = 0
    async with migration_session(session_factory) as session:
        agent_rows = (
            await session.execute(text(f"SELECT id,owner_user_id FROM {agents}"))
        ).all()
        owners = {row.id: row.owner_user_id for row in agent_rows}
        active_users = set(
            (
                await session.execute(
                    text(f"SELECT id FROM {users} WHERE status='active'")
                )
            ).scalars()
        )
        for source in sources:
            conversation_id = _uuid(source["id"])
            agent_id = agent_database_id(str(source["agent_key"]))
            owner_id = _uuid(source["legacy_user_id"])
            if owner_id is None and source["legacy_user_id"] == "default":
                owner_id = owners.get(agent_id)
            if conversation_id is None:
                rejected.append(
                    MigrationRejectedItem(
                        code="invalid_conversation_id",
                        source=str(source["source"]),
                        detail="会话标识不是有效 UUID",
                    )
                )
                continue
            if agent_id not in owners:
                rejected.append(
                    MigrationRejectedItem(
                        code="missing_target_agent",
                        source=str(source["source"]),
                        detail="目标智能体不存在",
                    )
                )
                continue
            if owner_id is None or owner_id not in active_users:
                rejected.append(
                    MigrationRejectedItem(
                        code="unresolved_conversation_owner",
                        source=str(source["source"]),
                        detail="会话所有者无法映射到有效用户",
                    )
                )
                continue
            inserted_id = await session.scalar(
                text(
                    f"INSERT INTO {conversations} "
                    "(id,agent_id,owner_user_id,title,status,created_at,updated_at) "
                    "VALUES (:id,:agent,:owner,:title,:status,:created,:updated) "
                    "ON CONFLICT (id) DO NOTHING RETURNING id"
                ),
                {
                    "id": conversation_id,
                    "agent": agent_id,
                    "owner": owner_id,
                    "title": source["title"],
                    "status": source["status"],
                    "created": source["created_at"],
                    "updated": source["updated_at"],
                },
            )
            if inserted_id is not None:
                inserted += 1
                continue
            row = (
                await session.execute(
                    text(
                        f"SELECT agent_id,owner_user_id,title,status,created_at,updated_at "
                        f"FROM {conversations} WHERE id=:id"
                    ),
                    {"id": conversation_id},
                )
            ).mappings().one()
            if _matches(row, source, owner_id, agent_id):
                unchanged += 1
            else:
                rejected.append(
                    MigrationRejectedItem(
                        code="target_conversation_conflict",
                        source=str(source["source"]),
                        detail="目标会话元数据不同，已保留目标版本",
                    )
                )

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
        domain="conversations",
        status=status,
        execution_order=3,
        source_count=len(sources),
        target_count=target_count,
        inserted_count=inserted,
        unchanged_count=unchanged,
        source_hash=source_hash,
        target_hash=target_hash,
        transaction_committed=True,
        rejected=rejected,
    )


async def _target_snapshot(schema: str, session_factory) -> tuple[int, str]:
    conversations = table(schema, "conversations")
    async with migration_session(session_factory) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id,agent_id,owner_user_id,title,status,model_override_id,"
                    "shared_app_id,publication_id,created_at,updated_at,deleted_at "
                    f"FROM {conversations} ORDER BY id"
                )
            )
        ).mappings().all()
    projection = [dict(row) for row in rows]
    return len(projection), content_hash(projection)
