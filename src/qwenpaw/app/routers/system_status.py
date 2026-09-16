# -*- coding: utf-8 -*-
"""只读系统状态接口。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...access.dependencies import require_platform_settings_manage
from ...persistence.database import check_database
from ...persistence.mode import StorageMode
from ...persistence.repository_provider import (
    ALL_CUTOVER_DOMAINS,
    EXPECTED_SCHEMA_REVISION,
    CutoverDomain,
    RepositorySelectionError,
    load_cutover_policy,
    read_migration_state,
)

router = APIRouter(
    tags=["system-status"],
    dependencies=[Depends(require_platform_settings_manage)],
)


class DomainCutoverStatus(BaseModel):
    """单个领域的无凭据切换状态。"""

    domain: CutoverDomain
    migration_validated: bool
    legacy_writes_frozen: bool
    postgres_writes_open: bool
    read_repository: StorageMode
    write_repository: StorageMode


class StorageStatusResponse(BaseModel):
    """不包含连接凭据的存储状态。"""

    status: Literal["legacy", "disconnected", "ready"]
    connected: bool
    schema_version: str | None
    expected_schema_version: str
    schema_ready: bool
    storage_mode: StorageMode
    active_repository: Literal["legacy", "postgres", "mixed"]
    migration_lock_state: Literal[
        "not_applicable", "not_configured", "locked", "unknown"
    ]
    domains: list[DomainCutoverStatus]
    error_code: str | None


def _domain_statuses(*, schema_ready: bool) -> list[DomainCutoverStatus]:
    policy = load_cutover_policy()
    rows = []
    for domain in sorted(ALL_CUTOVER_DOMAINS, key=str):
        read_postgres = schema_ready and policy.read_uses_postgres(domain)
        write_postgres = schema_ready and policy.write_uses_postgres(domain)
        rows.append(
            DomainCutoverStatus(
                domain=domain,
                migration_validated=domain in policy.validated_domains,
                legacy_writes_frozen=domain in policy.legacy_writes_frozen_domains,
                postgres_writes_open=domain in policy.postgres_writes_open_domains,
                read_repository=(
                    StorageMode.POSTGRES if read_postgres else StorageMode.LEGACY
                ),
                write_repository=(
                    StorageMode.POSTGRES if write_postgres else StorageMode.LEGACY
                ),
            )
        )
    return rows


def _active_repository(
    domains: list[DomainCutoverStatus],
) -> Literal["legacy", "postgres", "mixed"]:
    postgres_count = sum(row.read_repository is StorageMode.POSTGRES for row in domains)
    if postgres_count == 0:
        return "legacy"
    if postgres_count == len(domains):
        return "postgres"
    return "mixed"


@router.get("/system/storage-status", response_model=StorageStatusResponse)
async def get_storage_status() -> StorageStatusResponse:
    """返回只读存储状态，不暴露 DSN、密码或数据库目标。"""
    health = await check_database()
    mode = StorageMode(health.storage_mode)

    if mode is StorageMode.LEGACY:
        return StorageStatusResponse(
            status="legacy",
            connected=False,
            schema_version=None,
            expected_schema_version=EXPECTED_SCHEMA_REVISION,
            schema_ready=False,
            storage_mode=mode,
            active_repository=StorageMode.LEGACY,
            migration_lock_state="not_applicable",
            domains=[],
            error_code=health.error_code,
        )

    if not health.connected:
        return StorageStatusResponse(
            status="disconnected",
            connected=False,
            schema_version=None,
            expected_schema_version=EXPECTED_SCHEMA_REVISION,
            schema_ready=False,
            storage_mode=mode,
            active_repository=StorageMode.LEGACY,
            migration_lock_state="unknown",
            domains=[],
            error_code=health.error_code,
        )

    try:
        migration = await read_migration_state()
    except Exception:  # noqa: BLE001 - 状态接口必须隐藏驱动和连接细节
        return StorageStatusResponse(
            status="ready",
            connected=True,
            schema_version=None,
            expected_schema_version=EXPECTED_SCHEMA_REVISION,
            schema_ready=False,
            storage_mode=mode,
            active_repository=StorageMode.LEGACY,
            migration_lock_state="not_configured",
            domains=[],
            error_code="migration_state_unavailable",
        )

    try:
        domains = _domain_statuses(schema_ready=migration.ready)
    except RepositorySelectionError as exc:
        return StorageStatusResponse(
            status="ready",
            connected=True,
            schema_version=migration.current_revision,
            expected_schema_version=migration.expected_revision,
            schema_ready=migration.ready,
            storage_mode=mode,
            active_repository="legacy",
            migration_lock_state="unknown",
            domains=[],
            error_code=exc.error_code,
        )
    active_repository = _active_repository(domains)
    all_frozen = bool(domains) and all(row.legacy_writes_frozen for row in domains)
    return StorageStatusResponse(
        status="ready",
        connected=True,
        schema_version=migration.current_revision,
        expected_schema_version=migration.expected_revision,
        schema_ready=migration.ready,
        storage_mode=mode,
        active_repository=active_repository,
        migration_lock_state="locked" if all_frozen else "not_configured",
        domains=domains,
        error_code=migration.error_code,
    )
