# -*- coding: utf-8 -*-
"""Task 1.1 数据库配置、事务边界与脱敏健康状态契约。"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI


def _settings_module():
    return importlib.import_module("qwenpaw.persistence.settings")


def _database_module():
    return importlib.import_module("qwenpaw.persistence.database")


def test_missing_dsn_keeps_legacy_mode_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QWENPAW_DATABASE_URL", raising=False)
    monkeypatch.delenv("QWENPAW_MULTI_USER_ENABLED", raising=False)
    monkeypatch.delenv("QWENPAW_STORAGE_MODE", raising=False)

    settings = _settings_module().load_database_settings()

    assert settings.multi_user_enabled is False
    assert settings.storage_mode == "legacy"
    assert settings.dsn is None


def test_multi_user_without_dsn_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _settings_module()
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.delenv("QWENPAW_STORAGE_MODE", raising=False)
    monkeypatch.delenv("QWENPAW_DATABASE_URL", raising=False)

    with pytest.raises(module.DatabaseConfigurationError) as caught:
        module.load_database_settings()

    assert caught.value.error_code == "database_url_required"
    assert caught.value.storage_mode == "postgres"


def test_multi_user_rejects_legacy_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _settings_module()
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_STORAGE_MODE", "legacy")
    monkeypatch.setenv(
        "QWENPAW_DATABASE_URL",
        "postgresql://admin:top-secret@127.0.0.1/qwenpaw",
    )

    with pytest.raises(module.DatabaseConfigurationError) as caught:
        module.load_database_settings()

    assert caught.value.error_code == "postgres_storage_required"
    assert "top-secret" not in str(caught.value)


def test_postgres_dsn_is_normalized_and_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_STORAGE_MODE", "postgres")
    monkeypatch.setenv(
        "QWENPAW_DATABASE_URL",
        "postgresql://admin:top-secret@127.0.0.1/qwenpaw",
    )

    settings = _settings_module().load_database_settings()

    assert settings.dsn == (
        "postgresql+asyncpg://admin:top-secret@127.0.0.1/qwenpaw"
    )
    assert "top-secret" not in repr(settings)
    assert "admin" not in settings.safe_database_target
    assert settings.safe_database_target == "127.0.0.1/qwenpaw"


@pytest.mark.asyncio
async def test_legacy_health_does_not_open_database_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _database_module()
    settings_module = _settings_module()
    monkeypatch.setattr(
        module,
        "load_database_settings",
        lambda: settings_module.DatabaseSettings(
            multi_user_enabled=False,
            storage_mode="legacy",
            dsn=None,
            safe_database_target=None,
        ),
    )
    monkeypatch.setattr(
        module,
        "_get_engine",
        lambda _settings: pytest.fail("legacy 模式不应创建数据库连接"),
    )

    health = await module.check_database()

    assert health == module.DatabaseHealth(
        connected=False,
        schema_version=None,
        storage_mode="legacy",
        error_code=None,
    )


@pytest.mark.asyncio
async def test_connection_failure_returns_sanitized_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _database_module()
    settings_module = _settings_module()

    class BrokenEngine:
        @asynccontextmanager
        async def connect(self):
            raise RuntimeError(
                "cannot connect postgresql://admin:top-secret@"
                "db.internal/qwenpaw",
            )
            yield  # pragma: no cover

    monkeypatch.setattr(
        module,
        "load_database_settings",
        lambda: settings_module.DatabaseSettings(
            multi_user_enabled=True,
            storage_mode="postgres",
            dsn="postgresql+asyncpg://admin:top-secret@db.internal/qwenpaw",
            safe_database_target="db.internal/qwenpaw",
        ),
    )
    monkeypatch.setattr(
        module, "_get_engine", lambda _settings: BrokenEngine()
    )

    health = await module.check_database()

    assert health.error_code == "connection_failed"
    assert health.connected is False
    assert "top-secret" not in repr(health)
    assert "db.internal" not in repr(health)


@pytest.mark.asyncio
async def test_database_session_uses_committing_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _database_module()
    events: list[str] = []
    expected_session = object()

    class FakeSessionFactory:
        @asynccontextmanager
        async def begin(self):
            events.append("begin")
            yield expected_session
            events.append("commit")

    monkeypatch.setattr(
        module, "_get_session_factory", lambda: FakeSessionFactory()
    )

    async with module.database_session() as session:
        assert session is expected_session
        events.append("body")

    assert events == ["begin", "body", "commit"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("health", "expected_status"),
    [
        ({"connected": False, "storage_mode": "legacy"}, "legacy"),
        ({"connected": False, "storage_mode": "postgres"}, "disconnected"),
        ({"connected": True, "storage_mode": "postgres"}, "ready"),
    ],
)
async def test_storage_status_exposes_three_public_states(
    monkeypatch: pytest.MonkeyPatch,
    health: dict[str, object],
    expected_status: str,
) -> None:
    database = _database_module()
    system_status = importlib.import_module(
        "qwenpaw.app.routers.system_status"
    )
    value = database.DatabaseHealth(
        connected=bool(health["connected"]),
        schema_version=None,
        storage_mode=health["storage_mode"],
        error_code=None if health["connected"] else "connection_failed",
    )
    monkeypatch.setattr(
        system_status,
        "check_database",
        lambda: _async_value(value),
    )

    app = FastAPI()
    app.include_router(system_status.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/system/storage-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["storage_mode"] == health["storage_mode"]
    assert payload["active_repository"] == "legacy"
    assert "migration_lock_state" in payload
    assert "dsn" not in payload


async def _async_value(value):
    return value


def test_app_startup_validates_storage_before_legacy_migration() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "src/qwenpaw/app/_app.py"
    ).read_text(encoding="utf-8")

    validation = source.index(
        "load_database_settings()", source.index("def lifespan")
    )
    legacy_migration = source.index(
        "migrate_legacy_workspace_to_default_agent()",
        source.index("def lifespan"),
    )

    assert validation < legacy_migration
