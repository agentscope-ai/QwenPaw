# -*- coding: utf-8 -*-
"""会话删除必须清理其真实个人运行空间，包括重启后的存储。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.checkpoints.runtime import CheckpointRuntime
from qwenpaw.checkpoints.policy import session_key
from qwenpaw.workspaces import resolver
from qwenpaw.identity import runtime as identity_runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("restart", [False, True])
async def test_cleanup_finds_personal_store_without_touching_neighbor(
    tmp_path, monkeypatch, restart
):
    monkeypatch.setattr(identity_runtime, "is_multi_user_enabled", lambda: True)
    original_resolver = resolver.WorkspaceResolver
    monkeypatch.setattr(
        resolver, "WorkspaceResolver",
        lambda **kwargs: original_resolver(working_dir=tmp_path, **kwargs),
    )
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    workspace = SimpleNamespace(workspace_dir=agent_root, agent_id="a")
    runtime = CheckpointRuntime()
    users = [str(uuid4()), str(uuid4())]
    services = []
    for user in users:
        root = tmp_path / "user_workspaces" / user / "a"
        root.mkdir(parents=True)
        (root / "file.txt").write_text(user, encoding="utf-8")
        service = runtime.get_for_workspace_dir(root)
        service.workspace = workspace
        await service.make_snapshot_result(
            kind="snap", session_id="session", user_id=user,
            channel="console", name="snapshot",
        )
        services.append(service)
    if restart:
        await runtime.flush_and_close_all()
        runtime = CheckpointRuntime()
    else:
        key = session_key(channel="console", user_id=users[1], session_id="session")
        runtime.debouncer.schedule(
            f"{services[1].workspace_dir}:{key}",
            lambda: services[1].make_auto_checkpoint(
                session_id="session", user_id=users[1], channel="console"
            ), delay=3600,
        )
    try:
        deleted = await runtime.delete_session_checkpoints(
            workspace, [("session", users[1], "console")]
        )
        assert len(deleted) == 1
        own = runtime.get_for_workspace_dir(services[1].workspace_dir)
        other = runtime.get_for_workspace_dir(services[0].workspace_dir)
        assert await own.graph_entries() == []
        assert len(await other.graph_entries()) == 1
        assert runtime.debouncer._pending == {}
        key = session_key(channel="console", user_id=users[1], session_id="session")
        assert own.repository.get_session_head(key) is None
    finally:
        await runtime.flush_and_close_all()
