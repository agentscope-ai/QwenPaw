# -*- coding: utf-8 -*-
"""平台备份清单与恢复确认的隔离集成测试。"""

from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import text
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uuid import UUID
from alembic import command
from alembic.config import Config

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.dependencies import get_actor
from qwenpaw.backup import orchestration
from qwenpaw.backup.models import BackupDetail, BackupMeta, RestoreBackupRequest
from qwenpaw.platform_ops import backup_service
from qwenpaw.identity.models import PlatformRole
from qwenpaw.app.routers import backup as backup_router


def _detail() -> BackupDetail:
    return BackupDetail(
        id="backup-test",
        name="Backup",
        workspace_stats={"alpha": {"files": 2, "size": 10}},
    )


def _actor(role: PlatformRole) -> ActorContext:
    return ActorContext(
        user_id=UUID("11111111-1111-4111-8111-111111111111"),
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="backup-test",
    )


def test_backup_routes_require_admin_and_restore_preview_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(backup_router.router, prefix="/api")
    monkeypatch.setattr(backup_service, "get_signing_key", lambda: b"k" * 32)
    monkeypatch.setattr(backup_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        backup_router, "get_backup", lambda _id: _async_value(_detail())
    )
    monkeypatch.setattr(backup_router, "preflight_restore", lambda *_args: None)
    monkeypatch.setattr(backup_service, "read_platform_manifest", lambda _id: {})

    app.dependency_overrides[get_actor] = lambda: _actor(PlatformRole.MEMBER)
    with TestClient(app) as client:
        assert client.get("/api/backups").status_code == 403

    app.dependency_overrides[get_actor] = lambda: _actor(PlatformRole.ADMIN)
    request = {"include_agents": True, "agent_ids": ["alpha"]}
    with TestClient(app) as client:
        preview = client.post("/api/backups/backup-test/restore/preview", json=request)
        assert preview.status_code == 200
        assert preview.json()["agents"] == ["alpha"]
        missing = client.post("/api/backups/backup-test/restore", json=request)
        assert missing.status_code == 409
        assert missing.json()["detail"]["code"] == "restore_confirmation_required"


async def _async_value(value):
    return value


def test_restore_confirmation_is_scoped_one_time_and_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backup_service, "get_signing_key", lambda: b"k" * 32)
    monkeypatch.setattr(
        backup_service,
        "read_platform_manifest",
        lambda _backup_id: {"database": {"included": True}},
    )
    request = RestoreBackupRequest(agent_ids=["alpha"])
    preview = backup_service.create_restore_preview(
        "backup-test",
        request,
        _detail(),
        actor_id="admin-1",
        now=100,
    )
    assert preview.agents == ["alpha"]
    assert "database" in preview.components

    backup_service.consume_restore_confirmation(
        preview.confirmation_token,
        "backup-test",
        request,
        actor_id="admin-1",
        now=101,
    )
    with pytest.raises(backup_service.RestoreConfirmationError, match="used"):
        backup_service.consume_restore_confirmation(
            preview.confirmation_token,
            "backup-test",
            request,
            actor_id="admin-1",
            now=102,
        )


def test_restore_confirmation_rejects_changed_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backup_service, "get_signing_key", lambda: b"k" * 32)
    monkeypatch.setattr(backup_service, "read_platform_manifest", lambda _id: {})
    request = RestoreBackupRequest(agent_ids=["alpha"])
    preview = backup_service.create_restore_preview(
        "backup-test", request, _detail(), actor_id="admin-1", now=100
    )
    changed = request.model_copy(update={"include_secrets": True})
    with pytest.raises(backup_service.RestoreConfirmationError, match="scope_changed"):
        backup_service.consume_restore_confirmation(
            preview.confirmation_token,
            "backup-test",
            changed,
            actor_id="admin-1",
            now=101,
        )


def test_legacy_platform_snapshot_adds_manifest_and_resigns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "backup.zip"
    meta = BackupMeta(id="backup-test", name="Backup")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("meta.json", meta.model_dump_json())
    monkeypatch.setattr(backup_service, "find_zip_path", lambda _id: archive)
    monkeypatch.setattr(backup_service, "is_multi_user_enabled", lambda: False)
    monkeypatch.setattr(
        backup_service,
        "build_platform_manifest",
        lambda: {
            "database": {"included": False},
            "workspaces": {"version": "sha256:test"},
            "content_store": {"version": "sha256:test"},
            "secret_store": {"version": "sha256:test", "values_exposed": False},
        },
    )
    resigned: list[str] = []
    monkeypatch.setattr(
        backup_service,
        "replace_meta_with_local_signature",
        lambda _archive, restored_meta: resigned.append(restored_meta.id),
    )

    manifest = asyncio.run(backup_service.append_platform_snapshot("backup-test"))

    with zipfile.ZipFile(archive) as zf:
        stored = json.loads(zf.read("platform/manifest.json"))
    assert stored == manifest
    assert set(stored) == {
        "database",
        "workspaces",
        "content_store",
        "secret_store",
    }
    assert resigned == ["backup-test"]


def test_pre_restore_backup_runs_after_preflight_and_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fake_get_backup(_backup_id: str) -> BackupDetail:
        return _detail()

    def fake_preflight(_backup_id: str, _req: RestoreBackupRequest) -> None:
        events.append("preflight")

    async def fake_protection() -> str:
        events.append("protection")
        return "protection-id"

    async def fake_stop(_agent_id: str) -> bool:
        events.append("stop")
        return True

    async def fake_restore(_backup_id: str, _req: RestoreBackupRequest) -> BackupMeta:
        events.append("restore")
        return BackupMeta(id="backup-test", name="Backup")

    monkeypatch.setattr(orchestration, "get_backup", fake_get_backup)
    monkeypatch.setattr(orchestration, "preflight_restore", fake_preflight)
    monkeypatch.setattr(orchestration, "restore", fake_restore)
    asyncio.run(
        orchestration.execute_restore(
            "backup-test",
            RestoreBackupRequest(agent_ids=["alpha"]),
            create_pre_restore_backup_fn=fake_protection,
            stop_agent_fn=fake_stop,
        )
    )
    assert events == ["preflight", "stop", "protection", "restore"]


def test_file_failure_rolls_database_back_to_protection_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restored_databases: list[str] = []
    restored_files: list[str] = []

    async def fake_get_backup(_backup_id: str) -> BackupDetail:
        return _detail()

    async def fake_protection() -> str:
        return "protection-id"

    async def fake_database(backup_id: str) -> None:
        restored_databases.append(backup_id)

    async def failing_restore(backup_id: str, _req: RestoreBackupRequest):
        restored_files.append(backup_id)
        if backup_id == "backup-test":
            raise RuntimeError("file restore failed")
        return BackupMeta(id=backup_id, name="Protection")

    monkeypatch.setattr(orchestration, "get_backup", fake_get_backup)
    monkeypatch.setattr(orchestration, "preflight_restore", lambda *_args: None)
    monkeypatch.setattr(orchestration, "restore", failing_restore)
    with pytest.raises(RuntimeError, match="file restore failed"):
        asyncio.run(
            orchestration.execute_restore(
                "backup-test",
                RestoreBackupRequest(include_agents=False),
                create_pre_restore_backup_fn=fake_protection,
                restore_database_fn=fake_database,
            )
        )
    assert restored_databases == ["backup-test", "protection-id"]
    assert restored_files == ["backup-test", "protection-id"]


@pytest.mark.integration
def test_postgres_snapshot_round_trip_is_transactional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_test_schema,
) -> None:
    archive = tmp_path / "platform.zip"
    meta = BackupMeta(id="backup-test", name="Backup")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("meta.json", meta.model_dump_json())

    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_STORAGE_MODE", "postgres")
    monkeypatch.setenv("QWENPAW_DATABASE_URL", postgres_test_schema.async_url())
    monkeypatch.setenv("QWENPAW_DATABASE_SCHEMA", postgres_test_schema.name)
    monkeypatch.setattr(backup_service, "find_zip_path", lambda _id: archive)
    monkeypatch.setattr(
        backup_service,
        "replace_meta_with_local_signature",
        lambda _archive, restored_meta: restored_meta,
    )

    async def scenario() -> tuple[list[str], list[str]]:
        from qwenpaw.persistence import database as database_module
        from qwenpaw.persistence.database import database_session

        schema = f'"{postgres_test_schema.name}"'
        async with database_session() as session:
            await session.execute(
                text(
                    f"CREATE TABLE {schema}.parent (id integer PRIMARY KEY, value text)"
                )
            )
            await session.execute(
                text(
                    f"CREATE TABLE {schema}.child (id integer PRIMARY KEY, parent_id integer "
                    f"REFERENCES {schema}.parent(id), value text)"
                )
            )
            await session.execute(
                text(f"INSERT INTO {schema}.parent VALUES (1, 'before')")
            )
            await session.execute(
                text(f"INSERT INTO {schema}.child VALUES (1, 1, 'before')")
            )
        await backup_service.append_platform_snapshot("backup-test")
        async with database_session() as session:
            await session.execute(text(f"UPDATE {schema}.parent SET value='after'"))
            await session.execute(text(f"UPDATE {schema}.child SET value='after'"))
        await backup_service.restore_platform_database("backup-test")
        async with database_session() as session:
            parents = [
                str(row[0])
                for row in await session.execute(
                    text(f"SELECT value FROM {schema}.parent")
                )
            ]
            children = [
                str(row[0])
                for row in await session.execute(
                    text(f"SELECT value FROM {schema}.child")
                )
            ]
        if database_module._engine is not None:
            await database_module._engine.dispose()
        database_module._engine = None
        database_module._engine_dsn = None
        database_module._session_factory = None
        return parents, children

    parents, children = asyncio.run(scenario())
    assert parents == ["before"]
    assert children == ["before"]


@pytest.mark.integration
def test_full_migrated_schema_with_foreign_key_cycles_round_trips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_test_schema,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    alembic = Config(str(project_root / "alembic.ini"))
    alembic.set_main_option("script_location", str(project_root / "migrations"))
    alembic.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    alembic.attributes["target_schema"] = postgres_test_schema.name
    command.upgrade(alembic, "head")

    archive = tmp_path / "full-schema.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "meta.json",
            BackupMeta(id="backup-full", name="Full").model_dump_json(),
        )
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_STORAGE_MODE", "postgres")
    monkeypatch.setenv("QWENPAW_DATABASE_URL", postgres_test_schema.async_url())
    monkeypatch.setenv("QWENPAW_DATABASE_SCHEMA", postgres_test_schema.name)
    monkeypatch.setattr(backup_service, "find_zip_path", lambda _id: archive)
    monkeypatch.setattr(
        backup_service,
        "replace_meta_with_local_signature",
        lambda _archive, restored_meta: restored_meta,
    )

    async def scenario() -> str:
        from qwenpaw.persistence import database as database_module
        from qwenpaw.persistence.database import database_session

        schema = f'"{postgres_test_schema.name}"'
        async with database_session() as session:
            await session.execute(
                text(
                    f"INSERT INTO {schema}.users "
                    "(id,username,password_hash,status,platform_role) VALUES "
                    "('11111111-1111-4111-8111-111111111111','before','hash','active','admin')"
                )
            )
        await backup_service.append_platform_snapshot("backup-full")
        async with database_session() as session:
            await session.execute(text(f"UPDATE {schema}.users SET username='after'"))
        await backup_service.restore_platform_database("backup-full")
        async with database_session() as session:
            username = (
                await session.execute(text(f"SELECT username FROM {schema}.users"))
            ).scalar_one()
        if database_module._engine is not None:
            await database_module._engine.dispose()
        database_module._engine = None
        database_module._engine_dsn = None
        database_module._session_factory = None
        return str(username)

    assert asyncio.run(scenario()) == "before"
