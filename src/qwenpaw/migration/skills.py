"""遗留 Agent 工作区技能关系到 PostgreSQL 的安全幂等迁移。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ..access.agent_repository import agent_database_id
from ..constant import WORKING_DIR
from .common import content_hash, migration_session, stable_uuid, table
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


def _redact_config(value: Any, *, source: str, path: str = "") -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, nested in value.items():
            location = f"{path}.{key}" if path else str(key)
            if (
                any(marker in str(key).lower() for marker in _SECRET_MARKERS)
                and isinstance(nested, str)
                and nested
            ):
                output[key] = {"secret_ref": f"{source}#{location}"}
            else:
                output[key] = _redact_config(
                    nested,
                    source=source,
                    path=location,
                )
        return output
    if isinstance(value, list):
        return [
            _redact_config(item, source=source, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


def _parts_hash(parts: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, raw in sorted(parts):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _source_skills(
    working_dir: Path,
) -> tuple[list[dict[str, object]], str, list[MigrationRejectedItem]]:
    workspaces = working_dir / "workspaces"
    if not workspaces.is_dir():
        return [], content_hash([]), []
    records: list[dict[str, object]] = []
    parts: list[tuple[str, bytes]] = []
    rejected: list[MigrationRejectedItem] = []
    for workspace in sorted(path for path in workspaces.iterdir() if path.is_dir()):
        manifest_path = workspace / "skill.json"
        if not manifest_path.is_file():
            continue
        logical_manifest = f"work/workspaces/{workspace.name}/skill.json"
        try:
            raw_manifest = manifest_path.read_bytes()
            manifest = json.loads(raw_manifest.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            rejected.append(
                MigrationRejectedItem(
                    code="invalid_skill_manifest",
                    source=logical_manifest,
                    detail="技能清单无法解析",
                )
            )
            continue
        parts.append((logical_manifest, raw_manifest))
        entries = manifest.get("skills") if isinstance(manifest, dict) else None
        if not isinstance(entries, dict):
            continue
        for name, raw_entry in sorted(entries.items()):
            skill_dir = workspace / "skills" / str(name)
            document = skill_dir / "SKILL.md"
            logical = f"work/workspaces/{workspace.name}/skills/{name}"
            if not document.is_file():
                continue
            if skill_dir.parent != workspace / "skills" or Path(str(name)).name != name:
                rejected.append(
                    MigrationRejectedItem(
                        code="unsafe_skill_name",
                        source=logical,
                        detail="技能名称不能安全映射到工作区目录",
                    )
                )
                continue
            try:
                for path in sorted(item for item in skill_dir.rglob("*") if item.is_file()):
                    parts.append(
                        (
                            f"{logical}/{path.relative_to(skill_dir).as_posix()}",
                            path.read_bytes(),
                        )
                    )
            except OSError:
                rejected.append(
                    MigrationRejectedItem(
                        code="unreadable_skill_directory",
                        source=logical,
                        detail="技能目录无法完整读取",
                    )
                )
                continue
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            raw_config = entry.get("config")
            config = raw_config if isinstance(raw_config, dict) else {}
            records.append(
                {
                    "source": logical,
                    "agent_key": workspace.name,
                    "name": str(name),
                    "content_key": f"skills/{name}",
                    "enabled": bool(entry.get("enabled", True)),
                    "source_pool_version_id": entry.get("source_pool_version_id"),
                    "detached": bool(entry.get("detached", False)),
                    "config": _redact_config(config, source=logical),
                }
            )
    return records, _parts_hash(parts), rejected


def _same(row, expected: dict[str, object]) -> bool:
    return all(row[key] == value for key, value in expected.items())


async def migrate_skills(
    *,
    working_dir: Path = WORKING_DIR,
    schema: str = "qwenpaw",
    session_factory=None,
) -> MigrationExecutionReport:
    """补录缺失的 Agent 技能关系，保留已有治理状态。"""
    sources, source_hash, rejected = _source_skills(working_dir)
    if not sources and not rejected:
        target_count, target_hash = await _target_snapshot(schema, session_factory)
        return MigrationExecutionReport(
            domain="skills",
            status="empty",
            execution_order=5,
            source_count=0,
            target_count=target_count,
            source_hash=source_hash,
            target_hash=target_hash,
            transaction_committed=False,
        )

    agents = table(schema, "agents")
    versions = table(schema, "skill_pool_versions")
    agent_skills = table(schema, "agent_skills")
    inserted = unchanged = 0
    async with migration_session(session_factory) as session:
        agent_ids = set((await session.execute(text(f"SELECT id FROM {agents}"))).scalars())
        version_ids = set(
            (await session.execute(text(f"SELECT id FROM {versions}"))).scalars()
        )
        for source in sources:
            agent_id = agent_database_id(str(source["agent_key"]))
            version_id = source["source_pool_version_id"]
            if agent_id not in agent_ids:
                rejected.append(
                    MigrationRejectedItem(
                        code="missing_target_agent",
                        source=str(source["source"]),
                        detail="目标智能体不存在",
                    )
                )
                continue
            if version_id and version_id not in {str(item) for item in version_ids}:
                rejected.append(
                    MigrationRejectedItem(
                        code="missing_skill_pool_version",
                        source=str(source["source"]),
                        detail="来源技能池版本不存在",
                    )
                )
                continue
            expected = {
                "content_key": source["content_key"],
                "enabled": source["enabled"],
                "source_pool_version_id": version_id,
                "detached": source["detached"],
                "config": source["config"],
            }
            row = (
                await session.execute(
                    text(
                        "SELECT content_key,enabled,source_pool_version_id,detached,config "
                        f"FROM {agent_skills} WHERE agent_id=:agent_id AND name=:name"
                    ),
                    {"agent_id": agent_id, "name": source["name"]},
                )
            ).mappings().one_or_none()
            if row is not None:
                comparable = dict(expected)
                comparable["source_pool_version_id"] = (
                    str(version_id) if version_id else None
                )
                actual = dict(row)
                actual["source_pool_version_id"] = (
                    str(actual["source_pool_version_id"])
                    if actual["source_pool_version_id"]
                    else None
                )
                if _same(actual, comparable):
                    unchanged += 1
                else:
                    rejected.append(
                        MigrationRejectedItem(
                            code="target_agent_skill_conflict",
                            source=str(source["source"]),
                            detail="目标技能已有不同治理状态，已保留目标版本",
                        )
                    )
                continue
            await session.execute(
                text(
                    f"INSERT INTO {agent_skills} "
                    "(id,agent_id,name,content_key,enabled,source_pool_version_id,"
                    "detached,config) VALUES "
                    "(:id,:agent_id,:name,:content_key,:enabled,:source_pool_version_id,"
                    ":detached,CAST(:config AS jsonb))"
                ),
                {
                    "id": stable_uuid(
                        "agent_skill", f"{source['agent_key']}:{source['name']}"
                    ),
                    "agent_id": agent_id,
                    "name": source["name"],
                    "content_key": source["content_key"],
                    "enabled": source["enabled"],
                    "source_pool_version_id": UUID(str(version_id))
                    if version_id
                    else None,
                    "detached": source["detached"],
                    "config": json.dumps(source["config"], ensure_ascii=False),
                },
            )
            inserted += 1

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
        domain="skills",
        status=status,
        execution_order=5,
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
    agent_skills = table(schema, "agent_skills")
    async with migration_session(session_factory) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id,agent_id,name,content_key,enabled,source_pool_version_id,"
                    f"detached,config,updated_at FROM {agent_skills} ORDER BY agent_id,name"
                )
            )
        ).mappings().all()
    projection = [dict(row) for row in rows]
    return len(projection), content_hash(projection)
