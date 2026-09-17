# -*- coding: utf-8 -*-
"""平台备份必须携带数据库引用的多用户内容正文。"""

import zipfile

import pytest

from qwenpaw.backup._ops import create_helpers, restore
from qwenpaw.backup.models import BackupMeta, RestoreBackupRequest


@pytest.mark.parametrize(
    "directory",
    [
        "user_workspaces",
        "user_libraries",
        "published_workspaces",
        "media",
    ],
)
def test_platform_content_round_trip(tmp_path, monkeypatch, directory):
    source = tmp_path / "source"
    target = source / directory / "user-a" / "note.txt"
    target.parent.mkdir(parents=True)
    target.write_text("private content", encoding="utf-8")
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setattr(create_helpers, "WORKING_DIR", source)
    archive = tmp_path / "backup.zip"
    meta = BackupMeta(name="test")
    meta.scope.include_skill_pool = False
    with zipfile.ZipFile(archive, "w") as zf:
        create_helpers.add_files_to_zip(zf, meta)
    with zipfile.ZipFile(archive) as zf:
        assert (
            zf.read(f"data/platform_content/{directory}/user-a/note.txt")
            == b"private content"
        )
        destination = tmp_path / "destination"
        monkeypatch.setattr(restore, "WORKING_DIR", destination)
        monkeypatch.setattr(restore, "_stage_global_config", lambda *_args: None)
        request = RestoreBackupRequest(include_agents=False, include_skill_pool=False)
        staged, _, _, _ = restore._stage_all(zf, request, meta, [], set(), {}, set())
        assert destination / directory in staged
        for root in staged:
            restore.commit_tmp(root)
    assert (destination / directory / "user-a/note.txt").read_text(
        encoding="utf-8"
    ) == "private content"


def test_partial_backup_does_not_include_platform_content(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setattr(create_helpers, "WORKING_DIR", tmp_path)
    root = tmp_path / "user_libraries"
    root.mkdir()
    (root / "private.txt").write_text("private", encoding="utf-8")
    meta = BackupMeta(name="partial")
    meta.scope.include_global_config = False
    meta.scope.include_skill_pool = False
    with zipfile.ZipFile(tmp_path / "partial.zip", "w") as zf:
        create_helpers.add_files_to_zip(zf, meta)
        assert not any(
            name.startswith("data/platform_content/") for name in zf.namelist()
        )


def test_empty_content_snapshot_clears_newer_content(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setattr(create_helpers, "WORKING_DIR", tmp_path / "source")
    destination = tmp_path / "destination"
    newer = destination / "user_libraries" / "newer.txt"
    newer.parent.mkdir(parents=True)
    newer.write_text("newer", encoding="utf-8")
    monkeypatch.setattr(restore, "WORKING_DIR", destination)
    monkeypatch.setattr(restore, "_stage_global_config", lambda *_args: None)
    meta = BackupMeta(name="empty")
    meta.scope.include_skill_pool = False
    with zipfile.ZipFile(tmp_path / "empty.zip", "w") as zf:
        create_helpers.add_files_to_zip(zf, meta)
        req = RestoreBackupRequest(include_agents=False, include_skill_pool=False)
        staged, _, _, _ = restore._stage_all(zf, req, meta, [], set(), {}, set())
        for root in staged:
            restore.commit_tmp(root)
    assert not newer.exists()


def test_database_restore_stops_all_running_agents(monkeypatch):
    import asyncio
    from qwenpaw.backup import orchestration
    from qwenpaw.backup.models import BackupDetail

    stopped = []

    async def detail(_id):
        return BackupDetail(id="test", name="test")

    async def stop(agent_id):
        stopped.append(agent_id)
        return True

    async def database(_id):
        assert stopped == ["a", "b"]

    async def files(_id, _req):
        return BackupMeta(id="test", name="test")

    restarted = []

    async def preload(agent_id):
        await asyncio.sleep(0)
        restarted.append(agent_id)

    monkeypatch.setattr(orchestration, "get_backup", detail)
    monkeypatch.setattr(orchestration, "preflight_restore", lambda *_args: None)
    monkeypatch.setattr(orchestration, "restore", files)
    asyncio.run(
        orchestration.execute_restore(
            "test",
            RestoreBackupRequest(include_agents=False, include_skill_pool=False),
            stop_agent_fn=stop,
            list_running_agent_ids_fn=lambda: ["a", "b"],
            restore_database_fn=database,
            preload_agent_fn=preload,
        )
    )
    assert restarted == ["a", "b"]


def test_partial_platform_snapshot_does_not_export_database(tmp_path, monkeypatch):
    import asyncio
    from qwenpaw.platform_ops import backup_service

    archive = tmp_path / "partial.zip"
    meta = BackupMeta(name="partial")
    meta.scope.include_global_config = False
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("meta.json", meta.model_dump_json())
    monkeypatch.setattr(backup_service, "find_zip_path", lambda _: archive)
    monkeypatch.setattr(backup_service, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        backup_service,
        "build_platform_manifest",
        lambda: {"database": {"included": True}},
    )
    monkeypatch.setattr(
        backup_service, "replace_meta_with_local_signature", lambda *_args: None
    )

    def unexpected_database():
        pytest.fail("partial backup must not export all users' database rows")

    monkeypatch.setattr(backup_service, "database_session", unexpected_database)
    manifest = asyncio.run(backup_service.append_platform_snapshot("partial"))
    assert manifest["database"]["included"] is False


def test_platform_restores_do_not_interleave_database_and_files(monkeypatch):
    import asyncio
    from qwenpaw.backup import orchestration
    from qwenpaw.backup.models import BackupDetail

    monkeypatch.setattr(orchestration, "_ORCHESTRATION_LOCK", asyncio.Lock())

    events = []
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()

    async def detail(backup_id):
        return BackupDetail(id=backup_id, name="test")

    async def database(backup_id):
        events.append((backup_id, "database"))
        if backup_id == "a":
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()

    async def files(backup_id, _req):
        events.append((backup_id, "files"))
        return BackupMeta(id=backup_id, name="test")

    monkeypatch.setattr(orchestration, "get_backup", detail)
    monkeypatch.setattr(orchestration, "preflight_restore", lambda *_args: None)
    monkeypatch.setattr(orchestration, "restore", files)

    async def scenario():
        async def run(backup_id):
            return await orchestration.execute_restore(
                backup_id,
                RestoreBackupRequest(include_agents=False),
                restore_database_fn=database,
            )

        first = asyncio.create_task(run("a"))
        await first_started.wait()
        second = asyncio.create_task(run("b"))
        try:
            await asyncio.wait_for(second_started.wait(), timeout=0.1)
        except TimeoutError:
            pass
        finally:
            release_first.set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())
    assert events in [
        [("a", "database"), ("a", "files"), ("b", "database"), ("b", "files")],
        [("b", "database"), ("b", "files"), ("a", "database"), ("a", "files")],
    ]


def test_cancelled_restore_finishes_files_before_releasing_lock(monkeypatch):
    import asyncio
    from qwenpaw.backup import orchestration
    from qwenpaw.backup.models import BackupDetail

    monkeypatch.setattr(orchestration, "_ORCHESTRATION_LOCK", asyncio.Lock())
    started = asyncio.Event()
    release = asyncio.Event()
    completed = []

    async def detail(_id):
        return BackupDetail(id="a", name="test")

    async def files(_id, _req):
        started.set()
        await release.wait()
        completed.append(True)
        return BackupMeta(id="a", name="test")

    monkeypatch.setattr(orchestration, "get_backup", detail)
    monkeypatch.setattr(orchestration, "preflight_restore", lambda *_args: None)
    monkeypatch.setattr(orchestration, "restore", files)

    async def scenario():
        task = asyncio.create_task(
            orchestration.execute_restore("a", RestoreBackupRequest())
        )
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert orchestration._ORCHESTRATION_LOCK.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert completed == [True]
