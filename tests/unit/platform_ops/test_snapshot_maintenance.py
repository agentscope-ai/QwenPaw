"""Platform snapshot holds one maintenance lease across files and SQL."""

import asyncio
from contextlib import asynccontextmanager

from qwenpaw.backup.models import CreateBackupRequest
from qwenpaw.platform_ops import backup_service


def test_platform_stream_holds_exclusive_until_database_snapshot(monkeypatch):
    active = []
    from qwenpaw.platform_ops import maintenance
    from qwenpaw.backup._ops import create

    @asynccontextmanager
    async def exclusive():
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    async def files(_req):
        assert active
        yield {"type": "done", "meta": {"id": "backup"}}

    async def snapshot(_id):
        assert active

    monkeypatch.setattr(maintenance, "exclusive", exclusive)
    monkeypatch.setattr(create, "create_stream", files)
    monkeypatch.setattr(backup_service, "append_platform_snapshot", snapshot)

    async def scenario():
        return [
            event
            async for event in backup_service.create_platform_stream(
                CreateBackupRequest(name="test")
            )
        ]

    assert asyncio.run(scenario()) == [{"type": "done", "meta": {"id": "backup"}}]
    assert not active


def test_restore_mutations_and_rollback_hold_exclusive(tmp_path, monkeypatch):
    from qwenpaw.backup import orchestration
    from qwenpaw.backup.models import BackupDetail, RestoreBackupRequest
    from qwenpaw.platform_ops import maintenance

    coordinator = maintenance.MaintenanceCoordinator(tmp_path)
    monkeypatch.setattr(maintenance, "exclusive", coordinator.exclusive)
    stages = []

    async def detail(_id):
        return BackupDetail(id="backup", name="test")

    async def protection():
        assert maintenance.maintenance_active()
        return "protection"

    async def database(backup_id):
        assert maintenance.maintenance_active()
        stages.append(backup_id)

    async def files(backup_id, _req):
        assert maintenance.maintenance_active()
        if backup_id == "backup":
            raise ValueError("simulated file failure")

    monkeypatch.setattr(orchestration, "get_backup", detail)
    monkeypatch.setattr(orchestration, "preflight_restore", lambda *_args: None)
    monkeypatch.setattr(orchestration, "restore", files)

    async def scenario():
        import pytest

        with pytest.raises(ValueError, match="simulated"):
            await orchestration.execute_restore(
                "backup",
                RestoreBackupRequest(include_agents=False),
                create_pre_restore_backup_fn=protection,
                restore_database_fn=database,
            )

    asyncio.run(scenario())
    assert stages == ["backup", "protection"]


def test_legacy_incomplete_archive_is_rejected_before_platform_restore(
    tmp_path, monkeypatch
):
    import pytest
    import zipfile
    from qwenpaw.backup.models import RestoreBackupRequest

    archive = tmp_path / "old.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("platform/manifest.json", '{"database":{"included":true}}')
    monkeypatch.setattr(backup_service, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(backup_service, "find_zip_path", lambda _: archive)
    with pytest.raises(ValueError, match="platform_backup_incomplete"):
        backup_service.validate_platform_restore("old", RestoreBackupRequest())


def test_disconnected_backup_waits_for_snapshot_before_unlock(tmp_path, monkeypatch):
    from qwenpaw.platform_ops import maintenance
    from qwenpaw.backup._ops import create

    coordinator = maintenance.MaintenanceCoordinator(tmp_path, timeout=0.05)
    monkeypatch.setattr(maintenance, "exclusive", coordinator.exclusive)
    release = asyncio.Event()
    completed = []

    async def files(_req):
        yield {"type": "start"}
        await release.wait()
        yield {"type": "done", "meta": {"id": "backup"}}

    async def snapshot(_id):
        assert maintenance.maintenance_active()
        completed.append(True)

    monkeypatch.setattr(create, "create_stream", files)
    monkeypatch.setattr(backup_service, "append_platform_snapshot", snapshot)

    async def scenario():
        import pytest

        stream = backup_service.create_platform_stream(CreateBackupRequest(name="test"))
        assert await anext(stream) == {"type": "start"}
        close = asyncio.create_task(stream.aclose())
        with pytest.raises(maintenance.MaintenanceBusy):
            async with coordinator.operation():
                pass
        release.set()
        await close
        async with coordinator.exclusive():
            pass

    asyncio.run(scenario())
    assert completed == [True]


def test_database_transaction_cannot_enter_during_snapshot(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    import pytest
    from qwenpaw.persistence import database
    from qwenpaw.platform_ops import maintenance

    coordinator = maintenance.MaintenanceCoordinator(tmp_path, timeout=0.05)
    monkeypatch.setattr(maintenance, "operation", coordinator.operation)
    entered = []

    class Factory:
        @asynccontextmanager
        async def begin(self):
            entered.append(True)
            yield "session"

    monkeypatch.setattr(database, "_get_session_factory", lambda: Factory())

    async def transaction():
        async with database.database_session():
            pass

    async def scenario():
        async with coordinator.exclusive():
            with pytest.raises(maintenance.MaintenanceBusy):
                await asyncio.create_task(transaction())
            assert not entered
        await transaction()

    asyncio.run(scenario())
    assert entered == [True]
