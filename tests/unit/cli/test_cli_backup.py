# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw backup`` CLI surface."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from click.testing import CliRunner

from qwenpaw.backup.models import BackupMeta, DeleteBackupsResponse
from qwenpaw.cli.main import cli


def test_backup_group_is_registered() -> None:
    result = CliRunner().invoke(cli, ["backup", "--help"])

    assert result.exit_code == 0
    assert "create" in result.output
    assert "restore" in result.output
    assert "prune" in result.output


def test_backups_alias_is_registered() -> None:
    result = CliRunner().invoke(cli, ["backups", "--help"])

    assert result.exit_code == 0
    assert "delete" in result.output


def test_backup_create_accepts_multiple_agents(monkeypatch) -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"agent_a": object(), "agent_b": object()},
            agent_order=["agent_b", "agent_a"],
        ),
    )
    captured = {}

    monkeypatch.setattr("qwenpaw.cli.backup_cmd.load_config", lambda: config)

    async def create_stream(req):
        captured["req"] = req
        yield {
            "type": "done",
            "meta": {
                "id": "backup-1",
                "name": req.name,
                "agents": req.agents,
                "scope": req.scope.model_dump(mode="json"),
            },
        }

    monkeypatch.setattr("qwenpaw.cli.backup_cmd.create_stream", create_stream)

    result = CliRunner().invoke(
        cli,
        [
            "backup",
            "create",
            "--name",
            "selected",
            "--agent",
            "agent_a",
            "--agent",
            "agent_b",
        ],
    )

    assert result.exit_code == 0
    assert '"id": "backup-1"' in result.output
    assert captured["req"].agents == ["agent_a", "agent_b"]
    assert captured["req"].scope.include_agents is True
    assert captured["req"].scope.include_secrets is False


def test_backup_create_defaults_to_all_agents(monkeypatch) -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"agent_a": object(), "agent_b": object()},
            agent_order=["agent_b", "agent_a"],
        ),
    )
    captured = {}

    monkeypatch.setattr("qwenpaw.cli.backup_cmd.load_config", lambda: config)

    async def create_stream(req):
        captured["agents"] = req.agents
        yield {"type": "done", "meta": {"id": "backup-1"}}

    monkeypatch.setattr("qwenpaw.cli.backup_cmd.create_stream", create_stream)

    result = CliRunner().invoke(cli, ["backup", "create"])

    assert result.exit_code == 0
    assert captured["agents"] == ["agent_b", "agent_a"]


def test_backup_create_full_marks_agent_scope_when_empty(monkeypatch) -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={},
            agent_order=[],
        ),
    )
    captured = {}

    monkeypatch.setattr("qwenpaw.cli.backup_cmd.load_config", lambda: config)

    async def create_stream(req):
        captured["scope"] = req.scope
        yield {"type": "done", "meta": {"id": "backup-1"}}

    monkeypatch.setattr("qwenpaw.cli.backup_cmd.create_stream", create_stream)

    result = CliRunner().invoke(cli, ["backup", "create", "--full"])

    assert result.exit_code == 0
    assert captured["scope"].include_agents is True
    assert captured["scope"].include_secrets is True


def test_backup_delete_yes_skips_confirmation(monkeypatch) -> None:
    captured = {}

    async def delete_backups(ids):
        captured["ids"] = ids
        return DeleteBackupsResponse(deleted=ids)

    monkeypatch.setattr(
        "qwenpaw.cli.backup_cmd.delete_backups",
        delete_backups,
    )

    result = CliRunner().invoke(
        cli,
        ["backup", "delete", "backup-1", "backup-2", "--yes"],
    )

    assert result.exit_code == 0
    assert "Continue with deletion?" not in result.output
    assert captured["ids"] == ["backup-1", "backup-2"]
    assert '"deleted": [' in result.output


def test_backup_prune_dry_run_keeps_newest(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    backups = [
        BackupMeta(name="newest", id="backup-new", created_at=now),
        BackupMeta(
            name="old",
            id="backup-old",
            created_at=now - timedelta(days=4),
        ),
        BackupMeta(
            name="older",
            id="backup-older",
            created_at=now - timedelta(days=8),
        ),
    ]

    async def list_backups():
        return backups

    monkeypatch.setattr("qwenpaw.cli.backup_cmd.list_backups", list_backups)

    result = CliRunner().invoke(
        cli,
        ["backup", "prune", "--keep-last", "1", "--dry-run"],
    )

    assert result.exit_code == 0
    assert '"dry_run": true' in result.output
    assert '"id": "backup-new"' not in result.output
    assert '"id": "backup-old"' in result.output
    assert '"id": "backup-older"' in result.output
