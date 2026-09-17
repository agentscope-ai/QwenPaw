# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import checkpoints as router
from qwenpaw.checkpoints.models import CheckpointEntry, GcResult, RestoreResult
from qwenpaw.checkpoints.policy import session_key
from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole
from qwenpaw.access.agent_repository import AgentResourceRole


def test_checkpoint_entry_exposes_trusted_agent_identity() -> None:
    entry = CheckpointEntry(
        ref="refs/snap/example/one",
        kind="snap",
        session_key="example",
        name="one",
        commit="a" * 40,
        timestamp_ms=1,
        subject="snapshot",
        query=None,
        agent_id="public-agent",
    )

    assert router._entry_payload(entry)["agent_id"] == "public-agent"


def test_checkpoint_user_id_comes_from_authenticated_actor(monkeypatch) -> None:
    authenticated_user_id = uuid4()
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(role=AgentResourceRole.USER),
            actor=ActorContext(
                user_id=authenticated_user_id,
                actor_type=ActorType.USER,
                platform_role=PlatformRole.MEMBER,
                admin_mode=False,
                request_id="request",
            ),
        ),
    )
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    assert router._trusted_user_id(request, "attacker-controlled-user") == str(
        authenticated_user_id,
    )


@pytest.mark.asyncio
async def test_member_cannot_restore_another_users_checkpoint(monkeypatch) -> None:
    service = FakeService()
    authenticated_user_id = uuid4()
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(role=AgentResourceRole.USER),
            actor=ActorContext(
                user_id=authenticated_user_id,
                actor_type=ActorType.USER,
                platform_role=PlatformRole.MEMBER,
                admin_mode=False,
                request_id="request",
            ),
        ),
    )
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    with pytest.raises(HTTPException) as caught:
        await router._require_restore_access(
            service,
            request,
            commit="a" * 40,
            user_id="another-user",
            session_id="session",
            channel="console",
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_member_checkpoint_graph_only_includes_own_entries(monkeypatch) -> None:
    service = FakeService()
    authenticated_user_id = uuid4()
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(role=AgentResourceRole.USER),
            actor=ActorContext(
                user_id=authenticated_user_id,
                actor_type=ActorType.USER,
                platform_role=PlatformRole.MEMBER,
                admin_mode=False,
                request_id="request",
            ),
        ),
    )
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    assert await router._visible_entries(service, request, limit=20) == []


@pytest.mark.asyncio
async def test_owner_checkpoint_graph_does_not_expose_other_private_creator(
    monkeypatch,
) -> None:
    service = FakeService()
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(role=AgentResourceRole.OWNER),
            actor=ActorContext(
                user_id=uuid4(),
                actor_type=ActorType.USER,
                platform_role=PlatformRole.MEMBER,
                admin_mode=False,
                request_id="request",
            ),
        ),
    )
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    assert await router._visible_entries(service, request, limit=20) == []


def _entry() -> CheckpointEntry:
    key = session_key(channel="console", user_id="user", session_id="session")
    return CheckpointEntry(
        ref=f"refs/auto/{key}/1",
        kind="auto",
        session_key=key,
        name="1",
        commit="a" * 40,
        timestamp_ms=1,
        subject="auto",
        query="hello",
        channel="console",
        parent_commit="b" * 40,
        is_head=True,
        user_id="user",
        session_id="session",
    )


class FakeService:
    auto_enabled = True
    workspace_dir = Path("/workspace")
    gc_keep_count = 20
    gc_keep_days = 7
    pre_restore_retention_days = 7
    checkpoint_scope = "user_runtime"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        chat = SimpleNamespace(
            channel="console",
            user_id="user",
            session_id="session",
            name="Readable session title",
            archived=False,
        )
        empty_chat = SimpleNamespace(
            channel="console",
            user_id="user",
            session_id="empty-session",
            name="No checkpoints yet",
            archived=False,
        )

        class ChatManager:
            async def list_chats(self, *, archived=None):
                assert archived is None
                return [chat, empty_chat]

        self.workspace = SimpleNamespace(chat_manager=ChatManager())

    async def graph_entries(self, *, limit: int, user_id: str | None = None):
        self.calls.append(("graph", {"limit": limit, "user_id": user_id}))
        entries = [_entry()]
        if user_id is not None:
            entries = [entry for entry in entries if entry.user_id == user_id]
        return entries

    async def resolve_target_entry(
        self,
        target: str,
        session_id: str,
        user_id: str,
        channel: str,
    ):
        del session_id, user_id, channel
        entry = _entry()
        if target != entry.commit:
            raise CheckpointError("unknown")
        return entry

    async def auto_settings(self):
        self.calls.append(("auto_settings", {}))
        return self.auto_enabled, 1.5

    async def set_auto_enabled(self, enabled: bool):
        self.calls.append(("set_auto_enabled", {"enabled": enabled}))
        self.auto_enabled = enabled
        return self.auto_enabled, 1.5

    async def restore_with_files(self, **kwargs):
        self.calls.append(("restore_with_files", kwargs))
        return RestoreResult(
            target=kwargs["target"],
            commit=kwargs["target"],
            restored_paths=("sessions/session.json", "demo.py"),
            deleted_paths=(),
            file_paths=("demo.py",),
            pre_restore_ref=None,
            dry_run=kwargs["dry_run"],
            include_files=True,
            include_memory=kwargs["include_memory"],
        )

    async def gc(self, **kwargs):
        self.calls.append(("gc", kwargs))
        return GcResult(
            deleted_refs=(),
            kept_refs=(),
            dry_run=kwargs["dry_run"],
        )

    async def gc_settings(self):
        self.calls.append(("gc_settings", {}))
        return {
            "gc_keep_count": self.gc_keep_count,
            "gc_keep_days": self.gc_keep_days,
            "pre_restore_retention_days": self.pre_restore_retention_days,
        }

    async def set_gc_settings(self, **kwargs):
        self.calls.append(("set_gc_settings", kwargs))
        return kwargs


@pytest.fixture(name="checkpoint_service")
def _checkpoint_service(monkeypatch) -> FakeService:
    fake = FakeService()

    async def get_service(_request):
        return fake

    monkeypatch.setattr(router, "_service", get_service)
    return fake


@pytest.mark.asyncio
@pytest.mark.usefixtures("checkpoint_service")
async def test_graph_returns_topology_and_exact_session_identity():
    result = await router.checkpoint_graph(SimpleNamespace(), limit=50)

    assert result["nodes"][0]["parent_commit"] == "b" * 40
    assert result["nodes"][0]["session_id"] == "session"
    assert result["nodes"][0]["user_id"] == "user"
    assert result["nodes"][0]["session_title"] == "Readable session title"
    assert result["nodes"][0]["sha"] == "a" * 12
    assert result["sessions"] == [
        {
            "session_key": session_key(
                channel="console",
                user_id="user",
                session_id="session",
            ),
            "session_id": "session",
            "user_id": "user",
            "channel": "console",
            "title": "Readable session title",
            "archived": False,
        },
        {
            "session_key": session_key(
                channel="console",
                user_id="user",
                session_id="empty-session",
            ),
            "session_id": "empty-session",
            "user_id": "user",
            "channel": "console",
            "title": "No checkpoints yet",
            "archived": False,
        },
    ]
    assert result["summary"] == {
        "total": 1,
        "auto": 1,
        "snapshots": 0,
        "safety": 0,
        "heads": 1,
    }


@pytest.mark.asyncio
async def test_status_exposes_scope_not_server_workspace_path(
    checkpoint_service,
) -> None:
    result = await router.checkpoint_status(SimpleNamespace())

    assert result["scope"] == "user_runtime"
    assert result["restore_mode"] == "in_place"
    assert "workspace_dir" not in result


@pytest.mark.asyncio
async def test_multi_user_status_explicitly_exposes_new_chat_restore_mode(
    checkpoint_service,
    monkeypatch,
) -> None:
    user_id = uuid4()
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)

    result = await router.checkpoint_status(
        SimpleNamespace(
            state=SimpleNamespace(
                actor=ActorContext(
                    user_id=user_id,
                    actor_type=ActorType.USER,
                    platform_role=PlatformRole.MEMBER,
                    admin_mode=False,
                    request_id="status-mode",
                ),
            ),
        ),
    )

    assert result["restore_mode"] == "new_chat"


@pytest.mark.asyncio
async def test_gc_uses_retention_unless_compact_is_explicit(
    checkpoint_service,
):
    await router.preview_checkpoint_gc(
        router.GcRequest(),
        SimpleNamespace(),
    )
    assert checkpoint_service.calls[-1] == (
        "gc",
        {
            "session_id": "console",
            "user_id": "console",
            "channel": "console",
            "compact": False,
            "all_sessions": True,
            "dry_run": True,
            "keep_count": None,
            "keep_days": None,
                "pre_restore_days": None,
                "creator_user_id": None,
            },
    )

    await router.apply_checkpoint_gc(
        router.GcRequest(compact=True),
        SimpleNamespace(),
    )
    assert checkpoint_service.calls[-1][1]["compact"] is True
    assert checkpoint_service.calls[-1][1]["dry_run"] is False


@pytest.mark.asyncio
async def test_gc_settings_are_read_and_updated(checkpoint_service):
    current = await router.get_checkpoint_gc_settings(SimpleNamespace())
    assert current == {
        "gc_keep_count": 20,
        "gc_keep_days": 7,
        "pre_restore_retention_days": 7,
    }

    updated = await router.update_checkpoint_gc_settings(
        router.GcSettingsRequest(
            gc_keep_count=30,
            gc_keep_days=14,
            pre_restore_retention_days=3,
        ),
        SimpleNamespace(),
    )
    assert updated == {
        "gc_keep_count": 30,
        "gc_keep_days": 14,
        "pre_restore_retention_days": 3,
    }
    assert checkpoint_service.calls[-1] == (
        "set_gc_settings",
        updated,
    )


@pytest.mark.asyncio
async def test_restore_preview_and_apply_keep_the_pinned_commit(
    checkpoint_service,
):
    commit = "c" * 40
    body = router.RestoreRequest(
        commit=commit,
        session_id="session",
        user_id="user",
        channel="console",
        include_memory=True,
        include_files=True,
    )

    preview = await router.preview_checkpoint_restore(body, SimpleNamespace())
    assert preview["commit"] == commit
    assert checkpoint_service.calls[-1][1]["selected_files"] is None
    assert checkpoint_service.calls[-1][1]["dry_run"] is True

    body.files = ["demo.py"]
    applied = await router.apply_checkpoint_restore(body, SimpleNamespace())
    assert applied["commit"] == commit
    assert checkpoint_service.calls[-1][1]["selected_files"] == ("demo.py",)
    assert checkpoint_service.calls[-1][1]["dry_run"] is False


@pytest.mark.asyncio
async def test_file_restore_requires_an_explicit_selection(
    checkpoint_service,
):
    body = router.RestoreRequest(
        commit="d" * 40,
        session_id="session",
        include_files=True,
    )

    with pytest.raises(HTTPException) as caught:
        await router.apply_checkpoint_restore(body, SimpleNamespace())

    assert caught.value.status_code == 400
    assert all(
        call[0] != "restore_with_files" for call in checkpoint_service.calls
    )
