# -*- coding: utf-8 -*-
"""只读系统存储状态接口测试。"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.persistence.database import DatabaseHealth
from qwenpaw.persistence.mode import StorageMode
from qwenpaw.persistence.repository_provider import MigrationState


async def _async_value(value):
    return value


def _build_app(system_status_module) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[
        system_status_module.require_platform_settings_manage
    ] = lambda: None
    app.include_router(system_status_module.router, prefix="/api")
    return app


@pytest.mark.asyncio
async def test_legacy_status_is_healthy_without_touching_migration_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.app.routers import system_status

    migration_reader = pytest.fail
    monkeypatch.setattr(
        system_status,
        "check_database",
        lambda: _async_value(
            DatabaseHealth(
                connected=False,
                schema_version=None,
                storage_mode=StorageMode.LEGACY,
                error_code=None,
            )
        ),
    )
    monkeypatch.setattr(system_status, "read_migration_state", migration_reader)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_build_app(system_status)),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/system/storage-status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "legacy",
        "connected": False,
        "schema_version": None,
        "expected_schema_version": "0020_agent_personal_library",
        "schema_ready": False,
        "storage_mode": "legacy",
        "active_repository": "legacy",
        "migration_lock_state": "not_applicable",
        "domains": [],
        "error_code": None,
    }


@pytest.mark.asyncio
async def test_postgres_status_reads_schema_without_exposing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.app.routers import system_status

    monkeypatch.setattr(
        system_status,
        "check_database",
        lambda: _async_value(
            DatabaseHealth(
                connected=True,
                schema_version=None,
                storage_mode=StorageMode.POSTGRES,
                error_code=None,
            )
        ),
    )
    monkeypatch.setattr(
        system_status,
        "read_migration_state",
        lambda: _async_value(
            MigrationState(
                current_revision="0018_automation_authorization",
                expected_revision="0018_automation_authorization",
                ready=True,
                error_code=None,
            )
        ),
    )
    all_domains = ",".join(
        domain.value for domain in system_status.ALL_CUTOVER_DOMAINS
    )
    monkeypatch.setenv("QWENPAW_CUTOVER_VALIDATED_DOMAINS", all_domains)
    monkeypatch.setenv("QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS", all_domains)
    monkeypatch.setenv("QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS", all_domains)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_build_app(system_status)),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/system/storage-status")

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert payload["connected"] is True
    assert payload["schema_ready"] is True
    assert payload["schema_version"] == "0018_automation_authorization"
    assert payload["migration_lock_state"] == "locked"
    assert payload["active_repository"] == "postgres"
    assert len(payload["domains"]) == 9
    assert all(item["read_repository"] == "postgres" for item in payload["domains"])
    assert all(item["write_repository"] == "postgres" for item in payload["domains"])
    serialized = response.text.lower()
    for secret_name in ("dsn", "password", "secret", "database_url"):
        assert secret_name not in serialized


@pytest.mark.asyncio
async def test_disconnected_postgres_does_not_read_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.app.routers import system_status

    monkeypatch.setattr(
        system_status,
        "check_database",
        lambda: _async_value(
            DatabaseHealth(
                connected=False,
                schema_version=None,
                storage_mode=StorageMode.POSTGRES,
                error_code="connection_failed",
            )
        ),
    )
    monkeypatch.setattr(system_status, "read_migration_state", pytest.fail)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_build_app(system_status)),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/system/storage-status")

    payload = response.json()
    assert payload["status"] == "disconnected"
    assert payload["migration_lock_state"] == "unknown"
    assert payload["error_code"] == "connection_failed"
