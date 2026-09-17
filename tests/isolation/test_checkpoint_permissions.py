# -*- coding: utf-8 -*-
"""检查点身份边界的真实 Git 隔离测试。"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentscope.state import AgentState
from fastapi import HTTPException

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.app.routers import checkpoints as router
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.checkpoints.runtime import CheckpointRuntime
from qwenpaw.checkpoints.models import CheckpointError
from qwenpaw.identity.models import PlatformRole
from qwenpaw.checkpoints.policy import session_file_path


def _request(user_id, role: AgentResourceRole = AgentResourceRole.USER):
    return SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=role,
                historical_read_only=False,
            ),
            actor=ActorContext(
                user_id=user_id,
                actor_type=ActorType.USER,
                platform_role=PlatformRole.MEMBER,
                admin_mode=False,
                request_id="checkpoint-permissions",
            ),
        ),
    )


async def _service(
    root: Path,
    *,
    agent_id: str = "shared-agent",
    conversation_root: Path | None = None,
):
    runtime = CheckpointRuntime()
    service = await runtime.get_for_workspace_dir_async(root)
    service.agent_id = agent_id
    service.checkpoint_scope = "user_runtime"
    if conversation_root is not None:
        service.conversation_workspace_dir = conversation_root
    return service


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_repeated_snapshots_do_not_reuse_other_session_index(tmp_path):
    """持久索引不能使 A→B→A 的快照互相夹带会话。"""
    service = await _service(tmp_path)
    commits = []
    for name, user in [("a1", "alice"), ("b", "bob"), ("a2", "alice")]:
        path = session_file_path(
            tmp_path, session_id="source", user_id=user, channel="console"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"agent":{"state":{"context":[]}}}', encoding="utf-8")
        snapshot = await service.make_snapshot_result(
            kind="snap", session_id="source", user_id=user, channel="console", name=name
        )
        commits.append((snapshot.commit, user))
    for commit, user in commits:
        paths = service.repository.run_git(
            "ls-tree", "-r", "--name-only", commit
        ).splitlines()
        assert [p for p in paths if p.startswith("sessions/")] == [
            f"sessions/console/{user}_source.json"
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("copy", [False, True])
async def test_file_restore_safety_snapshot_captures_current_trusted_session(
    tmp_path, copy
):
    """清理索引后，Legacy 和新会话文件恢复的安全快照仍含恢复前的源会话。"""
    service = await _service(tmp_path)
    source = session_file_path(
        tmp_path, session_id="source", user_id="alice", channel="console"
    )
    source.parent.mkdir(parents=True)
    source.write_text('{"agent":{"state":{"context":[]}}}', encoding="utf-8")
    selected = tmp_path / "selected.txt"
    selected.write_text("checkpoint", encoding="utf-8")
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source",
        user_id="alice",
        channel="console",
        name="before",
    )
    current = b'{"agent":{"state":{"context":[],"summary":"current state"}}}'
    source.write_bytes(current)
    selected.write_text("current", encoding="utf-8")
    if copy:
        result = await service.restore_selected_files_copy(
            target=snapshot.commit,
            source_session_id="source",
            source_user_id="alice",
            source_channel="console",
            selected_files=("selected.txt",),
        )
    else:
        result = await service.restore_with_files(
            target=snapshot.commit,
            session_id="source",
            user_id="alice",
            channel="console",
            selected_files=("selected.txt",),
        )
    assert (
        service.repository.read_blob(
            result.pre_restore_ref, "sessions/console/alice_source.json"
        )
        == current
    )


@pytest.mark.asyncio
async def test_legacy_http_snapshot_preview_and_restore_keep_nonempty_user(
    tmp_path, monkeypatch
):
    """前端保留的 Legacy 身份必须能贯穿真实 snapshot、preview 和原位恢复。"""
    service = await _service(tmp_path)
    source = session_file_path(
        tmp_path, session_id="legacy-session", user_id="legacy-user", channel="console"
    )
    source.parent.mkdir(parents=True)
    original = '{"agent":{"state":{"context":[],"summary":"checkpoint"}}}'
    source.write_text(original, encoding="utf-8")
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: False)

    async def get_service(_request):
        return service

    monkeypatch.setattr(router, "_service", get_service)
    request = SimpleNamespace(state=SimpleNamespace())
    snapshot = await router.create_checkpoint(
        router.SnapshotRequest(
            session_id="legacy-session",
            user_id="legacy-user",
            channel="console",
            name="legacy",
        ),
        request,
    )
    source.write_text('{"agent":{"state":{"context":[]}}}', encoding="utf-8")
    body = router.RestoreRequest(
        commit=snapshot["commit"],
        session_id="legacy-session",
        user_id="legacy-user",
        channel="console",
    )
    preview = await router._restore(body, request, dry_run=True)
    assert preview["commit"] == snapshot["commit"]
    result = await router._restore(body, request, dry_run=False)
    assert result["new_chat_id"] is None
    assert source.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"agent": {}},
        {"agent": {"state": {}}},
        {"agent": []},
        {"agent": {"state": []}},
        {"agent": {"state": {"context": None}}},
        {"agent": {"state": {"context": ["invalid"]}}},
        {"agent": {"state": {"context": [], "tool_context": []}}},
    ],
)
async def test_structurally_invalid_session_is_rejected(tmp_path, payload):
    """恢复必须保证页面和 AgentState 能消费完整状态，不能假成功。"""
    source = session_file_path(
        tmp_path, session_id="source", user_id="alice", channel="console"
    )
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(payload), encoding="utf-8")
    service = await _service(tmp_path)
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source",
        user_id="alice",
        channel="console",
        name="invalid",
    )
    with pytest.raises(CheckpointError, match="missing or invalid"):
        await service.restore_session_copy(
            target=snapshot.commit,
            source_session_id="source",
            source_user_id="alice",
            source_channel="console",
            new_session_id="new",
            new_user_id="alice",
            new_channel="console",
        )
    assert not session_file_path(
        tmp_path, session_id="new", user_id="alice", channel="console"
    ).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_callback", [False, True])
async def test_new_chat_restore_keeps_writers_paused_through_callback_rollback(
    tmp_path, monkeypatch, cancel_callback
):
    """活动任务先排空；元数据等待和失败补偿期间不能放行写入或第二次恢复。"""
    user_uuid = uuid4()
    user = str(user_uuid)
    source = session_file_path(
        tmp_path, session_id="source", user_id=user, channel="console"
    )
    source.parent.mkdir(parents=True)
    source.write_text('{"agent":{"state":{"context":[]}}}', encoding="utf-8")
    selected = tmp_path / "selected.txt"
    selected.write_text("checkpoint", encoding="utf-8")
    service = await _service(tmp_path)
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    await manager.create_chat(
        ChatSpec(session_id="source", user_id=user, channel="console", name="source")
    )
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source",
        user_id=user,
        channel="console",
        name="checkpoint",
    )
    selected.write_text("current", encoding="utf-8")
    idle = asyncio.Event()
    paused = asyncio.Event()
    callback_entered = asyncio.Event()
    finish_callback = asyncio.Event()

    class Cron:
        def pause(self):
            paused.set()

        def resume(self):
            paused.clear()

    tracker = TaskTracker()

    async def active_writer(_payload):
        await idle.wait()
        selected.write_text("active-task-finished", encoding="utf-8")
        yield "done"

    await tracker.attach_or_start("active-writer", None, active_writer)
    service.workspace = SimpleNamespace(
        chat_manager=manager, cron_executor=Cron(), task_tracker=tracker
    )

    async def fail_metadata(_chat):
        callback_entered.set()
        await finish_callback.wait()
        raise RuntimeError("metadata failed")

    manager.set_on_chat_created(fail_metadata)
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    async def get_service(_request):
        return service

    monkeypatch.setattr(router, "_service", get_service)
    restore_task = asyncio.create_task(
        router._restore(
            router.RestoreRequest(
                commit=snapshot.commit,
                session_id="source",
                channel="console",
                include_files=True,
                files=["selected.txt"],
            ),
            _request(user_uuid),
            dry_run=False,
        )
    )
    writer = second = None
    try:
        await asyncio.wait_for(paused.wait(), 5)
        assert paused.is_set(), "cron must pause before restore"
        assert not callback_entered.is_set(), "active task must finish before restore"
        assert selected.read_text(encoding="utf-8") == "current"
        idle.set()
        await asyncio.wait_for(callback_entered.wait(), 5)
        assert selected.read_text(encoding="utf-8") == "checkpoint"
        assert not service.query_gate.is_set()

        async def queued_writer():
            await service.query_gate.wait()
            selected.write_text("concurrent-write", encoding="utf-8")

        writer = asyncio.create_task(queued_writer())
        second = asyncio.create_task(
            service.restore_selected_files_copy(
                target=snapshot.commit,
                source_session_id="source",
                source_user_id=user,
                source_channel="console",
                selected_files=(),
                include_files=False,
            )
        )
        await asyncio.sleep(0.1)
        assert not writer.done()
        assert not second.done()
        assert paused.is_set()
        if cancel_callback:
            restore_task.cancel()
        else:
            finish_callback.set()
        with pytest.raises(asyncio.CancelledError if cancel_callback else RuntimeError):
            await restore_task
        await asyncio.gather(writer, second)
        assert selected.read_text(encoding="utf-8") == "concurrent-write"
        assert service.query_gate.is_set()
        assert not paused.is_set()
        assert len(await manager.list_chats()) == 1
    finally:
        idle.set()
        finish_callback.set()
        await asyncio.gather(
            restore_task,
            *[t for t in (writer, second) if t is not None],
            return_exceptions=True,
        )


@pytest.mark.asyncio
async def test_cancelled_file_copy_rolls_back_before_releasing_writers(
    tmp_path, monkeypatch
):
    """取消发生在同步文件恢复期间，也必须拿到安全快照并补偿后才释放 gate。"""
    source = session_file_path(
        tmp_path, session_id="source", user_id="alice", channel="console"
    )
    source.parent.mkdir(parents=True)
    source.write_text('{"agent":{"state":{"context":[]}}}', encoding="utf-8")
    selected = tmp_path / "selected.txt"
    selected.write_text("checkpoint", encoding="utf-8")
    service = await _service(tmp_path)
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source",
        user_id="alice",
        channel="console",
        name="checkpoint",
    )
    selected.write_text("current", encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    restore_paths = service.repository.restore_tree_paths

    def delayed_restore(commit, paths):
        result = restore_paths(commit, paths)
        if commit == snapshot.commit:
            entered.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(service.repository, "restore_tree_paths", delayed_restore)
    task = asyncio.create_task(
        service.restore_selected_files_copy(
            target=snapshot.commit,
            source_session_id="source",
            source_user_id="alice",
            source_channel="console",
            selected_files=("selected.txt",),
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0.1)
        assert not service.query_gate.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert selected.read_text(encoding="utf-8") == "current"
        assert service.query_gate.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_same_root_snapshot_contains_only_the_requested_session(
    tmp_path: Path,
) -> None:
    """Agent 工作区快照必须包含当前会话，且不能夹带其他用户会话。"""
    root = tmp_path / "agent"
    own_user_id = str(uuid4())
    other_user_id = str(uuid4())
    own = session_file_path(
        root,
        session_id="own-session",
        user_id=own_user_id,
        channel="console",
    )
    other = session_file_path(
        root,
        session_id="other-session",
        user_id=other_user_id,
        channel="console",
    )
    own.parent.mkdir(parents=True)
    own.write_text('{"agent":{"state":{"context":["own"]}}}', encoding="utf-8")
    other.write_text('{"agent":{"state":{"context":["other"]}}}', encoding="utf-8")
    service = await _service(root, conversation_root=root)

    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="own-session",
        user_id=own_user_id,
        channel="console",
        name="own-only",
    )

    own_rel = f"sessions/console/{own_user_id}_own-session.json"
    other_rel = f"sessions/console/{other_user_id}_other-session.json"
    assert service.repository.read_blob(snapshot.commit, own_rel)
    with pytest.raises(CheckpointError):
        service.repository.read_blob(snapshot.commit, other_rel)


@pytest.mark.asyncio
async def test_graph_filters_creator_before_applying_limit(tmp_path: Path) -> None:
    """大量其他用户检查点不能挤掉当前用户的图谱结果。"""
    root = tmp_path / "graph-agent"
    service = await _service(root, conversation_root=root)
    own_user_id = str(uuid4())
    other_user_id = str(uuid4())
    for user_id, session_id in (
        (own_user_id, "own"),
        (other_user_id, "other-1"),
        (other_user_id, "other-2"),
    ):
        path = session_file_path(
            root,
            session_id=session_id,
            user_id=user_id,
            channel="console",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"agent":{"state":{"context":[]}}}', encoding="utf-8")
        await service.make_snapshot_result(
            kind="snap",
            session_id=session_id,
            user_id=user_id,
            channel="console",
            name=session_id,
        )

    entries = await service.graph_entries(limit=1, user_id=own_user_id)

    assert len(entries) == 1
    assert entries[0].user_id == own_user_id


@pytest.mark.asyncio
async def test_shared_gc_only_collects_authenticated_creator_refs(
    tmp_path: Path,
) -> None:
    """共享仓库 GC 即使 all_sessions 也不能收集其他创建者 refs。"""
    root = tmp_path / "gc-agent"
    service = await _service(root, conversation_root=root)
    own_user_id = str(uuid4())
    other_user_id = str(uuid4())
    for user_id, session_id in (
        (own_user_id, "own"),
        (other_user_id, "other"),
    ):
        path = session_file_path(
            root,
            session_id=session_id,
            user_id=user_id,
            channel="console",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        for index in range(2):
            path.write_text(
                f'{{"agent":{{"state":{{"context":[{index}]}}}}}}',
                encoding="utf-8",
            )
            await service.make_auto_checkpoint(
                session_id=session_id,
                user_id=user_id,
                channel="console",
                query=str(index),
            )

    other_refs_before = {
        entry.ref
        for entry in await service.graph_entries(user_id=other_user_id)
    }
    result = await service.gc(
        session_id="ignored",
        user_id=own_user_id,
        channel="console",
        compact=True,
        all_sessions=True,
        creator_user_id=own_user_id,
    )
    other_refs_after = {
        entry.ref
        for entry in await service.graph_entries(user_id=other_user_id)
    }

    assert result.deleted_refs
    assert other_refs_after == other_refs_before


@pytest.mark.asyncio
async def test_restore_rejects_commit_from_a_different_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """防止移除会话匹配校验后，commit 被用于覆盖另一会话。"""
    user_id = uuid4()
    service = await _service(tmp_path / "runtime")
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source-session",
        user_id=str(user_id),
        channel="console",
        name="source",
    )
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(router, "_service", lambda _request: _async_value(service))

    with pytest.raises(HTTPException) as caught:
        await router._require_restore_access(
            service,
            _request(user_id),
            commit=snapshot.commit,
            user_id=str(user_id),
            session_id="target-session",
            channel="console",
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_unowned_legacy_checkpoint_is_not_private_user_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """防止旧无 user_id 元数据的记录自动变成当前成员的私人记录。"""
    user_id = uuid4()
    service = await _service(tmp_path / "runtime")
    legacy = await service.make_snapshot_result(
        kind="snap",
        session_id="legacy-session",
        user_id="",
        channel="console",
        name="legacy",
    )
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    with pytest.raises(HTTPException) as caught:
        await router._require_restore_access(
            service,
            _request(user_id),
            commit=legacy.commit,
            user_id=str(user_id),
            session_id="legacy-session",
            channel="console",
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_authenticated_user_can_restore_own_checkpoint_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """防止可信身份校验只验证元数据、却没有执行真实文件恢复。"""
    user_id = uuid4()
    root = tmp_path / "runtime"
    root.mkdir()
    session_file = session_file_path(
        root,
        session_id="own-session",
        user_id=str(user_id),
        channel="console",
    )
    session_file.parent.mkdir(parents=True)
    session_file.write_text('{"value":"before"}', encoding="utf-8")
    service = await _service(root)
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="own-session",
        user_id=str(user_id),
        channel="console",
        name="own",
    )
    session_file.write_text('{"value":"after"}', encoding="utf-8")
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    await router._require_restore_access(
        service,
        _request(user_id),
        commit=snapshot.commit,
        user_id=str(user_id),
        session_id="own-session",
        channel="console",
    )
    result = await service.restore(
        target=snapshot.commit,
        session_id="own-session",
        user_id=str(user_id),
        channel="console",
    )

    assert result.commit == snapshot.commit
    assert session_file.read_text(encoding="utf-8") == '{"value":"before"}'


@pytest.mark.asyncio
async def test_owner_cannot_restore_collaborator_private_conversation_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """防止把 Agent 草稿管理权扩大为其他用户私人会话读取权。"""
    owner_id = uuid4()
    collaborator_id = uuid4()
    service = await _service(tmp_path / "agent-workspace")
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="draft-session",
        user_id=str(collaborator_id),
        channel="console",
        name="collaborator-draft",
    )
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(router, "_service", lambda _request: _async_value(service))

    with pytest.raises(HTTPException) as caught:
        await router._require_restore_access(
            service,
            _request(owner_id, AgentResourceRole.OWNER),
            commit=snapshot.commit,
            user_id=str(owner_id),
            session_id="draft-session",
            channel="console",
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_personal_checkpoint_restores_new_session_without_changing_source(
    tmp_path: Path,
) -> None:
    """防止个人仓库漏存 Agent session，或恢复时覆盖原会话。"""
    user_id = str(uuid4())
    agent_root = tmp_path / "agent"
    personal_root = tmp_path / "personal"
    source = session_file_path(
        agent_root,
        session_id="source-session",
        user_id=user_id,
        channel="console",
    )
    source.parent.mkdir(parents=True)
    checkpoint_state = {
        "agent": {
            "state": {
                "context": [
                    {
                        "name": "user",
                        "role": "user",
                        "content": [{"type": "text", "text": "checkpoint query"}],
                    },
                    {
                        "name": "assistant",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_result",
                                "id": "checkpoint-tool-result",
                                "name": "execute_shell_command",
                                "output": "rich-output",
                            },
                        ],
                    },
                ],
            },
        },
    }
    import json

    source.write_text(json.dumps(checkpoint_state), encoding="utf-8")
    service = await _service(
        personal_root,
        conversation_root=agent_root,
    )
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source-session",
        user_id=user_id,
        channel="console",
        name="before-new-turn",
    )
    entries = await service.graph_entries()
    assert entries[0].query == "checkpoint query"
    source.write_text('{"agent":{"state":{"context":[]}}}', encoding="utf-8")

    result = await service.restore_session_copy(
        target=snapshot.commit,
        source_session_id="source-session",
        source_user_id=user_id,
        source_channel="console",
        new_session_id="restored-session",
        new_user_id=user_id,
        new_channel="console",
    )

    restored = session_file_path(
        agent_root,
        session_id="restored-session",
        user_id=user_id,
        channel="console",
    )
    assert json.loads(source.read_text(encoding="utf-8"))["agent"]["state"][
        "context"
    ] == []
    assert json.loads(restored.read_text(encoding="utf-8")) == checkpoint_state
    restored_state = AgentState.model_validate(json.loads(restored.read_text(encoding="utf-8"))["agent"]["state"])
    assert restored_state.context[1].content[0].output == "rich-output"
    assert result.restored_paths == (
        f"sessions/console/{user_id}_restored-session.json",
    )


@pytest.mark.asyncio
async def test_corrupt_checkpoint_session_is_rejected_without_new_file(
    tmp_path: Path,
) -> None:
    """防止损坏的旧 session blob 被当成成功恢复。"""
    user_id = str(uuid4())
    agent_root = tmp_path / "agent"
    source = session_file_path(
        agent_root,
        session_id="source",
        user_id=user_id,
        channel="console",
    )
    source.parent.mkdir(parents=True)
    source.write_text("not-json", encoding="utf-8")
    service = await _service(tmp_path / "personal", conversation_root=agent_root)
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source",
        user_id=user_id,
        channel="console",
        name="corrupt",
    )

    with pytest.raises(CheckpointError, match="missing or invalid"):
        await service.restore_session_copy(
            target=snapshot.commit,
            source_session_id="source",
            source_user_id=user_id,
            source_channel="console",
            new_session_id="new",
            new_user_id=user_id,
            new_channel="console",
        )

    assert not session_file_path(
        agent_root,
        session_id="new",
        user_id=user_id,
        channel="console",
    ).exists()


@pytest.mark.asyncio
async def test_missing_checkpoint_session_is_rejected_without_new_file(
    tmp_path: Path,
) -> None:
    """旧检查点缺少 session blob 时必须明确失败，不能生成空会话。"""
    user_id = str(uuid4())
    root = tmp_path / "legacy-agent"
    service = await _service(root, conversation_root=root)
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="missing-source",
        user_id=user_id,
        channel="console",
        name="missing",
    )

    with pytest.raises(CheckpointError, match="missing or invalid"):
        await service.restore_session_copy(
            target=snapshot.commit,
            source_session_id="missing-source",
            source_user_id=user_id,
            source_channel="console",
            new_session_id="new",
            new_user_id=user_id,
            new_channel="console",
        )

    assert not session_file_path(
        root,
        session_id="new",
        user_id=user_id,
        channel="console",
    ).exists()


@pytest.mark.asyncio
async def test_corrupt_restore_is_mapped_to_http_400(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多用户恢复的数据错误必须返回可解释 4xx，而不是泄漏为 500。"""
    user_uuid = uuid4()
    user_id = str(user_uuid)
    root = tmp_path / "http-agent"
    source = session_file_path(
        root,
        session_id="source",
        user_id=user_id,
        channel="console",
    )
    source.parent.mkdir(parents=True)
    source.write_text("not-json", encoding="utf-8")
    service = await _service(root, conversation_root=root)
    manager = ChatManager(repo=JsonChatRepository(root / "chats.json"))
    await manager.create_chat(
        ChatSpec(
            session_id="source",
            user_id=user_id,
            channel="console",
            name="source",
        ),
    )
    service.workspace = SimpleNamespace(chat_manager=manager)
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source",
        user_id=user_id,
        channel="console",
        name="corrupt-http",
    )
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    async def get_service(_request):
        return service

    monkeypatch.setattr(router, "_service", get_service)

    with pytest.raises(HTTPException) as caught:
        await router._restore(
            router.RestoreRequest(
                commit=snapshot.commit,
                session_id="source",
                channel="console",
            ),
            _request(user_uuid),
            dry_run=False,
        )

    assert caught.value.status_code == 400
    assert "missing or invalid" in str(caught.value.detail)


@pytest.mark.asyncio
async def test_collaborator_cannot_reset_shared_checkpoint_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """协作者不能用共享仓库 reset 删除其他创建者检查点。"""
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    async def unexpected_service(_request):
        raise AssertionError("reset must be rejected before opening the repository")

    monkeypatch.setattr(router, "_service", unexpected_service)

    with pytest.raises(HTTPException) as caught:
        await router.reset_checkpoints(
            _request(uuid4(), AgentResourceRole.COLLABORATOR),
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_restore_preview_does_not_create_session_or_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """防止预览通过生成新 UUID、目录或 ChatSpec 产生业务写入。"""
    user_uuid = uuid4()
    user_id = str(user_uuid)
    agent_root = tmp_path / "agent"
    source_path = session_file_path(
        agent_root,
        session_id="source-session",
        user_id=user_id,
        channel="console",
    )
    source_path.parent.mkdir(parents=True)
    source_path.write_text('{"agent":{"state":{"context":[]}}}', encoding="utf-8")
    personal_root = tmp_path / "personal"
    personal_root.mkdir()
    selected = personal_root / "selected.txt"
    selected.write_text("checkpoint", encoding="utf-8")
    service = await _service(
        personal_root,
        conversation_root=agent_root,
    )
    manager = ChatManager(repo=JsonChatRepository(agent_root / "chats.json"))
    source_chat = ChatSpec(
        session_id="source-session",
        user_id=user_id,
        channel="console",
        name="source",
    )
    await manager.create_chat(source_chat)
    service.workspace = SimpleNamespace(chat_manager=manager)
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source-session",
        user_id=user_id,
        channel="console",
        name="source",
    )
    selected.write_text("current", encoding="utf-8")
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    async def get_service(_request):
        return service

    monkeypatch.setattr(router, "_service", get_service)

    result = await router._restore(
        router.RestoreRequest(
            commit=snapshot.commit,
            session_id="source-session",
            channel="console",
            include_files=True,
            files=["selected.txt"],
        ),
        _request(user_uuid),
        dry_run=True,
    )

    assert result["new_session_id"] is None
    assert result["new_chat_id"] is None
    assert [chat.id for chat in await manager.list_chats()] == [source_chat.id]
    assert list((agent_root / "sessions" / "console").glob("*.json")) == [
        source_path,
    ]
    assert selected.read_text(encoding="utf-8") == "current"


@pytest.mark.asyncio
async def test_restore_callback_failure_removes_new_session_and_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """防止 PG 元数据 callback 失败后暴露可继续的新会话半成品。"""
    user_uuid = uuid4()
    user_id = str(user_uuid)
    agent_root = tmp_path / "agent"
    source_path = session_file_path(
        agent_root,
        session_id="source-session",
        user_id=user_id,
        channel="console",
    )
    source_path.parent.mkdir(parents=True)
    source_path.write_text('{"agent":{"state":{"context":[]}}}', encoding="utf-8")
    personal_root = tmp_path / "failed-personal"
    personal_root.mkdir()
    selected = personal_root / "selected.txt"
    selected.write_text("checkpoint", encoding="utf-8")
    manager = ChatManager(repo=JsonChatRepository(agent_root / "chats.json"))
    source_chat = ChatSpec(
        session_id="source-session",
        user_id=user_id,
        channel="console",
        name="source",
    )
    await manager.create_chat(source_chat)

    async def fail_metadata(_chat) -> None:
        raise RuntimeError("metadata failed")

    manager.set_on_chat_created(fail_metadata)
    service = await _service(
        personal_root,
        conversation_root=agent_root,
    )
    service.workspace = SimpleNamespace(chat_manager=manager)
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source-session",
        user_id=user_id,
        channel="console",
        name="source",
    )
    selected.write_text("current", encoding="utf-8")
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    async def get_service(_request):
        return service

    monkeypatch.setattr(router, "_service", get_service)

    with pytest.raises(RuntimeError, match="metadata failed"):
        await router._restore(
            router.RestoreRequest(
                commit=snapshot.commit,
                session_id="source-session",
                channel="console",
                include_files=True,
                files=["selected.txt"],
            ),
            _request(user_uuid),
            dry_run=False,
        )

    assert [chat.id for chat in await manager.list_chats()] == [source_chat.id]
    assert list((agent_root / "sessions" / "console").glob("*.json")) == [
        source_path,
    ]
    assert selected.read_text(encoding="utf-8") == "current"


@pytest.mark.asyncio
async def test_new_session_restore_keeps_source_and_restores_only_selected_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """防止新会话恢复覆盖源 session，或恢复未勾选的个人文件。"""
    user_uuid = uuid4()
    user_id = str(user_uuid)
    agent_root = tmp_path / "agent"
    personal_root = tmp_path / "personal"
    source_path = session_file_path(
        agent_root,
        session_id="source-session",
        user_id=user_id,
        channel="console",
    )
    source_path.parent.mkdir(parents=True)
    source_path.write_text('{"agent":{"state":{"context":[],"summary":"before"}}}', encoding="utf-8")
    personal_root.mkdir()
    selected = personal_root / "selected.txt"
    untouched = personal_root / "untouched.txt"
    memory = personal_root / "MEMORY.md"
    selected.write_text("before", encoding="utf-8")
    untouched.write_text("before", encoding="utf-8")
    memory.write_text("before-memory", encoding="utf-8")
    manager = ChatManager(repo=JsonChatRepository(agent_root / "chats.json"))
    source_chat = ChatSpec(
        session_id="source-session",
        user_id=user_id,
        channel="console",
        name="source",
    )
    await manager.create_chat(source_chat)
    service = await _service(personal_root, conversation_root=agent_root)
    service.workspace = SimpleNamespace(chat_manager=manager)
    snapshot = await service.make_snapshot_result(
        kind="snap",
        session_id="source-session",
        user_id=user_id,
        channel="console",
        name="source",
    )
    source_path.write_text('{"agent":{"state":{"context":["after"]}}}', encoding="utf-8")
    selected.write_text("after", encoding="utf-8")
    untouched.write_text("after", encoding="utf-8")
    memory.write_text("after-memory", encoding="utf-8")
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    async def get_service(_request):
        return service

    monkeypatch.setattr(router, "_service", get_service)

    result = await router._restore(
        router.RestoreRequest(
            commit=snapshot.commit,
            session_id="source-session",
            channel="console",
            include_files=True,
            include_memory=True,
            files=["selected.txt"],
        ),
        _request(user_uuid),
        dry_run=False,
    )

    assert result["new_chat_id"]
    assert source_path.read_text(encoding="utf-8") == (
        '{"agent":{"state":{"context":["after"]}}}'
    )
    assert selected.read_text(encoding="utf-8") == "before"
    assert untouched.read_text(encoding="utf-8") == "after"
    assert memory.read_text(encoding="utf-8") == "before-memory"
    assert not session_file_path(
        personal_root,
        session_id="source-session",
        user_id=user_id,
        channel="console",
    ).exists()
