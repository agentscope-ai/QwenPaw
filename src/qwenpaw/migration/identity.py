"""旧单用户身份到 PostgreSQL 用户表的幂等迁移。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from ..constant import SECRET_DIR
from ..identity.models import LegacyAdminCredential
from ..identity.passwords import PasswordManager
from .common import (
    content_hash,
    file_hash,
    migration_session,
    read_json,
    stable_uuid,
    table,
)
from .report import MigrationExecutionReport, MigrationRejectedItem


async def migrate_identity(
    *,
    secret_dir: Path = SECRET_DIR,
    schema: str = "qwenpaw",
    session_factory=None,
) -> MigrationExecutionReport:
    """迁移一个合法旧管理员；重复运行只核验既有行。"""
    source_path = secret_dir / "auth.json"
    empty_hash = file_hash(source_path)
    if not source_path.is_file():
        target_count, target_hash = await _target_snapshot(schema, session_factory)
        return MigrationExecutionReport(
            domain="identity",
            status="empty",
            execution_order=1,
            source_count=0,
            target_count=target_count,
            inserted_count=0,
            unchanged_count=0,
            source_hash=empty_hash,
            target_hash=target_hash,
            transaction_committed=False,
        )
    try:
        auth_data = read_json(source_path)
    except (OSError, UnicodeDecodeError, ValueError):
        return await _rejected(
            "invalid_json",
            "旧身份文件无法解析",
            empty_hash,
            schema,
            session_factory,
        )

    legacy = LegacyAdminCredential.from_auth_data(auth_data)
    source_hash = file_hash(source_path)
    if legacy is None:
        return await _rejected(
            "invalid_legacy_credential",
            "旧身份凭据字段不完整或格式非法",
            source_hash,
            schema,
            session_factory,
        )

    encoded_hash = PasswordManager().encode_legacy_sha256(legacy)
    user_id = stable_uuid("identity", legacy.username)
    users = table(schema, "users")
    inserted = 0
    async with migration_session(session_factory) as session:
        result = await session.execute(
            text(
                f"INSERT INTO {users} "
                "(id,username,password_hash,status,platform_role) "
                "VALUES (:id,:username,:password_hash,'active','admin') "
                "ON CONFLICT (username) DO NOTHING RETURNING id"
            ),
            {
                "id": user_id,
                "username": legacy.username,
                "password_hash": encoded_hash,
            },
        )
        inserted = 1 if result.scalar_one_or_none() is not None else 0
        row = (
            await session.execute(
                text(
                    f"SELECT username,password_hash,status,platform_role "
                    f"FROM {users} WHERE username=:username"
                ),
                {"username": legacy.username},
            )
        ).mappings().one()

    migrated_projection = {
        "username": row["username"],
        "password_hash": row["password_hash"],
        "status": row["status"],
        "platform_role": row["platform_role"],
    }
    target_count, target_hash = await _target_snapshot(schema, session_factory)
    if inserted == 0 and migrated_projection != {
        "username": legacy.username,
        "password_hash": encoded_hash,
        "status": "active",
        "platform_role": "admin",
    }:
        return MigrationExecutionReport(
            domain="identity",
            status="rejected",
            execution_order=1,
            source_count=1,
            target_count=target_count,
            inserted_count=0,
            unchanged_count=0,
            source_hash=source_hash,
            target_hash=target_hash,
            transaction_committed=False,
            rejected=[
                MigrationRejectedItem(
                    code="target_identity_conflict",
                    source="secret/auth.json",
                    detail="目标中同名用户与旧身份凭据不一致，已拒绝覆盖",
                )
            ],
        )
    return MigrationExecutionReport(
        domain="identity",
        status="completed",
        execution_order=1,
        source_count=1,
        target_count=target_count,
        inserted_count=inserted,
        unchanged_count=1 - inserted,
        source_hash=source_hash,
        target_hash=target_hash,
        transaction_committed=True,
    )


async def _rejected(
    code: str,
    detail: str,
    source_hash: str,
    schema: str,
    session_factory,
) -> MigrationExecutionReport:
    target_count, target_hash = await _target_snapshot(schema, session_factory)
    return MigrationExecutionReport(
        domain="identity",
        status="rejected",
        execution_order=1,
        source_count=1,
        target_count=target_count,
        inserted_count=0,
        unchanged_count=0,
        source_hash=source_hash,
        target_hash=target_hash,
        transaction_committed=False,
        rejected=[
            MigrationRejectedItem(
                code=code,
                source="secret/auth.json",
                detail=detail,
            )
        ],
    )


async def _target_snapshot(schema: str, session_factory) -> tuple[int, str]:
    users = table(schema, "users")
    async with migration_session(session_factory) as session:
        rows = (
            await session.execute(
                text(
                    f"SELECT username,status,platform_role FROM {users} "
                    "ORDER BY username"
                )
            )
        ).mappings().all()
    projection = [dict(row) for row in rows]
    return len(projection), content_hash(projection)
