"""遗留数据源的只读扫描器。"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from ..constant import (
    CHATS_FILE,
    CONFIG_FILE,
    JOBS_FILE,
    SECRET_DIR,
    TOKEN_USAGE_FILE,
    WORKING_DIR,
)
from .report import (
    LegacyPostgresSnapshot,
    MigrationConflict,
    MigrationDomainReport,
    MigrationIntegrity,
    MigrationPreviewReport,
    MigrationPreviewSummary,
    MigrationRejectedItem,
    SecretReference,
)

LegacyPostgresProbe = Callable[
    [], LegacyPostgresSnapshot | Awaitable[LegacyPostgresSnapshot]
]

_EMPTY_HASH = hashlib.sha256(b"").hexdigest()
_DOMAIN_META = (
    ("identity", "身份", "legacy.auth", "identity.users"),
    ("agents", "智能体", "legacy.agents", "access.agents"),
    ("conversations", "会话", "legacy.chats", "chats.conversations"),
    ("messages", "消息", "legacy.sessions", "chats.messages"),
    ("skills", "技能", "legacy.skills", "governance.skills"),
    ("mcp", "MCP", "legacy.mcp", "governance.mcp_servers"),
    ("cron", "定时任务", "legacy.jobs", "automation.jobs"),
    ("inbox", "收件箱", "legacy.inbox", "inbox.events"),
    ("tokens", "Token 用量", "legacy.token_usage", "usage.records"),
    ("legacy_postgres", "旧 PostgreSQL", "legacy.postgres", "platform.postgres"),
)
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


def _sha256(parts: Iterable[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(parts):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _logical_path(path: Path, working_dir: Path, secret_dir: Path) -> str:
    try:
        return f"work/{path.relative_to(working_dir).as_posix()}"
    except ValueError:
        pass
    try:
        return f"secret/{path.relative_to(secret_dir).as_posix()}"
    except ValueError:
        return path.name


def _read_json(
    path: Path,
    *,
    domain: str,
    working_dir: Path,
    secret_dir: Path,
    rejected: dict[str, list[MigrationRejectedItem]],
) -> tuple[Any | None, bytes | None]:
    if not path.is_file():
        return None, None
    logical = _logical_path(path, working_dir, secret_dir)
    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8")), raw
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        rejected[domain].append(
            MigrationRejectedItem(
                code="invalid_json",
                source=logical,
                detail="JSON 文件无法解析",
            )
        )
        return None, None


def _secret_version(value: str) -> str:
    if value.startswith("ENC:"):
        return "fernet-v1"
    return "plaintext" if value else "unknown"


def _collect_secret_references(
    value: Any,
    source: str,
    output: dict[str, SecretReference],
    prefix: str = "",
) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            field = str(key)
            location = f"{prefix}.{field}" if prefix else field
            normalized = field.lower()
            is_secret = any(marker in normalized for marker in _SECRET_MARKERS)
            is_usage_counter = normalized.endswith("_tokens")
            if (
                is_secret
                and not is_usage_counter
                and isinstance(nested, str)
                and bool(nested)
            ):
                reference = f"{source}#{location}"
                output[reference] = SecretReference(
                    reference=reference,
                    version=_secret_version(nested),
                )
            else:
                _collect_secret_references(nested, source, output, location)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _collect_secret_references(nested, source, output, f"{prefix}[{index}]")


def _list_items(value: Any, key: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get(key), list):
        return value[key]
    return []


def _session_messages(value: Any) -> list[Any]:
    if not isinstance(value, dict):
        return []
    direct = value.get("messages")
    if isinstance(direct, list):
        return direct
    state = value.get("state")
    if isinstance(state, dict) and isinstance(state.get("context"), list):
        return state["context"]
    agent = value.get("agent")
    if isinstance(agent, dict):
        agent_state = agent.get("state")
        if isinstance(agent_state, dict) and isinstance(
            agent_state.get("context"), list
        ):
            return agent_state["context"]
    return []


def _token_record_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if not isinstance(value, dict):
        return 0
    explicit = value.get("chats") or value.get("records")
    if isinstance(explicit, list):
        return len(explicit)
    count = 0
    for bucket in value.values():
        if not isinstance(bucket, dict):
            continue
        count += sum(
            isinstance(record, dict)
            and any(
                field in record
                for field in ("prompt_tokens", "completion_tokens", "call_count")
            )
            for record in bucket.values()
        )
    return count


def _record_duplicates(
    items: Iterable[Any],
    *,
    domain: str,
    source: str,
    conflicts: dict[str, list[MigrationConflict]],
) -> None:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id") or item.get("session_id") or "").strip()
        if identifier and identifier in seen:
            duplicate.add(identifier)
        seen.add(identifier)
    for identifier in sorted(duplicate):
        conflicts[domain].append(
            MigrationConflict(
                code="duplicate_identifier",
                source=source,
                detail=f"发现重复标识：{identifier}",
            )
        )


def _candidate_files(working_dir: Path, secret_dir: Path) -> list[Path]:
    paths = [
        secret_dir / "auth.json",
        working_dir / CONFIG_FILE,
        working_dir / "inbox_events.json",
        working_dir / TOKEN_USAGE_FILE,
        working_dir / JOBS_FILE,
    ]
    workspaces = working_dir / "workspaces"
    if workspaces.is_dir():
        paths.extend(path for path in workspaces.rglob("*") if path.is_file() and (
            path.name in {"agent.json", CHATS_FILE, JOBS_FILE, "skill.json", "SKILL.md"}
            or "sessions" in path.parts
        ))
    return sorted(set(paths))


def _tree_fingerprint(
    paths: Iterable[Path], working_dir: Path, secret_dir: Path
) -> str:
    parts: list[tuple[str, bytes]] = []
    for path in paths:
        if path.is_file():
            try:
                parts.append(
                    (
                        _logical_path(path, working_dir, secret_dir),
                        path.read_bytes(),
                    )
                )
            except OSError:
                continue
    return _sha256(parts)


async def probe_configured_legacy_postgres() -> LegacyPostgresSnapshot:
    """以只读事务探测显式配置的旧 PostgreSQL，不返回连接信息。"""
    raw_dsn = os.getenv("QWENPAW_LEGACY_DATABASE_URL", "").strip()
    if not raw_dsn:
        return LegacyPostgresSnapshot(configured=False)
    schema = os.getenv("QWENPAW_LEGACY_DATABASE_SCHEMA", "public").strip() or "public"
    try:
        url = make_url(raw_dsn)
        if url.get_backend_name() != "postgresql":
            return LegacyPostgresSnapshot(
                configured=True, error_code="unsupported_driver"
            )
        async_url = url.set(drivername="postgresql+asyncpg").render_as_string(
            hide_password=False
        )
    except Exception:  # noqa: BLE001 - 只返回稳定、脱敏的错误码
        return LegacyPostgresSnapshot(
            configured=True, error_code="invalid_configuration"
        )

    engine = create_async_engine(async_url, poolclass=NullPool, hide_parameters=True)

    async def inspect_database() -> list[Any]:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                rows = (
                    await connection.execute(
                        text(
                            "SELECT relname, n_live_tup FROM pg_stat_user_tables "
                            "WHERE schemaname = :schema ORDER BY relname"
                        ),
                        {"schema": schema},
                    )
                ).all()
                await transaction.rollback()
            except Exception:
                await transaction.rollback()
                raise
                return list(rows)

    try:
        rows = await asyncio.wait_for(inspect_database(), timeout=5)
        canonical = json.dumps(
            [[str(row[0]), int(row[1] or 0)] for row in rows],
            separators=(",", ":"),
        ).encode("utf-8")
        return LegacyPostgresSnapshot(
            configured=True,
            table_count=len(rows),
            row_count=sum(int(row[1] or 0) for row in rows),
            schema_hash=f"sha256:{hashlib.sha256(canonical).hexdigest()}",
        )
    except Exception:  # noqa: BLE001 - 禁止把驱动异常和 DSN 返回前端
        return LegacyPostgresSnapshot(configured=True, error_code="connection_failed")
    finally:
        await engine.dispose()


async def scan_migration_preview(
    *,
    working_dir: Path,
    secret_dir: Path,
    legacy_postgres_probe: LegacyPostgresProbe | None = None,
) -> MigrationPreviewReport:
    """扫描遗留来源并生成报告；不写文件，也不写数据库。"""
    working_dir = working_dir.resolve()
    secret_dir = secret_dir.resolve()
    paths = _candidate_files(working_dir, secret_dir)
    before_hash = _tree_fingerprint(paths, working_dir, secret_dir)
    counts = {key: 0 for key, *_ in _DOMAIN_META}
    source_parts: dict[str, list[tuple[str, bytes]]] = {key: [] for key in counts}
    rejected: dict[str, list[MigrationRejectedItem]] = {key: [] for key in counts}
    conflicts: dict[str, list[MigrationConflict]] = {key: [] for key in counts}
    secret_references: dict[str, SecretReference] = {}

    def load(path: Path, domain: str) -> Any | None:
        value, raw = _read_json(
            path,
            domain=domain,
            working_dir=working_dir,
            secret_dir=secret_dir,
            rejected=rejected,
        )
        if raw is not None:
            logical = _logical_path(path, working_dir, secret_dir)
            source_parts[domain].append((logical, raw))
            _collect_secret_references(value, logical, secret_references)
        return value

    auth = load(secret_dir / "auth.json", "identity")
    if isinstance(auth, dict) and auth:
        counts["identity"] = 1

    config = load(working_dir / CONFIG_FILE, "agents")
    profiles: Any = None
    if isinstance(config, dict):
        agents_config = config.get("agents")
        profiles = (
            agents_config.get("profiles")
            if isinstance(agents_config, dict)
            else config.get("profiles")
        )
        if isinstance(profiles, (dict, list)):
            counts["agents"] += len(profiles)
        root_mcp = config.get("mcp")
        root_clients = root_mcp.get("clients") if isinstance(root_mcp, dict) else None
        if isinstance(root_clients, (dict, list)):
            counts["mcp"] += len(root_clients)
            source_parts["mcp"].extend(source_parts["agents"])

    workspaces = working_dir / "workspaces"
    workspace_dirs = (
        sorted(path for path in workspaces.iterdir() if path.is_dir())
        if workspaces.is_dir()
        else []
    )
    if counts["agents"] == 0:
        counts["agents"] = sum(
            (workspace / "agent.json").is_file()
            for workspace in workspace_dirs
        )

    for workspace in workspace_dirs:
        mcp_source_count = len(source_parts["mcp"])
        agent_config = load(workspace / "agent.json", "mcp")
        if len(source_parts["mcp"]) > mcp_source_count:
            source_parts["agents"].append(source_parts["mcp"][-1])
        if isinstance(agent_config, dict):
            clients = (
                (agent_config.get("mcp") or {}).get("clients")
                if isinstance(agent_config.get("mcp"), dict)
                else None
            )
            if isinstance(clients, (dict, list)):
                counts["mcp"] += len(clients)

        chats_path = workspace / CHATS_FILE
        chats = load(chats_path, "conversations")
        chat_items = _list_items(chats, "chats")
        counts["conversations"] += len(chat_items)
        _record_duplicates(
            chat_items,
            domain="conversations",
            source=_logical_path(chats_path, working_dir, secret_dir),
            conflicts=conflicts,
        )

        sessions_dir = workspace / "sessions"
        if sessions_dir.is_dir():
            for session_path in sorted(sessions_dir.rglob("*.json")):
                session = load(session_path, "messages")
                message_items = _session_messages(session)
                counts["messages"] += len(message_items)

        jobs_path = workspace / JOBS_FILE
        jobs = load(jobs_path, "cron")
        job_items = _list_items(jobs, "jobs")
        counts["cron"] += len(job_items)
        _record_duplicates(
            job_items,
            domain="cron",
            source=_logical_path(jobs_path, working_dir, secret_dir),
            conflicts=conflicts,
        )

        skill_files = sorted(workspace.glob("skills/**/SKILL.md"))
        counts["skills"] += len(skill_files)
        for skill_file in skill_files:
            try:
                source_parts["skills"].append(
                    (
                        _logical_path(skill_file, working_dir, secret_dir),
                        skill_file.read_bytes(),
                    )
                )
            except OSError:
                rejected["skills"].append(
                    MigrationRejectedItem(
                        code="unreadable_file",
                        source=_logical_path(skill_file, working_dir, secret_dir),
                        detail="技能文件无法读取",
                    )
                )

    root_jobs_path = working_dir / JOBS_FILE
    root_jobs = load(root_jobs_path, "cron")
    root_job_items = _list_items(root_jobs, "jobs")
    counts["cron"] += len(root_job_items)

    inbox_path = working_dir / "inbox_events.json"
    inbox = load(inbox_path, "inbox")
    counts["inbox"] = len(_list_items(inbox, "events"))

    tokens_path = working_dir / TOKEN_USAGE_FILE
    tokens = load(tokens_path, "tokens")
    counts["tokens"] = _token_record_count(tokens)

    probe = legacy_postgres_probe or probe_configured_legacy_postgres
    snapshot_or_awaitable = probe()
    snapshot = (
        await snapshot_or_awaitable
        if inspect.isawaitable(snapshot_or_awaitable)
        else snapshot_or_awaitable
    )
    counts["legacy_postgres"] = snapshot.row_count

    after_paths = _candidate_files(working_dir, secret_dir)
    after_hash = _tree_fingerprint(after_paths, working_dir, secret_dir)
    domains: list[MigrationDomainReport] = []
    for key, label, source_name, target_name in _DOMAIN_META:
        if key == "legacy_postgres":
            source_hash = snapshot.schema_hash
            if snapshot.error_code:
                status = "unavailable"
                rejected[key].append(
                    MigrationRejectedItem(
                        code=snapshot.error_code,
                        source="legacy/postgres",
                        detail="旧 PostgreSQL 无法完成只读探测",
                    )
                )
            elif not snapshot.configured:
                status = "unavailable"
            else:
                status = "ready" if snapshot.row_count else "empty"
        else:
            source_hash = _sha256(source_parts[key])
            status = (
                "rejected"
                if rejected[key]
                else ("ready" if counts[key] else "empty")
            )
        domains.append(
            MigrationDomainReport(
                key=key,
                label=label,
                status=status,
                count=counts[key],
                source_hash=source_hash,
                mapping={source_name: target_name},
                conflicts=conflicts[key],
                rejected=rejected[key],
            )
        )

    refs = [secret_references[key] for key in sorted(secret_references)]
    return MigrationPreviewReport(
        generated_at=datetime.now(UTC),
        summary=MigrationPreviewSummary(
            domain_count=len(domains),
            item_count=sum(domain.count for domain in domains),
            conflict_count=sum(len(domain.conflicts) for domain in domains),
            rejected_count=sum(len(domain.rejected) for domain in domains),
            secret_reference_count=len(refs),
        ),
        integrity=MigrationIntegrity(
            before_hash=before_hash,
            after_hash=after_hash,
            unchanged=before_hash == after_hash and paths == after_paths,
        ),
        domains=domains,
        secret_references=refs,
    )


async def scan_configured_migration_preview() -> MigrationPreviewReport:
    return await scan_migration_preview(
        working_dir=WORKING_DIR,
        secret_dir=SECRET_DIR,
    )
