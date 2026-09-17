"""遗留智能体治理元数据与配置修订的幂等迁移。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ..access.agent_repository import agent_database_id
from ..agents.config_repository import config_content_hash
from ..constant import CONFIG_FILE, SECRET_DIR, WORKING_DIR
from .common import content_hash, migration_session, read_json, table
from .report import MigrationExecutionReport, MigrationRejectedItem

_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "authorization",
    "cookie",
    "access_token",
    "refresh_token",
)


def _redact(value: Any, *, agent_key: str, path: str = "") -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, nested in value.items():
            location = f"{path}.{key}" if path else str(key)
            normalized = str(key).lower()
            if (
                any(marker in normalized for marker in _SECRET_MARKERS)
                and not normalized.endswith("_tokens")
                and isinstance(nested, str)
                and nested
            ):
                output[key] = {
                    "secret_ref": f"legacy/agents/{agent_key}#{location}",
                    "version": "fernet-v1" if nested.startswith("ENC:") else "plaintext",
                }
            else:
                output[key] = _redact(
                    nested,
                    agent_key=agent_key,
                    path=location,
                )
        return output
    if isinstance(value, list):
        return [
            _redact(item, agent_key=agent_key, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


def _structured_config(agent_key: str, data: dict[str, Any]) -> dict[str, Any]:
    metadata = {"id", "name", "description", "workspace_dir"}
    return _redact(
        {key: value for key, value in data.items() if key not in metadata},
        agent_key=agent_key,
    )


def _source_agents(working_dir: Path) -> tuple[list[dict[str, Any]], str]:
    config_path = working_dir / CONFIG_FILE
    if not config_path.is_file():
        return [], content_hash([])
    root = read_json(config_path)
    agents_config = root.get("agents") if isinstance(root, dict) else None
    profiles = agents_config.get("profiles") if isinstance(agents_config, dict) else None
    if not isinstance(profiles, dict):
        return [], content_hash([])

    records: list[dict[str, Any]] = []
    source_parts: list[tuple[str, bytes]] = [("work/config.json", config_path.read_bytes())]
    for agent_key, reference in profiles.items():
        workspace = working_dir / "workspaces" / str(agent_key)
        profile_path = workspace / "agent.json"
        data: dict[str, Any] = {}
        if profile_path.is_file():
            loaded = read_json(profile_path)
            if isinstance(loaded, dict):
                data = loaded
            source_parts.append(
                (
                    f"work/workspaces/{agent_key}/agent.json",
                    profile_path.read_bytes(),
                )
            )
        ref = reference if isinstance(reference, dict) else {}
        records.append(
            {
                "key": str(agent_key),
                "name": str(data.get("name") or agent_key),
                "description": str(data.get("description") or ""),
                "workspace_key": str(ref.get("workspace_dir") or workspace),
                "status": "active" if ref.get("enabled", True) else "disabled",
                "config": _structured_config(str(agent_key), data),
            }
        )
    return records, _parts_hash(source_parts)


def _parts_hash(parts: list[tuple[str, bytes]]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for name, raw in sorted(parts):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


async def migrate_agents(
    *,
    working_dir: Path = WORKING_DIR,
    secret_dir: Path = SECRET_DIR,
    schema: str = "qwenpaw",
    session_factory=None,
) -> MigrationExecutionReport:
    """补录智能体和缺失的当前配置修订，保留已有治理状态。"""
    del secret_dir  # Secret 只转为逻辑引用，不读取 Secret Store。
    try:
        sources, source_hash = _source_agents(working_dir)
    except (OSError, UnicodeDecodeError, ValueError):
        return await _rejected_report(
            schema=schema,
            session_factory=session_factory,
            source_hash=content_hash([]),
            source_count=0,
            code="invalid_agent_source",
            detail="智能体根清单或配置文件无法解析",
        )
    if not sources:
        target_count, target_hash = await _target_snapshot(schema, session_factory)
        return MigrationExecutionReport(
            domain="agents",
            status="empty",
            execution_order=2,
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
    revisions = table(schema, "agent_config_revisions")
    inserted = revision_inserted = unchanged = 0
    rejected: list[MigrationRejectedItem] = []
    async with migration_session(session_factory) as session:
        owner_id = await session.scalar(
            text(
                f"SELECT id FROM {users} WHERE status='active' "
                "AND platform_role='admin' ORDER BY created_at,id LIMIT 1"
            )
        )
        if owner_id is None:
            return await _rejected_report(
                schema=schema,
                session_factory=session_factory,
                source_hash=source_hash,
                source_count=len(sources),
                code="missing_target_admin",
                detail="目标库没有可承接遗留智能体的有效管理员",
            )
        for source in sources:
            agent_id = agent_database_id(source["key"])
            inserted_id = await session.scalar(
                text(
                    f"INSERT INTO {agents} "
                    "(id,owner_user_id,name,description,status,visibility,"
                    "default_model_mode,draft_workspace_key) VALUES "
                    "(:id,:owner,:name,:description,:status,'private','inherited',"
                    ":workspace_key) ON CONFLICT (id) DO NOTHING RETURNING id"
                ),
                {
                    "id": agent_id,
                    "owner": owner_id,
                    "name": source["name"],
                    "description": source["description"],
                    "status": source["status"],
                    "workspace_key": source["workspace_key"],
                },
            )
            if inserted_id is not None:
                inserted += 1
            row = (
                await session.execute(
                    text(
                        f"SELECT owner_user_id,config_version FROM {agents} "
                        "WHERE id=:id FOR UPDATE"
                    ),
                    {"id": agent_id},
                )
            ).mappings().one()
            revision = int(row["config_version"])
            config = source["config"]
            config_hash = config_content_hash(config)
            existing_hash = await session.scalar(
                text(
                    f"SELECT content_hash FROM {revisions} "
                    "WHERE agent_id=:agent_id AND revision=:revision"
                ),
                {"agent_id": agent_id, "revision": revision},
            )
            if existing_hash is None:
                await session.execute(
                    text(
                        f"INSERT INTO {revisions} "
                        "(id,agent_id,revision,structured_config,content_hash,changed_by) "
                        "VALUES (gen_random_uuid(),:agent_id,:revision,"
                        "CAST(:config AS jsonb),:content_hash,:changed_by)"
                    ),
                    {
                        "agent_id": agent_id,
                        "revision": revision,
                        "config": json.dumps(config, ensure_ascii=False),
                        "content_hash": config_hash,
                        "changed_by": row["owner_user_id"],
                    },
                )
                revision_inserted += 1
            elif existing_hash == config_hash:
                unchanged += 1
            else:
                rejected.append(
                    MigrationRejectedItem(
                        code="target_config_conflict",
                        source=f"work/workspaces/{source['key']}/agent.json",
                        detail="目标当前配置修订与遗留配置不同，已保留目标版本",
                    )
                )

    target_count, target_hash = await _target_snapshot(schema, session_factory)
    processed = inserted + revision_inserted + unchanged
    status = (
        "completed_with_rejections"
        if rejected and processed
        else "rejected"
        if rejected
        else "completed"
    )
    return MigrationExecutionReport(
        domain="agents",
        status=status,
        execution_order=2,
        source_count=len(sources),
        target_count=target_count,
        inserted_count=inserted,
        updated_count=revision_inserted,
        unchanged_count=unchanged,
        source_hash=source_hash,
        target_hash=target_hash,
        transaction_committed=True,
        rejected=rejected,
    )


async def _target_snapshot(schema: str, session_factory) -> tuple[int, str]:
    agents = table(schema, "agents")
    revisions = table(schema, "agent_config_revisions")
    async with migration_session(session_factory) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT a.id,a.owner_user_id,a.status,a.visibility,a.config_version,"
                    "r.content_hash "
                    f"FROM {agents} a LEFT JOIN {revisions} r "
                    "ON r.agent_id=a.id AND r.revision=a.config_version "
                    "ORDER BY a.id"
                )
            )
        ).mappings().all()
    projection = [dict(row) for row in rows]
    return len(projection), content_hash(projection)


async def _rejected_report(
    *,
    schema: str,
    session_factory,
    source_hash: str,
    source_count: int,
    code: str,
    detail: str,
) -> MigrationExecutionReport:
    target_count, target_hash = await _target_snapshot(schema, session_factory)
    return MigrationExecutionReport(
        domain="agents",
        status="rejected",
        execution_order=2,
        source_count=source_count,
        target_count=target_count,
        inserted_count=0,
        unchanged_count=0,
        source_hash=source_hash,
        target_hash=target_hash,
        transaction_committed=False,
        rejected=[
            MigrationRejectedItem(
                code=code,
                source="work/config.json",
                detail=detail,
            )
        ],
    )
