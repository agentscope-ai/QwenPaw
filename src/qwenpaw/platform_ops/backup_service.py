# -*- coding: utf-8 -*-
"""平台备份清单与一次性恢复确认令牌。"""

from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import json
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from ..backup._utils.constants import find_zip_path, PLATFORM_CONTENT_DIRECTORIES
from ..backup._utils.meta import read_meta_from_zip
from ..backup._utils.signing import replace_meta_with_local_signature
from ..backup._utils.signing import get_signing_key
from ..backup.models import BackupDetail, BackupMeta, RestoreBackupRequest
from ..constant import SECRET_DIR, WORKING_DIR
from ..identity.runtime import get_identity_schema, is_multi_user_enabled
from ..persistence.settings import load_database_settings
from ..persistence.database import database_session

_TOKEN_TTL_SECONDS = 10 * 60
_TOKEN_LOCK = threading.Lock()
_ISSUED_TOKENS: dict[str, float] = {}
_PLATFORM_MANIFEST_PATH = "platform/manifest.json"
_DATABASE_PREFIX = "platform/database/"


async def create_platform_stream(req, *, file_stream=None):
    """Keep one exclusive lease across file compression and database export."""
    from ..backup._ops.create import create_stream
    from ..backup import delete_backups
    from .maintenance import exclusive

    events = asyncio.Queue()

    async def capture():
        completed_id = None
        try:
            async with exclusive():
                async for event in (file_stream or create_stream)(req):
                    if event.get("type") == "done":
                        completed_id = str(event["meta"]["id"])
                        await append_platform_snapshot(completed_id)
                    events.put_nowait(event)
        except Exception:
            if completed_id is not None:
                await delete_backups([completed_id])
            raise
        finally:
            events.put_nowait(None)

    worker = asyncio.create_task(capture())
    try:
        while True:
            event = await events.get()
            if event is None:
                break
            yield event
        await worker
    finally:
        # Client disconnect does not cancel compression or release its lease.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
        if not worker.cancelled():
            worker.result()


class RestoreImpact(BaseModel):
    backup_id: str
    mode: str
    agents: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    platform_manifest: dict[str, Any] = Field(default_factory=dict)
    requires_pre_restore_backup: bool = True
    confirmation_token: str
    expires_at: int


class RestoreConfirmationError(ValueError):
    """恢复确认令牌无效、过期或已经使用。"""


def _tree_version(root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    files = 0
    size = 0
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            stat = path.stat()
            relative = path.relative_to(root).as_posix()
            digest.update(f"{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
            files += 1
            size += stat.st_size
    return {"version": f"sha256:{digest.hexdigest()}", "files": files, "bytes": size}


def build_platform_manifest() -> dict[str, Any]:
    """返回无凭据的数据库、工作区、内容和 Secret Store 一致性清单。"""
    settings = load_database_settings()
    workspace = _tree_version(WORKING_DIR / "workspaces")
    content = _tree_version(WORKING_DIR / "media")
    secrets = _tree_version(SECRET_DIR)
    from .maintenance import maintenance_active

    return {
        "format_version": 1,
        "database": {
            "included": is_multi_user_enabled(),
            "schema": get_identity_schema() if is_multi_user_enabled() else None,
            "target": settings.safe_database_target,
            "consistency": (
                "transaction_required" if is_multi_user_enabled() else "legacy_files"
            ),
        },
        "workspaces": workspace,
        "content_store": content,
        "managed_content": {
            name: _tree_version(WORKING_DIR / name)
            for name in PLATFORM_CONTENT_DIRECTORIES
        },
        "cross_store_consistency": (
            "coordinated_maintenance" if maintenance_active()
            else "sequential_files_and_database"
        ),
        "secret_store": {**secrets, "values_exposed": False},
    }


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def validate_platform_restore(backup_id: str, req: RestoreBackupRequest) -> None:
    """Do not restore all database facts from archives missing their content."""
    if not is_multi_user_enabled() or not req.include_global_config:
        return
    from ..backup._utils.constants import PREFIX_PLATFORM_CONTENT

    archive = find_zip_path(backup_id)
    if archive is None:
        raise FileNotFoundError(backup_id)
    manifest = read_platform_manifest(backup_id)
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    if not manifest.get("database", {}).get("included") or any(
        not any(item.startswith(f"{PREFIX_PLATFORM_CONTENT}{name}/") for item in names)
        for name in PLATFORM_CONTENT_DIRECTORIES
    ):
        raise ValueError("platform_backup_incomplete_recreate_backup")


async def append_platform_snapshot(backup_id: str) -> dict[str, Any]:
    """将同一只读事务中的 PostgreSQL 快照追加到备份并重新签名。"""
    archive = find_zip_path(backup_id)
    if archive is None:
        raise FileNotFoundError(f"Backup not found: {backup_id}")
    with zipfile.ZipFile(archive, "r") as zf:
        raw_meta = read_meta_from_zip(zf)
    if raw_meta is None:
        raise ValueError("backup_metadata_missing")
    meta = BackupMeta.model_validate_json(raw_meta)
    manifest = build_platform_manifest()
    tables: list[dict[str, Any]] = []
    include_database = is_multi_user_enabled() and meta.scope.include_global_config
    manifest["database"]["included"] = include_database
    if include_database:
        schema = get_identity_schema()
        async with database_session() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            result = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=:schema AND table_type='BASE TABLE' "
                    "ORDER BY table_name"
                ),
                {"schema": schema},
            )
            table_names = [str(row[0]) for row in result]
            with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as zf:
                for table_name in table_names:
                    entry = f"{_DATABASE_PREFIX}{table_name}.jsonl"
                    query = text(
                        f"SELECT row_to_json(t)::text FROM "
                        f"{_quote_identifier(schema)}.{_quote_identifier(table_name)} t"
                    )
                    rows = await session.stream(query)
                    digest = hashlib.sha256()
                    count = 0
                    with zf.open(entry, "w") as output:
                        async for row in rows:
                            line = str(row[0]).encode("utf-8") + b"\n"
                            output.write(line)
                            digest.update(line)
                            count += 1
                    tables.append(
                        {
                            "name": table_name,
                            "rows": count,
                            "sha256": digest.hexdigest(),
                            "entry": entry,
                        }
                    )
                manifest["database"]["tables"] = tables
                manifest["database"]["consistency"] = "repeatable_read"
                zf.writestr(
                    _PLATFORM_MANIFEST_PATH,
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                )
    else:
        with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                _PLATFORM_MANIFEST_PATH,
                json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            )
    replace_meta_with_local_signature(archive, meta)
    return manifest


async def restore_platform_database(backup_id: str) -> None:
    """在单一事务内恢复签名归档中的 PostgreSQL 表快照。"""
    if not is_multi_user_enabled():
        return
    archive = find_zip_path(backup_id)
    if archive is None:
        raise FileNotFoundError(f"Backup not found: {backup_id}")
    manifest = read_platform_manifest(backup_id)
    table_entries = manifest.get("database", {}).get("tables", [])
    if not isinstance(table_entries, list) or not table_entries:
        raise ValueError("database_snapshot_missing")
    schema = get_identity_schema()
    names = [str(item["name"]) for item in table_entries]
    payloads: dict[str, str] = {}
    with zipfile.ZipFile(archive, "r") as zf:
        for item in table_entries:
            name = str(item["name"])
            raw = zf.read(str(item["entry"]))
            digest = hashlib.sha256(raw).hexdigest()
            if digest != item.get("sha256"):
                raise ValueError("database_snapshot_hash_mismatch")
            rows = [json.loads(line) for line in raw.splitlines() if line]
            payloads[name] = json.dumps(rows, ensure_ascii=False)

    async with database_session() as session:
        await session.execute(text("SET LOCAL row_security = off"))
        current_result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=:schema AND table_type='BASE TABLE'"
            ),
            {"schema": schema},
        )
        current = {str(row[0]) for row in current_result}
        if current != set(names):
            raise ValueError("database_schema_mismatch")
        targets = [
            f"{_quote_identifier(schema)}.{_quote_identifier(name)}"
            for name in sorted(names)
        ]
        for target in targets:
            await session.execute(text(f"ALTER TABLE {target} DISABLE TRIGGER ALL"))
        await session.execute(text(f"TRUNCATE {', '.join(targets)} CASCADE"))
        for name in sorted(names):
            if payloads[name] == "[]":
                continue
            target = f"{_quote_identifier(schema)}.{_quote_identifier(name)}"
            await session.execute(
                text(
                    f"INSERT INTO {target} SELECT * FROM "
                    f"json_populate_recordset(NULL::{target}, CAST(:payload AS json))"
                ),
                {"payload": payloads[name]},
            )
        for target in targets:
            await session.execute(text(f"ALTER TABLE {target} ENABLE TRIGGER ALL"))


def read_platform_manifest(backup_id: str) -> dict[str, Any]:
    archive = find_zip_path(backup_id)
    if archive is None:
        raise FileNotFoundError(f"Backup not found: {backup_id}")
    with zipfile.ZipFile(archive, "r") as zf:
        if _PLATFORM_MANIFEST_PATH not in zf.namelist():
            return {}
        return json.loads(zf.read(_PLATFORM_MANIFEST_PATH))


async def create_pre_restore_backup() -> str:
    """在任何恢复写入前创建覆盖当前平台状态的本地签名备份。"""
    from ..backup._ops.create import create_stream
    from ..backup.models import BackupScope, CreateBackupRequest
    from ..config.utils import load_config

    request = CreateBackupRequest(
        name=f"Pre-restore protection {int(time.time())}",
        description="Automatically created before a platform restore.",
        scope=BackupScope(
            include_agents=True,
            include_global_config=True,
            include_secrets=True,
            include_skill_pool=True,
        ),
        agents=sorted(load_config().agents.profiles),
    )
    backup_id: str | None = None
    async for event in create_stream(request):
        if event.get("type") == "error":
            raise RuntimeError("pre_restore_backup_failed")
        if event.get("type") == "done":
            backup_id = str(event["meta"]["id"])
    if backup_id is None:
        raise RuntimeError("pre_restore_backup_incomplete")
    await append_platform_snapshot(backup_id)
    return backup_id


def _request_digest(backup_id: str, req: RestoreBackupRequest, actor_id: str) -> str:
    payload = {
        "backup_id": backup_id,
        "actor_id": actor_id,
        "request": req.model_dump(mode="json", exclude={"confirmation_token"}),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def create_restore_preview(
    backup_id: str,
    req: RestoreBackupRequest,
    detail: BackupDetail,
    *,
    actor_id: str,
    now: int | None = None,
) -> RestoreImpact:
    current = int(time.time()) if now is None else now
    expires_at = current + _TOKEN_TTL_SECONDS
    nonce = hashlib.sha256(f"{time.time_ns()}:{backup_id}".encode()).hexdigest()[:24]
    claims = {
        "digest": _request_digest(backup_id, req, actor_id),
        "exp": expires_at,
        "nonce": nonce,
    }
    raw = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(get_signing_key(), raw, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(raw + signature).decode().rstrip("=")
    with _TOKEN_LOCK:
        _ISSUED_TOKENS[token] = float(expires_at)
        for issued, expiry in list(_ISSUED_TOKENS.items()):
            if expiry < current:
                _ISSUED_TOKENS.pop(issued, None)

    requested_agents = set(req.agent_ids) if req.include_agents else set()
    agents = sorted(requested_agents.intersection(detail.workspace_stats))
    components = []
    if agents:
        components.append("workspaces")
    if req.include_global_config:
        components.extend(["database", "global_config", "content_store"])
    if req.include_skill_pool:
        components.append("skill_pool")
    if req.include_secrets:
        components.append("secret_store")
    return RestoreImpact(
        backup_id=backup_id,
        mode=req.mode,
        agents=agents,
        components=components,
        platform_manifest=read_platform_manifest(backup_id),
        confirmation_token=token,
        expires_at=expires_at,
    )


def consume_restore_confirmation(
    token: str | None,
    backup_id: str,
    req: RestoreBackupRequest,
    *,
    actor_id: str,
    now: int | None = None,
) -> None:
    if not token:
        raise RestoreConfirmationError("restore_confirmation_required")
    current = int(time.time()) if now is None else now
    padding = "=" * (-len(token) % 4)
    try:
        signed = base64.urlsafe_b64decode(token + padding)
        raw, signature = signed[:-32], signed[-32:]
        claims = json.loads(raw)
    except Exception as exc:
        raise RestoreConfirmationError("restore_confirmation_invalid") from exc
    expected = hmac.new(get_signing_key(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise RestoreConfirmationError("restore_confirmation_invalid")
    if int(claims.get("exp", 0)) < current:
        raise RestoreConfirmationError("restore_confirmation_expired")
    if claims.get("digest") != _request_digest(backup_id, req, actor_id):
        raise RestoreConfirmationError("restore_confirmation_scope_changed")
    with _TOKEN_LOCK:
        expiry = _ISSUED_TOKENS.pop(token, None)
    if expiry is None:
        raise RestoreConfirmationError("restore_confirmation_used_or_unknown")
