# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw backup`` CLI surface."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from click.testing import CliRunner

from qwenpaw.cli.main import cli


class FakeResponse:
    def __init__(
        self,
        data: Any | None = None,
        *,
        status_code: int = 200,
        content: bytes = b"",
        lines: list[str] | None = None,
    ) -> None:
        self._data = data
        self.status_code = status_code
        self.content = content
        self._lines = lines or []
        self.reason_phrase = "OK"
        self.text = json.dumps(data or {}, ensure_ascii=False)

    def json(self) -> Any:
        return self._data

    def iter_lines(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeClient:
    def __init__(self) -> None:
        self.timeout = None
        self.calls: list[tuple[str, str, Any]] = []
        self.agents = {"agents": []}
        self.backups: list[dict[str, Any]] = []
        self.detail: dict[str, Any] | None = None
        self.stream_lines: list[str] = []
        self.post_responses: dict[str, FakeResponse] = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, path: str):
        self.calls.append(("GET", path, None))
        if path == "/agents":
            return FakeResponse(self.agents)
        if path == "/backups":
            return FakeResponse(self.backups)
        if path.endswith("/export"):
            return FakeResponse(content=b"zip-content")
        if self.detail is not None:
            return FakeResponse(self.detail)
        return FakeResponse({"detail": "Backup not found"}, status_code=404)

    def post(self, path: str, **kwargs):
        payload = kwargs.get("json") or kwargs.get("data") or kwargs
        self.calls.append(("POST", path, payload))
        return self.post_responses.get(path, FakeResponse({"ok": True}))

    def stream(self, method: str, path: str, **kwargs):
        self.calls.append((method, path, kwargs.get("json")))
        return FakeResponse(lines=self.stream_lines)


def _patch_client(monkeypatch, fake: FakeClient) -> FakeClient:
    monkeypatch.setattr("qwenpaw.cli.backup_cmd.client", lambda _: fake)
    return fake


def _sse(data: dict[str, Any]) -> str:
    return "data: " + json.dumps(data)


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
    fake = _patch_client(monkeypatch, FakeClient())
    fake.agents = {
        "agents": [
            {"id": "agent_b"},
            {"id": "agent_a"},
        ],
    }
    fake.stream_lines = [
        _sse({"type": "agent", "agent_id": "agent_a"}),
        _sse({"type": "done", "meta": {"id": "backup-1"}}),
    ]

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
    assert "backing up" not in result.output
    assert fake.calls[-1] == (
        "POST",
        "/backups/stream",
        {
            "name": "selected",
            "description": "",
            "scope": {
                "include_agents": True,
                "include_global_config": True,
                "include_secrets": False,
                "include_skill_pool": True,
            },
            "agents": ["agent_a", "agent_b"],
        },
    )


def test_backup_create_defaults_to_all_agents(monkeypatch) -> None:
    fake = _patch_client(monkeypatch, FakeClient())
    fake.agents = {
        "agents": [
            {"id": "agent_b"},
            {"id": "agent_a"},
        ],
    }
    fake.stream_lines = [_sse({"type": "done", "meta": {"id": "backup-1"}})]

    result = CliRunner().invoke(cli, ["backup", "create"])

    assert result.exit_code == 0
    assert fake.calls[-1][2]["agents"] == ["agent_b", "agent_a"]


def test_backup_create_full_marks_agent_scope_when_empty(monkeypatch) -> None:
    fake = _patch_client(monkeypatch, FakeClient())
    fake.agents = {"agents": []}
    fake.stream_lines = [_sse({"type": "done", "meta": {"id": "backup-1"}})]

    result = CliRunner().invoke(cli, ["backup", "create", "--full"])

    assert result.exit_code == 0
    scope = fake.calls[-1][2]["scope"]
    assert scope["include_agents"] is True
    assert scope["include_secrets"] is True


def test_backup_restore_posts_to_backend(monkeypatch) -> None:
    fake = _patch_client(monkeypatch, FakeClient())
    fake.detail = {
        "id": "backup-1",
        "scope": {
            "include_global_config": True,
            "include_skill_pool": True,
        },
        "workspace_stats": {"agent_a": {}, "agent_b": {}},
    }
    fake.post_responses["/backups/backup-1/restore"] = FakeResponse({"ok": True})

    result = CliRunner().invoke(
        cli,
        ["backup", "restore", "backup-1", "--agent", "agent_a", "--yes"],
    )

    assert result.exit_code == 0
    assert fake.calls[-1] == (
        "POST",
        "/backups/backup-1/restore",
        {
            "mode": "custom",
            "include_agents": True,
            "agent_ids": ["agent_a"],
            "include_global_config": True,
            "include_secrets": False,
            "include_skill_pool": True,
            "default_workspace_dir": None,
        },
    )
    assert '"ok": true' in result.output


def test_backup_delete_yes_skips_confirmation(monkeypatch) -> None:
    fake = _patch_client(monkeypatch, FakeClient())
    fake.post_responses["/backups/delete"] = FakeResponse(
        {"deleted": ["backup-1", "backup-2"], "failed": []},
    )

    result = CliRunner().invoke(
        cli,
        ["backup", "delete", "backup-1", "backup-2", "--yes"],
    )

    assert result.exit_code == 0
    assert "Continue with deletion?" not in result.output
    assert fake.calls[-1] == (
        "POST",
        "/backups/delete",
        {"ids": ["backup-1", "backup-2"]},
    )
    assert '"deleted": [' in result.output


def test_backup_prune_dry_run_keeps_newest(monkeypatch) -> None:
    fake = _patch_client(monkeypatch, FakeClient())
    now = datetime.now(timezone.utc)
    fake.backups = [
        {
            "name": "newest",
            "id": "backup-new",
            "created_at": now.isoformat(),
        },
        {
            "name": "old",
            "id": "backup-old",
            "created_at": (now - timedelta(days=4)).isoformat(),
        },
        {
            "name": "older",
            "id": "backup-older",
            "created_at": (now - timedelta(days=8)).isoformat(),
        },
    ]

    result = CliRunner().invoke(
        cli,
        ["backup", "prune", "--keep-last", "1", "--dry-run"],
    )

    assert result.exit_code == 0
    assert '"dry_run": true' in result.output
    assert '"id": "backup-new"' not in result.output
    assert '"id": "backup-old"' in result.output
    assert '"id": "backup-older"' in result.output


def test_backup_commands_require_reachable_backend(monkeypatch) -> None:
    def fail_client(_):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("qwenpaw.cli.backup_cmd.client", fail_client)

    result = CliRunner().invoke(cli, ["backup", "list"])

    assert result.exit_code != 0
    assert "QwenPaw backend is not reachable" in result.output
