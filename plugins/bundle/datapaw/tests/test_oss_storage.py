# -*- coding: utf-8 -*-
"""Tests for DataPaw OSS sync."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace


class _FakeBackend:
    def __init__(
        self,
        *,
        prefix: str = "workspaces/datapaw",
        objects: dict[str, bytes] | None = None,
    ) -> None:
        self.prefix = prefix
        self.objects: dict[str, bytes] = dict(objects or {})
        self.uploaded: list[str] = []

    def list_keys(self, prefix: str) -> list[str]:
        normalized = prefix.rstrip("/") + "/"
        return sorted(
            key
            for key in self.objects
            if key.startswith(normalized) or key == prefix.rstrip("/")
        )

    def put(self, local_path: Path, key: str) -> None:
        self.objects[key] = Path(local_path).read_bytes()
        self.uploaded.append(key)

    def get(self, key: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(self.objects[key])


def _install_fake(monkeypatch, fake: _FakeBackend):
    import plugin_datapaw.core.oss_sync as oss_sync

    monkeypatch.setattr(oss_sync, "_get_oss_bucket", lambda: object())
    monkeypatch.setattr(oss_sync, "_oss_list", fake.list_keys)
    monkeypatch.setattr(
        oss_sync,
        "_oss_upload",
        lambda local, key: fake.put(local, key),
    )
    monkeypatch.setattr(
        oss_sync,
        "_oss_download",
        lambda key, local: fake.get(key, local),
    )
    return oss_sync


def test_upload_session_only_current_files(tmp_path, monkeypatch):
    fake = _FakeBackend()
    oss_sync = _install_fake(monkeypatch, fake)

    ws = tmp_path / "workspace"
    session_id = "1782458522493"
    user_id = "default"

    console = ws / "sessions" / "console" / f"{user_id}_{session_id}.json"
    console.parent.mkdir(parents=True)
    console.write_text('{"agent": {}}', encoding="utf-8")

    dag = ws / "sessions" / "dag" / f"{user_id}_{session_id}.json"
    dag.parent.mkdir(parents=True)
    dag.write_text('{"artifacts": []}', encoding="utf-8")

    artifact = ws / "artifacts" / session_id / "graph_a" / "result.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("a,b\n1,2\n", encoding="utf-8")

    oss_sync.upload_session(
        session_id=session_id,
        user_id=user_id,
        channel="console",
        workspace_dir=ws,
    )

    assert (
        fake.objects[
            "workspaces/datapaw/sessions/console/"
            f"{user_id}_{session_id}.json"
        ]
        == b'{"agent": {}}'
    )
    assert (
        "workspaces/datapaw/artifacts/"
        f"{session_id}/graph_a/result.csv"
        in fake.objects
    )


def test_upload_session_includes_chats_json(tmp_path, monkeypatch):
    fake = _FakeBackend()
    oss_sync = _install_fake(monkeypatch, fake)

    ws = tmp_path / "workspace"
    ws.mkdir()
    session_id = "1782458522493"
    chats = ws / "chats.json"
    chats.write_text(
        '{"version":1,"chats":[{"session_id":"1782458522493","name":"hi"}]}',
        encoding="utf-8",
    )
    console = ws / "sessions" / "console" / f"default_{session_id}.json"
    console.parent.mkdir(parents=True)
    console.write_text("{}", encoding="utf-8")

    oss_sync.upload_session(
        session_id=session_id,
        workspace_dir=ws,
    )

    assert fake.objects["workspaces/datapaw/chats.json"] == chats.read_bytes()


def test_reload_downloads_chats_when_local_empty(tmp_path, monkeypatch):
    fake = _FakeBackend(
        objects={
            "workspaces/datapaw/chats.json": (
                b'{"version":1,"chats":[{"session_id":"111","name":"restored"}]}'
            ),
        },
    )
    oss_sync = _install_fake(monkeypatch, fake)

    ws = tmp_path / "workspace"
    oss_sync.reload_from_oss(workspace_dir=ws)

    local_chats = ws / "chats.json"
    assert local_chats.is_file()
    assert b"restored" in local_chats.read_bytes()


def test_reload_skips_chats_when_local_has_entries(tmp_path, monkeypatch):
    fake = _FakeBackend(
        objects={
            "workspaces/datapaw/chats.json": (
                b'{"version":1,"chats":[{"session_id":"remote","name":"remote"}]}'
            ),
        },
    )
    oss_sync = _install_fake(monkeypatch, fake)

    ws = tmp_path / "workspace"
    ws.mkdir()
    local_chats = ws / "chats.json"
    local_chats.write_text(
        '{"version":1,"chats":[{"session_id":"local","name":"local"}]}',
        encoding="utf-8",
    )

    oss_sync.reload_from_oss(workspace_dir=ws)

    assert b"local" in local_chats.read_bytes()
    assert b"remote" not in local_chats.read_bytes()


def test_reload_removes_invalid_chats_after_bad_download(tmp_path, monkeypatch):
    fake = _FakeBackend(
        objects={
            "workspaces/datapaw/chats.json": b"",
        },
    )
    oss_sync = _install_fake(monkeypatch, fake)

    ws = tmp_path / "workspace"
    ws.mkdir()
    local_chats = ws / "chats.json"
    local_chats.write_text("", encoding="utf-8")

    oss_sync.reload_from_oss(workspace_dir=ws)

    assert not local_chats.exists()


def test_upload_skips_invalid_chats_json(tmp_path, monkeypatch):
    fake = _FakeBackend()
    oss_sync = _install_fake(monkeypatch, fake)

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "chats.json").write_text("", encoding="utf-8")
    console = ws / "sessions" / "console" / "default_111.json"
    console.parent.mkdir(parents=True)
    console.write_text("{}", encoding="utf-8")

    oss_sync.upload_session(
        session_id="111",
        workspace_dir=ws,
    )

    assert "workspaces/datapaw/chats.json" not in fake.objects
    assert "workspaces/datapaw/sessions/console/default_111.json" in fake.objects


def test_upload_session_does_not_touch_other_sessions(tmp_path, monkeypatch):
    fake = _FakeBackend()
    oss_sync = _install_fake(monkeypatch, fake)

    ws = tmp_path / "workspace"
    for sid in ("111", "222"):
        path = ws / "sessions" / "console" / f"default_{sid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"session": "{sid}"}}', encoding="utf-8")

    oss_sync.upload_session(
        session_id="111",
        user_id="default",
        channel="console",
        workspace_dir=ws,
    )

    uploaded_sessions = {
        key for key in fake.uploaded if "/sessions/console/" in key
    }
    assert uploaded_sessions == {
        "workspaces/datapaw/sessions/console/default_111.json",
    }


def test_reload_local_first_skips_existing(tmp_path, monkeypatch):
    fake = _FakeBackend(
        objects={
            "workspaces/datapaw/sessions/console/"
            "default_1782458522493.json": b'{"remote": true}',
            "workspaces/datapaw/sessions/dag/"
            "default_1782458522493.json": b'{"artifacts": []}',
            "workspaces/datapaw/artifacts/"
            "1782458522493/graph_a/report.html": b"<html></html>",
        },
    )
    oss_sync = _install_fake(monkeypatch, fake)

    ws = tmp_path / "workspace"
    session_id = "1782458522493"
    user_id = "default"
    local_console = ws / "sessions" / "console" / f"{user_id}_{session_id}.json"
    local_console.parent.mkdir(parents=True)
    local_console.write_text('{"local": true}', encoding="utf-8")

    oss_sync.reload_from_oss(workspace_dir=ws)

    assert local_console.read_text(encoding="utf-8") == '{"local": true}'
    assert (
        ws / "sessions" / "dag" / f"{user_id}_{session_id}.json"
    ).is_file()
    assert (ws / "artifacts" / session_id / "graph_a" / "report.html").is_file()


def test_reload_skips_artifacts_when_local_dir_exists(tmp_path, monkeypatch):
    fake = _FakeBackend(
        objects={
            "workspaces/datapaw/sessions/console/"
            "default_1782458522493.json": b"{}",
            "workspaces/datapaw/artifacts/"
            "1782458522493/remote.txt": b"remote",
        },
    )
    oss_sync = _install_fake(monkeypatch, fake)

    ws = tmp_path / "workspace"
    session_id = "1782458522493"
    artifacts_dir = ws / "artifacts" / session_id
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "keep.txt").write_text("local", encoding="utf-8")

    oss_sync.reload_from_oss(workspace_dir=ws)

    assert not (artifacts_dir / "remote.txt").exists()


def test_upload_session_to_oss_respects_flag(monkeypatch):
    import plugin_datapaw.core.oss_sync as oss_sync

    calls = []
    monkeypatch.setattr(
        oss_sync.EnvVarLoader,
        "get_bool",
        lambda name, default=False: False,
    )
    monkeypatch.setattr(
        oss_sync,
        "upload_session",
        lambda **kwargs: calls.append(kwargs),
    )

    oss_sync.upload_session_to_oss(
        runner=SimpleNamespace(),
        session_id="s1",
        user_id="default",
        channel="console",
    )
    assert calls == []


def test_datapaw_query_wrapper_schedules_oss_upload(monkeypatch):
    from plugin_datapaw.constants import BUILTIN_DATAPAW_AGENT_ID
    from plugin_datapaw.hooks import _wrap_query_handler
    from plugin_datapaw.core import trace_submitter

    oss_calls = []
    monkeypatch.setattr(
        trace_submitter,
        "schedule_trace_submit",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "plugin_datapaw.hooks._schedule_oss_upload_for_request",
        lambda runner, request: oss_calls.append(
            (getattr(runner, "agent_id", None), getattr(request, "session_id", "")),
        ),
    )

    async def orig_query_handler(self, msgs, request=None, **kwargs):
        yield "chunk", False

    async def run():
        wrapped = _wrap_query_handler(orig_query_handler)
        runner = SimpleNamespace(agent_id=BUILTIN_DATAPAW_AGENT_ID)
        request = SimpleNamespace(
            session_id="s1",
            user_id="default",
            channel="console",
        )
        chunks = []
        async for item in wrapped(runner, [], request):
            chunks.append(item)
        return chunks

    assert asyncio.run(run()) == [("chunk", False)]
    assert oss_calls == [(BUILTIN_DATAPAW_AGENT_ID, "s1")]
