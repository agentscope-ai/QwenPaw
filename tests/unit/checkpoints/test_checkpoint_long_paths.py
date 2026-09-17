# -*- coding: utf-8 -*-
"""真实深目录检查点必须能更新 ref、查询和恢复。"""

import os
import hashlib
import json
import shutil
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.checkpoints.policy import session_file_path
from qwenpaw.checkpoints.service import CheckpointService
from qwenpaw.checkpoints import repository as repository_module
from qwenpaw.checkpoints.repository import CheckpointRepository


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_name", ["TASK63-deep-personal-checkpoint", "🌟" * 80])
async def test_deep_user_runtime_checkpoint_round_trip(
    tmp_path, checkpoint_test_git, monkeypatch, snapshot_name
):
    user_id = str(uuid4())
    session_id = str(uuid4())
    base = tmp_path / "user_workspaces" / user_id
    padding = "x" * max(0, 150 - len(str(base / "deep-personal-agent")))
    root = base / ("deep-personal-agent" + padding)
    root.mkdir(parents=True)
    agent_root = tmp_path / "agent"
    source = session_file_path(
        agent_root, session_id=session_id, user_id=user_id, channel="console"
    )
    source.parent.mkdir(parents=True)
    original = '{"agent":{"state":{"context":[],"summary":"before"}}}'
    source.write_text(original, encoding="utf-8")
    selected = root / "selected.txt"
    selected.write_text("before", encoding="utf-8")
    service = CheckpointService(root)
    service.conversation_workspace_dir = agent_root
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id=session_id,
        user_id=user_id,
        channel="console",
        name=snapshot_name,
    )
    assert len(str(service.repository.git_dir / snapshot.ref)) < 260
    entries = await service.graph_entries()
    assert [entry.commit for entry in entries] == [snapshot.commit]
    assert entries[0].name == snapshot_name
    assert (
        await service.resolve_target_entry(
            snapshot_name, session_id, user_id, "console"
        )
    ).commit == snapshot.commit
    source.write_text(
        '{"agent":{"state":{"context":[],"summary":"after"}}}', encoding="utf-8"
    )
    selected.write_text("after", encoding="utf-8")
    result = await service.restore_selected_files_copy(
        target=snapshot.commit,
        source_session_id=session_id,
        source_user_id=user_id,
        source_channel="console",
        selected_files=("selected.txt",),
    )
    await service.restore_session_copy(
        target=snapshot.commit,
        source_session_id=session_id,
        source_user_id=user_id,
        source_channel="console",
        new_session_id="new",
        new_user_id=user_id,
        new_channel="console",
    )
    restored = session_file_path(
        agent_root, session_id="new", user_id=user_id, channel="console"
    )
    assert '"summary":"before"' in restored.read_text(encoding="utf-8")
    assert selected.read_text(encoding="utf-8") == "before"
    assert '"summary":"after"' in source.read_text(encoding="utf-8")
    assert result.pre_restore_ref
    neighbor = root / "neighbor" / "keep.txt"
    neighbor.parent.mkdir()
    neighbor.write_text("preserve adjacent workspace data", encoding="utf-8")
    rmtree = shutil.rmtree
    removed = []

    def remove_checkpoint_state(path, *args, **kwargs):
        assert os.path.samefile(path, service.repository.state_dir)
        assert service.repository.git_dir.parent == service.repository.state_dir
        removed.append(path)
        return rmtree(path, *args, **kwargs)

    monkeypatch.setattr(
        repository_module, "shutil", SimpleNamespace(rmtree=remove_checkpoint_state)
    )
    await service.reset()
    assert len(removed) == 1
    assert await service.graph_entries() == []
    assert neighbor.read_text(encoding="utf-8") == "preserve adjacent workspace data"
    assert '"summary":"after"' in source.read_text(encoding="utf-8")


def test_reset_keeps_original_path_on_nonwindows_branch(tmp_path, monkeypatch):
    repo = CheckpointRepository(tmp_path)
    neighbor = tmp_path / "keep.txt"
    neighbor.write_text("keep", encoding="utf-8")
    rmtree = shutil.rmtree
    removed = []

    def remove_checkpoint_state(path, *args, **kwargs):
        assert path == repo.state_dir
        removed.append(path)
        return rmtree(path, *args, **kwargs)

    monkeypatch.setattr(
        repository_module, "os", SimpleNamespace(name="posix", chmod=os.chmod)
    )
    monkeypatch.setattr(
        repository_module, "shutil", SimpleNamespace(rmtree=remove_checkpoint_state)
    )
    repo.reset()
    assert removed == [repo.state_dir]
    assert neighbor.read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_legacy_refs_and_heads_remain_readable(tmp_path):
    from qwenpaw.checkpoints.policy import session_key

    service = CheckpointService(tmp_path)
    (tmp_path / "file.txt").write_text("before", encoding="utf-8")
    first = await service.make_snapshot_result(
        kind="snap", session_id="s", user_id="u", channel="c", name="old"
    )
    digest = hashlib.sha256(b'["c","u","s"]').hexdigest()
    legacy_key = f"c-u-s-{digest}"
    legacy_ref = f"refs/snap/{legacy_key}/old"
    service.repository.run_git("update-ref", legacy_ref, first.commit)
    service.repository.run_git("update-ref", "-d", first.ref)
    service.repository.heads_file.write_text(
        json.dumps({legacy_key: first.commit}), encoding="utf-8"
    )
    service = CheckpointService(tmp_path)
    timeline = await service.timeline(session_id="s", user_id="u", channel="c")
    assert len(timeline) == 1
    assert timeline[0].is_head
    second = await service.make_snapshot_result(
        kind="snap", session_id="s", user_id="u", channel="c", name="new"
    )
    assert second.parent_commit == first.commit
    assert (await service.resolve_target_entry("old", "s", "u", "c")).commit == first.commit
    assert len(await service.delete_sessions([("s", "u", "c")])) == 2
    assert await service.graph_entries() == []
    assert service.repository.get_session_head(
        session_key(channel="c", user_id="u", session_id="s")
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_named_snapshot_lookup_is_not_limited_by_timeline_page(
    tmp_path, monkeypatch, legacy
):
    service = CheckpointService(tmp_path)
    (tmp_path / "file.txt").write_text("before", encoding="utf-8")
    name = "old" if legacy else "🌟" * 80
    first = await service.make_snapshot_result(
        kind="snap", session_id="s", user_id="u", channel="c", name=name
    )
    old_ref = first.ref
    if legacy:
        digest = hashlib.sha256(b'["c","u","s"]').hexdigest()
        old_ref = f"refs/snap/c-u-s-{digest}/old"
        service.repository.run_git("update-ref", old_ref, first.commit)
        service.repository.run_git("update-ref", "-d", first.ref)
    second = await service.make_snapshot_result(
        kind="snap", session_id="s", user_id="u", channel="c",
        name="new" if legacy else name,
    )
    monkeypatch.setattr(type(service), "timeline_max_limit", property(lambda self: 1))
    assert len(await service.timeline(session_id="s", user_id="u", channel="c", limit=1)) == 1
    for target in (name, old_ref, first.commit):
        assert (await service.resolve_target_entry(target, "s", "u", "c")).commit == first.commit
    if not legacy:
        assert (await service.resolve_target_entry(name + "-2", "s", "u", "c")).commit == second.commit
