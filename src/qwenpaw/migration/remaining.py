"""无可安全写入记录的剩余领域迁移报告。"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import text

from ..constant import WORKING_DIR
from .common import content_hash, file_hash, migration_session, read_json, table
from .report import MigrationExecutionReport, MigrationRejectedItem


async def migrate_cron(*, working_dir: Path = WORKING_DIR, schema: str = "qwenpaw", session_factory=None):
    paths = sorted((working_dir / "workspaces").glob("*/jobs.json")) if (working_dir / "workspaces").is_dir() else []
    if (working_dir / "jobs.json").is_file(): paths.append(working_dir / "jobs.json")
    jobs = []
    for path in paths:
        value = read_json(path)
        jobs.extend(value.get("jobs", []) if isinstance(value, dict) else [])
    source_hash = content_hash([(str(path.relative_to(working_dir)), file_hash(path)) for path in paths])
    schedules = table(schema, "automation_schedules")
    async with migration_session(session_factory) as session:
        rows = (await session.execute(text(f"SELECT id,agent_id,name,status,config_version FROM {schedules} ORDER BY id"))).mappings().all()
    rejected = [] if not jobs else [MigrationRejectedItem(code="cron_records_require_authorization", source="work/workspaces/*/jobs.json", detail="定时任务必须重新授权后迁移")]
    return MigrationExecutionReport(domain="cron", status="empty" if not jobs else "rejected", execution_order=7, source_count=len(jobs), target_count=len(rows), inserted_count=0, unchanged_count=0, source_hash=source_hash, target_hash=content_hash([dict(row) for row in rows]), transaction_committed=False, rejected=rejected)


async def migrate_tokens(*, working_dir: Path = WORKING_DIR, schema: str = "qwenpaw", session_factory=None):
    path = working_dir / "token_usage.json"
    value = read_json(path) if path.is_file() else {}
    records = [(day, key) for day, models in value.items() for key in models] if isinstance(value, dict) else []
    usage = table(schema, "usage_records")
    async with migration_session(session_factory) as session:
        rows = (await session.execute(text(f"SELECT id,occurred_at,user_id,agent_id,provider_id,model_id,prompt_tokens,completion_tokens,call_count FROM {usage} ORDER BY occurred_at,id"))).mappings().all()
    rejected = [MigrationRejectedItem(code="missing_usage_attribution", source=f"work/token_usage.json#{day}/{key}", detail="全局汇总缺少用户、智能体和会话归属，拒绝重复入账") for day, key in records]
    return MigrationExecutionReport(domain="tokens", status="rejected" if records else "empty", execution_order=9, source_count=len(records), target_count=len(rows), inserted_count=0, unchanged_count=0, source_hash=file_hash(path), target_hash=content_hash([dict(row) for row in rows]), transaction_committed=False, rejected=rejected)


async def migrate_legacy_postgres(*, schema: str = "qwenpaw", session_factory=None):
    configured = bool(os.getenv("QWENPAW_LEGACY_DATABASE_URL", "").strip())
    rejected = [] if configured else [MigrationRejectedItem(code="legacy_postgres_not_configured", source="legacy/postgres", detail="未配置独立旧 PostgreSQL 数据源，没有可执行迁移")]
    return MigrationExecutionReport(domain="legacy_postgres", status="rejected" if rejected else "empty", execution_order=10, source_count=0, target_count=0, inserted_count=0, unchanged_count=0, source_hash=content_hash([]), target_hash=content_hash([]), transaction_committed=False, rejected=rejected)
