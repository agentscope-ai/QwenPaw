# -*- coding: utf-8 -*-
"""Task 13.3：生产多用户路径不得写入 Legacy 业务事实。"""

from __future__ import annotations

from pathlib import Path

import pytest


def _settings(*, multi_user: bool, mode: str):
    return type(
        "Settings",
        (),
        {"multi_user_enabled": multi_user, "storage_mode": mode},
    )()


def test_legacy_write_gate_blocks_multi_user_and_allows_single_user() -> None:
    from qwenpaw.persistence.repository_provider import (
        CutoverDomain,
        LegacyWriteBlockedError,
        assert_legacy_write_allowed,
    )

    with pytest.raises(LegacyWriteBlockedError) as caught:
        assert_legacy_write_allowed(
            CutoverDomain.INBOX,
            settings_loader=lambda: _settings(multi_user=True, mode="postgres"),
        )
    assert caught.value.error_code == "legacy_write_blocked"

    assert_legacy_write_allowed(
        CutoverDomain.INBOX,
        settings_loader=lambda: _settings(multi_user=False, mode="legacy"),
    )


def test_auth_plaintext_read_does_not_rewrite_in_multi_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.app import auth

    auth_file = tmp_path / "auth.json"
    auth_file.write_text('{"jwt_secret":"plain-secret"}', encoding="utf-8")
    monkeypatch.setattr(auth, "AUTH_FILE", auth_file)
    monkeypatch.setattr(auth, "is_multi_user_enabled", lambda: True)
    rewritten = []
    monkeypatch.setattr(auth, "_save_auth_data", lambda data: rewritten.append(data))

    assert auth._load_auth_data()["jwt_secret"] == "plain-secret"
    assert rewritten == []


def test_auth_legacy_writer_is_blocked_in_multi_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.app import auth
    from qwenpaw.persistence.repository_provider import LegacyWriteBlockedError

    auth_file = tmp_path / "auth.json"
    monkeypatch.setattr(auth, "AUTH_FILE", auth_file)
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_STORAGE_MODE", "postgres")
    monkeypatch.setenv(
        "QWENPAW_DATABASE_URL",
        "postgresql://user:password@localhost/database",
    )

    with pytest.raises(LegacyWriteBlockedError):
        auth._save_auth_data({"jwt_secret": "plain-secret"})
    assert not auth_file.exists()


def test_workspace_skips_legacy_rewrite_migrations_in_multi_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.app.workspace import workspace as workspace_module

    monkeypatch.setattr(workspace_module, "is_multi_user_enabled", lambda: True)
    workspace = object.__new__(workspace_module.Workspace)
    workspace.agent_id = "agent-a"
    workspace.workspace_dir = tmp_path

    workspace._migrate_legacy_weixin_data()

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_multi_user_inbox_write_never_calls_legacy_file_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.app import inbox_store

    class Repository:
        async def append_event(self, **payload):
            return {"id": "pg-event", **payload}

    monkeypatch.setattr(inbox_store, "_postgres_repository", lambda: Repository())
    monkeypatch.setattr(
        inbox_store,
        "_save_events",
        lambda events: pytest.fail("Legacy inbox writer was called"),
    )

    event = await inbox_store.append_event(
        agent_id="agent-a",
        source_type="task",
        source_id="source-a",
        event_type="completed",
        status="success",
        title="done",
        body="done",
        recipient_user_id="00000000-0000-0000-0000-000000000001",
    )
    assert event["id"] == "pg-event"


def test_multi_user_token_manager_uses_only_postgres_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.token_usage import manager
    from qwenpaw.token_usage import postgres_buffer
    from qwenpaw.persistence.mode import StorageMode

    sentinel = object()
    monkeypatch.setattr(
        manager,
        "load_database_settings",
        lambda: _settings(multi_user=True, mode=StorageMode.POSTGRES),
    )
    monkeypatch.setattr(postgres_buffer, "PostgresUsageBuffer", lambda **_: sentinel)
    monkeypatch.setattr(manager.TokenUsageManager, "_instance", None)

    usage = manager.TokenUsageManager()

    assert usage._postgres is True
    assert usage._buffer is sentinel


@pytest.mark.asyncio
async def test_cron_repository_selection_has_one_write_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.app.workspace import workspace as workspace_module

    postgres = object()
    monkeypatch.setattr(workspace_module, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(workspace_module, "PostgresJobRepository", lambda **_: postgres)
    monkeypatch.setattr(
        "qwenpaw.automation.grants.build_automation_authorization_service",
        lambda repository, agent_id: (repository, agent_id),
    )
    monkeypatch.setattr(
        "qwenpaw.identity.runtime.get_identity_schema",
        lambda: "qwenpaw",
    )
    fake_workspace = type(
        "Workspace",
        (),
        {
            "agent_id": "agent-a",
            "workspace_dir": Path("unused"),
            "_service_manager": type("Services", (), {"services": {}})(),
        },
    )()

    selected = workspace_module._cron_service_args(fake_workspace)

    assert selected["repo"] is postgres


@pytest.mark.asyncio
async def test_legacy_cron_and_token_writers_remain_available_in_legacy_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.app.crons.models import JobsFile
    from qwenpaw.app.crons.repo.json_repo import JsonJobRepository
    from qwenpaw.token_usage.storage import save_data_sync

    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "false")
    monkeypatch.setenv("QWENPAW_STORAGE_MODE", "legacy")
    jobs_path = tmp_path / "jobs.json"
    token_path = tmp_path / "token_usage.json"

    await JsonJobRepository(jobs_path).save(JobsFile(jobs=[]))
    assert save_data_sync(token_path, {"2026-09-09": {}}) is True

    assert jobs_path.is_file()
    assert token_path.is_file()


def test_deployment_env_store_is_explicit_file_authority() -> None:
    from qwenpaw.envs import store

    assert store.STORAGE_AUTHORITY == "encrypted_deployment_file"
    assert "envs.json" in store.get_envs_json_path().name


def test_chat_json_is_declared_runtime_index() -> None:
    from qwenpaw.app.chats.repo import json_repo

    assert json_repo.STORAGE_AUTHORITY == "runtime_session_index"


def test_multi_user_legacy_migrations_leave_archives_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.app.chats.repo.json_repo import migrate_legacy_weixin_chats_file
    from qwenpaw.app.crons.repo.json_repo import migrate_legacy_weixin_jobs_file
    from qwenpaw.persistence.repository_provider import LegacyWriteBlockedError

    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_STORAGE_MODE", "postgres")
    monkeypatch.setenv(
        "QWENPAW_DATABASE_URL",
        "postgresql://user:password@localhost/database",
    )
    chats = tmp_path / "chats.json"
    jobs = tmp_path / "jobs.json"
    chats_payload = (
        '{"version":1,"chats":[{"id":"chat-a","session_id":"weixin:user"}]}'
    )
    jobs_payload = (
        '{"jobs":[{"dispatch":{"target":{"session_id":"weixin:user"}}}]}'
    )
    chats.write_text(chats_payload, encoding="utf-8")
    jobs.write_text(jobs_payload, encoding="utf-8")

    with pytest.raises(LegacyWriteBlockedError):
        migrate_legacy_weixin_chats_file(chats)
    with pytest.raises(LegacyWriteBlockedError):
        migrate_legacy_weixin_jobs_file(jobs)

    assert chats.read_text(encoding="utf-8") == chats_payload
    assert jobs.read_text(encoding="utf-8") == jobs_payload
    assert list(tmp_path.glob("*.bak")) == []
