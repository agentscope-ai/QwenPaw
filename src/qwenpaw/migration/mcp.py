"""遗留 Agent MCP 配置到 PostgreSQL Driver 的安全幂等迁移。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from ..access.agent_repository import agent_database_id
from ..constant import WORKING_DIR
from ..drivers.adapters.mcp_legacy_config import legacy_mcp_client_to_driver
from .common import content_hash, migration_session, stable_uuid, table
from .report import MigrationExecutionReport, MigrationRejectedItem


def _client_config(value: dict[str, object]) -> SimpleNamespace:
    """仅将适配器以属性访问的顶层和 OAuth 配置转为命名空间。"""
    normalized = dict(value)
    for field in ("env", "headers"):
        mapping = normalized.get(field)
        if isinstance(mapping, dict):
            normalized[field] = {
                key: item for key, item in mapping.items() if item not in ("", None)
            }
    oauth = normalized.get("oauth")
    if isinstance(oauth, dict):
        normalized["oauth"] = SimpleNamespace(**oauth)
    return SimpleNamespace(**normalized)


def _sources(working_dir: Path):
    records: list[dict[str, object]] = []
    rejected: list[MigrationRejectedItem] = []
    root = working_dir / "workspaces"
    if not root.is_dir():
        return records, content_hash(records), rejected
    for workspace in sorted(path for path in root.iterdir() if path.is_dir()):
        path = workspace / "agent.json"
        if not path.is_file():
            continue
        logical = f"work/workspaces/{workspace.name}/agent.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            clients = value.get("mcp", {}).get("clients", {})
            if not isinstance(clients, dict):
                raise ValueError
        except (OSError, UnicodeDecodeError, ValueError, AttributeError):
            rejected.append(MigrationRejectedItem(
                code="invalid_mcp_config", source=logical, detail="MCP 配置无法解析"
            ))
            continue
        for client_key, raw in sorted(clients.items()):
            if not isinstance(raw, dict):
                rejected.append(MigrationRejectedItem(
                    code="invalid_mcp_client", source=f"{logical}#{client_key}",
                    detail="MCP 客户端配置格式非法"
                ))
                continue
            card, credential = legacy_mcp_client_to_driver(str(client_key), _client_config(raw))
            if credential is not None:
                rejected.append(MigrationRejectedItem(
                    code="credential_requires_explicit_import",
                    source=f"{logical}#{client_key}",
                    detail="配置含凭据，未自动复制明文；请在目标端重新绑定"
                ))
                continue
            records.append({
                "source": f"{logical}#{client_key}", "agent_key": workspace.name,
                "client_key": str(client_key), "enabled": bool(card.enabled),
                "config": {
                    "endpoint": dict(card.endpoint), "config": dict(card.config),
                    "credentials": {},
                },
                "tools": card.config.get("tools"), "policy": asdict(card.policy),
            })
    return records, content_hash(records), rejected


async def migrate_mcp(*, working_dir: Path = WORKING_DIR, schema: str = "qwenpaw", session_factory=None) -> MigrationExecutionReport:
    sources, source_hash, rejected = _sources(working_dir)
    drivers, revisions, agents = (table(schema, name) for name in ("agent_drivers", "driver_revisions", "agents"))
    inserted = unchanged = 0
    async with migration_session(session_factory) as session:
        agent_rows = (await session.execute(text(f"SELECT id,owner_user_id FROM {agents}"))).mappings().all()
        owners = {row["id"]: row["owner_user_id"] for row in agent_rows}
        for source in sources:
            agent_id = agent_database_id(str(source["agent_key"]))
            owner = owners.get(agent_id)
            if owner is None:
                rejected.append(MigrationRejectedItem(code="missing_target_agent", source=str(source["source"]), detail="目标智能体不存在"))
                continue
            row = (await session.execute(text(
                f"SELECT d.status,r.config,r.tool_allowlist,r.policy FROM {drivers} d "
                f"JOIN {revisions} r ON r.id=d.current_revision_id "
                "WHERE d.agent_id=:agent AND d.protocol='mcp' AND d.name=:name"
            ), {"agent": agent_id, "name": source["client_key"]})).mappings().one_or_none()
            expected_status = "enabled" if source["enabled"] else "disabled"
            if row is not None:
                if (row["status"] == expected_status and row["config"] == source["config"]
                        and row["tool_allowlist"] == source["tools"] and row["policy"] == source["policy"]):
                    unchanged += 1
                else:
                    rejected.append(MigrationRejectedItem(code="target_driver_conflict", source=str(source["source"]), detail="目标 MCP Driver 已有不同配置，已保留目标版本"))
                continue
            driver_id = stable_uuid("mcp_driver", f"{source['agent_key']}:{source['client_key']}")
            revision_id = stable_uuid("mcp_revision", f"{source['agent_key']}:{source['client_key']}:1")
            config_json = json.dumps(source["config"], ensure_ascii=False)
            tools_json = json.dumps(source["tools"], ensure_ascii=False)
            policy_json = json.dumps(source["policy"], ensure_ascii=False)
            revision_hash = content_hash({"config": source["config"], "tool_allowlist": source["tools"], "policy": source["policy"]}).removeprefix("sha256:")
            await session.execute(text(f"INSERT INTO {drivers} (id,agent_id,protocol,name,status,created_by) VALUES (:id,:agent,'mcp',:name,:status,:owner)"), {"id": driver_id, "agent": agent_id, "name": source["client_key"], "status": expected_status, "owner": owner})
            await session.execute(text(f"INSERT INTO {revisions} (id,driver_id,revision,config,tool_allowlist,policy,content_hash,created_by) VALUES (:id,:driver,1,CAST(:config AS jsonb),CAST(:tools AS jsonb),CAST(:policy AS jsonb),:hash,:owner)"), {"id": revision_id, "driver": driver_id, "config": config_json, "tools": tools_json, "policy": policy_json, "hash": revision_hash, "owner": owner})
            await session.execute(text(f"UPDATE {drivers} SET current_revision_id=:revision WHERE id=:driver"), {"revision": revision_id, "driver": driver_id})
            inserted += 1
    target_count, target_hash = await _target_snapshot(schema, session_factory)
    processed = inserted + unchanged
    status = "completed_with_rejections" if rejected and processed else "rejected" if rejected else "completed" if sources else "empty"
    return MigrationExecutionReport(domain="mcp", status=status, execution_order=6, source_count=len(sources), target_count=target_count, inserted_count=inserted, unchanged_count=unchanged, source_hash=source_hash, target_hash=target_hash, transaction_committed=bool(sources or rejected), rejected=rejected)


async def _target_snapshot(schema: str, session_factory):
    drivers, revisions = table(schema, "agent_drivers"), table(schema, "driver_revisions")
    async with migration_session(session_factory) as session:
        rows = (await session.execute(text(f"SELECT d.id,d.agent_id,d.name,d.status,r.revision,r.config,r.tool_allowlist,r.policy FROM {drivers} d JOIN {revisions} r ON r.id=d.current_revision_id WHERE d.protocol='mcp' ORDER BY d.agent_id,d.name"))).mappings().all()
    projection = [dict(row) for row in rows]
    return len(projection), content_hash(projection)
