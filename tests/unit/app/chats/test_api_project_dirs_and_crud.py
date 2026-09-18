# -*- coding: utf-8 -*-
"""Route-level tests for the chats API.

Complements the two existing modules: ``test_api.py`` pins the PawApp
ownership boundary of the read routes and ``test_group_api.py`` drives
group CRUD through ``TestClient``. This one calls the route functions
directly, so every dependency-injection seam, every error status code and
the effective project-directory projection can be asserted on its own.
"""
# pylint: disable=protected-access

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState
from fastapi import HTTPException

from qwenpaw.app.chats import api as chats_api
from qwenpaw.app.chats.models import BatchArchiveResult, ChatSpec


def _spec(
    chat_id: str = "c1",
    *,
    meta: dict | None = None,
    session_id: str = "console:u",
    user_id: str = "u",
) -> ChatSpec:
    """Build a persisted chat spec with a console session identity."""
    return ChatSpec(
        id=chat_id,
        session_id=session_id,
        user_id=user_id,
        channel="console",
        meta=meta if meta is not None else {},
    )


def _mgr(**overrides) -> SimpleNamespace:
    """ChatManager stand-in exposing only what the routes await.

    ``SimpleNamespace`` (not ``MagicMock``) so touching an unstubbed
    method raises instead of silently returning another mock.
    """
    base: dict = {
        "get_chat": AsyncMock(return_value=_spec()),
        "list_chats": AsyncMock(return_value=[]),
        "delete_chats": AsyncMock(return_value=True),
        "patch_chat": AsyncMock(return_value=_spec()),
        "archive_chat": AsyncMock(return_value=_spec()),
        "unarchive_chat": AsyncMock(return_value=_spec()),
        "batch_archive": AsyncMock(return_value=BatchArchiveResult()),
        "batch_unarchive": AsyncMock(return_value=BatchArchiveResult()),
        "set_session_project_dirs": AsyncMock(return_value=_spec()),
        "create_group": AsyncMock(return_value=None),
        "reorder_groups": AsyncMock(return_value=[]),
        "update_group": AsyncMock(return_value=None),
        "delete_group": AsyncMock(return_value=True),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _workspace(workspace_dir: Path, **extra) -> SimpleNamespace:
    """Workspace stand-in carrying the agent identity the routes read."""
    return SimpleNamespace(
        agent_id="agent-x",
        workspace_dir=workspace_dir,
        **extra,
    )


@pytest.fixture(name="dirs")
def _dirs_fixture(tmp_path: Path) -> SimpleNamespace:
    """Three real directories: a workspace plus an outer/inner pair."""
    workspace = tmp_path / "ws"
    outer = tmp_path / "alpha"
    middle = outer / "beta"
    inner = middle / "gamma"
    for path in (workspace, outer, middle, inner):
        path.mkdir(parents=True)
    return SimpleNamespace(
        workspace=workspace.resolve(),
        outer=outer.resolve(),
        middle=middle.resolve(),
        inner=inner.resolve(),
        tmp=tmp_path.resolve(),
    )


def _meta_dirs(*entries: tuple[str, str | None]) -> dict:
    """Session-level ``runtime_context.project_dirs`` override metadata."""
    return {
        "runtime_context": {
            "project_dirs": [
                {"path": path, "label": label} for path, label in entries
            ],
        },
    }


# --------------------------------------------------------------------- #
# Dependency injection seams
# --------------------------------------------------------------------- #


async def test_get_workspace_delegates_to_agent_context() -> None:
    """``get_workspace`` is a thin await over the agent-context resolver."""
    request = SimpleNamespace()
    sentinel = object()
    resolver = AsyncMock(return_value=sentinel)
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=resolver,
    ):
        assert await chats_api.get_workspace(request) is sentinel
    resolver.assert_awaited_once_with(request)


async def test_get_chat_manager_returns_workspace_manager() -> None:
    manager = object()
    workspace = SimpleNamespace(chat_manager=manager)
    with patch.object(
        chats_api,
        "get_workspace",
        new=AsyncMock(return_value=workspace),
    ):
        assert await chats_api.get_chat_manager(SimpleNamespace()) is manager


async def test_get_session_returns_workspace_session() -> None:
    session = object()
    workspace = SimpleNamespace(session=session)
    with patch.object(
        chats_api,
        "get_workspace",
        new=AsyncMock(return_value=workspace),
    ):
        assert await chats_api.get_session(SimpleNamespace()) is session


# --------------------------------------------------------------------- #
# Effective project-directory projection
# --------------------------------------------------------------------- #


async def test_dirs_response_reports_labels_and_nesting(dirs) -> None:
    chat = _spec(
        meta=_meta_dirs((str(dirs.outer), "L1"), (str(dirs.middle), None)),
    )
    payload = await chats_api._project_dirs_response(
        chat,
        _workspace(dirs.workspace),
    )
    assert payload["source"] == "session"
    assert payload["agent_project_dir"] is None
    assert [
        (entry["path"], entry["label"], entry["exists"], entry["nested_with"])
        for entry in payload["project_dirs"]
    ] == [
        (str(dirs.outer), "L1", True, None),
        (str(dirs.middle), None, True, str(dirs.outer)),
    ]


async def test_dirs_response_prefers_nearest_ancestor(dirs) -> None:
    """``nested_with`` is the *longest* covering path, not the first."""
    chat = _spec(
        meta=_meta_dirs(
            (str(dirs.outer), None),
            (str(dirs.middle), None),
            (str(dirs.inner), None),
        ),
    )
    payload = await chats_api._project_dirs_response(
        chat,
        _workspace(dirs.workspace),
    )
    nesting = [entry["nested_with"] for entry in payload["project_dirs"]]
    assert nesting == [None, str(dirs.outer), str(dirs.middle)]


async def test_dirs_response_order_independent_nearest_ancestor(
    dirs,
) -> None:
    """Nesting is reported from the submitted order, not from path depth.

    The outer root arrives *after* the middle one, so every entry still
    reports its own nearest covering ancestor by longest path, and the
    outer entry (index 1) is flagged as covered by the middle one even
    though it was submitted later.
    """
    chat = _spec(
        meta=_meta_dirs(
            (str(dirs.middle), None),
            (str(dirs.outer), None),
            (str(dirs.inner), None),
        ),
    )
    payload = await chats_api._project_dirs_response(
        chat,
        _workspace(dirs.workspace),
    )
    nesting = [entry["nested_with"] for entry in payload["project_dirs"]]
    assert nesting == [str(dirs.outer), None, str(dirs.middle)]


async def test_dirs_response_flags_the_workspace_entry(dirs) -> None:
    """``is_workspace`` is decided by filesystem identity, not path text."""
    chat = _spec(meta=_meta_dirs((str(dirs.workspace), None)))
    payload = await chats_api._project_dirs_response(
        chat,
        _workspace(dirs.workspace),
    )
    assert [entry["is_workspace"] for entry in payload["project_dirs"]] == [
        True,
    ]


async def test_dirs_response_falls_back_to_workspace_without_override(
    dirs,
) -> None:
    """No session override and no readable agent config -> workspace."""
    chat = _spec(meta={})
    with patch(
        "qwenpaw.config.config.load_agent_config",
        side_effect=RuntimeError("no agent"),
    ):
        payload = await chats_api._project_dirs_response(
            chat,
            _workspace(dirs.workspace),
        )
    assert payload["source"] == "workspace_fallback"
    assert payload["project_dirs"] == []
    assert payload["agent_project_dir"] is None


async def test_dirs_response_reads_agent_default_list(dirs) -> None:
    chat = _spec(meta={})
    config = SimpleNamespace(
        project_dir=None,
        project_dirs=[
            {"path": str(dirs.outer), "label": "agent-outer"},
        ],
    )
    with patch(
        "qwenpaw.config.config.load_agent_config",
        return_value=config,
    ):
        payload = await chats_api._project_dirs_response(
            chat,
            _workspace(dirs.workspace),
        )
    assert payload["source"] == "agent"
    assert payload["agent_project_dir"] is None
    assert payload["project_dirs"][0]["path"] == str(dirs.outer)
    assert payload["project_dirs"][0]["label"] == "agent-outer"


async def test_session_override_wins_over_agent_default(dirs) -> None:
    """A legacy singular ``project_dir`` in meta still outranks the agent."""
    chat = _spec(
        meta={"runtime_context": {"project_dir": str(dirs.inner)}},
    )
    config = SimpleNamespace(project_dir=str(dirs.outer), project_dirs=[])
    with patch(
        "qwenpaw.config.config.load_agent_config",
        return_value=config,
    ):
        payload = await chats_api._project_dirs_response(
            chat,
            _workspace(dirs.workspace),
        )
    assert payload["source"] == "session"
    assert payload["agent_project_dir"] == str(dirs.outer)
    assert [entry["path"] for entry in payload["project_dirs"]] == [
        str(dirs.inner),
    ]


async def test_single_dir_response_projects_primary_and_existence(
    dirs,
) -> None:
    chat = _spec(meta=_meta_dirs((str(dirs.outer), "L1")))
    payload = await chats_api._project_directory_response(
        chat,
        _workspace(dirs.workspace),
    )
    assert payload == {
        "project_dir": str(dirs.outer),
        "source": "session",
        "agent_project_dir": None,
        "exists": True,
    }


async def test_single_dir_response_survives_unreadable_agent_config(
    dirs,
) -> None:
    chat = _spec(meta={})
    with patch(
        "qwenpaw.config.config.load_agent_config",
        side_effect=RuntimeError("boom"),
    ):
        payload = await chats_api._project_directory_response(
            chat,
            _workspace(dirs.workspace),
        )
    assert payload["project_dir"] == str(dirs.workspace)
    assert payload["source"] == "workspace_fallback"
    assert payload["exists"] is True
    assert payload["agent_project_dir"] is None


async def test_single_dir_response_uses_legacy_singular_agent_value(
    dirs,
) -> None:
    chat = _spec(meta={})
    config = SimpleNamespace(project_dir=str(dirs.middle), project_dirs=None)
    with patch(
        "qwenpaw.config.config.load_agent_config",
        return_value=config,
    ):
        payload = await chats_api._project_directory_response(
            chat,
            _workspace(dirs.workspace),
        )
    assert payload["source"] == "agent"
    assert payload["project_dir"] == str(dirs.middle)
    assert payload["agent_project_dir"] == str(dirs.middle)


# --------------------------------------------------------------------- #
# Project-directory routes (deprecated singular + plural)
# --------------------------------------------------------------------- #


async def test_get_project_dir_route_reads_chat_then_projects(dirs) -> None:
    chat = _spec(meta=_meta_dirs((str(dirs.outer), None)))
    mgr = _mgr(get_chat=AsyncMock(return_value=chat))
    payload = await chats_api.get_chat_project_dir(
        "c1",
        mgr=mgr,
        workspace=_workspace(dirs.workspace),
    )
    mgr.get_chat.assert_awaited_once_with("c1")
    assert payload["project_dir"] == str(dirs.outer)


async def test_get_project_dir_route_missing_chat_is_404() -> None:
    mgr = _mgr(get_chat=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as raised:
        await chats_api.get_chat_project_dir(
            "gone",
            mgr=mgr,
            workspace=SimpleNamespace(),
        )
    assert raised.value.status_code == 404
    assert raised.value.detail == "Chat not found"


async def test_set_project_dir_route_persists_one_entry(dirs) -> None:
    stored = _spec(meta=_meta_dirs((str(dirs.inner), None)))
    mgr = _mgr(set_session_project_dirs=AsyncMock(return_value=stored))
    payload = await chats_api.set_chat_project_dir(
        "c1",
        chats_api.ProjectDirectoryUpdate(project_dir=str(dirs.inner)),
        mgr=mgr,
        workspace=_workspace(dirs.workspace),
    )
    mgr.set_session_project_dirs.assert_awaited_once_with(
        "c1",
        [{"path": str(dirs.inner), "label": None}],
    )
    assert payload["project_dir"] == str(dirs.inner)


async def test_set_project_dir_route_expands_user_home(
    dirs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``~`` in the submitted path is resolved before it is stored."""
    monkeypatch.setenv("HOME", str(dirs.tmp))
    stored = _spec(meta=_meta_dirs((str(dirs.outer), None)))
    mgr = _mgr(set_session_project_dirs=AsyncMock(return_value=stored))
    await chats_api.set_chat_project_dir(
        "c1",
        chats_api.ProjectDirectoryUpdate(project_dir="~/alpha"),
        mgr=mgr,
        workspace=_workspace(dirs.workspace),
    )
    call = mgr.set_session_project_dirs.await_args
    assert call.args[1] == [{"path": str(dirs.outer), "label": None}]


async def test_set_project_dir_route_rejects_missing_directory(
    dirs,
) -> None:
    mgr = _mgr()
    with pytest.raises(HTTPException) as raised:
        await chats_api.set_chat_project_dir(
            "c1",
            chats_api.ProjectDirectoryUpdate(
                project_dir=str(dirs.tmp / "absent"),
            ),
            mgr=mgr,
            workspace=_workspace(dirs.workspace),
        )
    assert raised.value.status_code == 400
    assert "unavailable" in raised.value.detail
    mgr.set_session_project_dirs.assert_not_awaited()


async def test_set_project_dir_route_rejects_regular_file(dirs) -> None:
    target = dirs.tmp / "plain.txt"
    target.write_text("x", encoding="utf-8")
    mgr = _mgr()
    with pytest.raises(HTTPException) as raised:
        await chats_api.set_chat_project_dir(
            "c1",
            chats_api.ProjectDirectoryUpdate(project_dir=str(target)),
            mgr=mgr,
            workspace=_workspace(dirs.workspace),
        )
    assert raised.value.status_code == 400
    mgr.set_session_project_dirs.assert_not_awaited()


async def test_set_project_dir_route_missing_chat_is_404(dirs) -> None:
    mgr = _mgr(set_session_project_dirs=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as raised:
        await chats_api.set_chat_project_dir(
            "gone",
            chats_api.ProjectDirectoryUpdate(project_dir=str(dirs.outer)),
            mgr=mgr,
            workspace=_workspace(dirs.workspace),
        )
    assert raised.value.status_code == 404


async def test_clear_project_dir_route_passes_none(dirs) -> None:
    stored = _spec(meta={})
    mgr = _mgr(set_session_project_dirs=AsyncMock(return_value=stored))
    payload = await chats_api.clear_chat_project_dir(
        "c1",
        mgr=mgr,
        workspace=_workspace(dirs.workspace),
    )
    mgr.set_session_project_dirs.assert_awaited_once_with("c1", None)
    assert payload["source"] == "workspace_fallback"


async def test_clear_project_dir_route_missing_chat_is_404() -> None:
    mgr = _mgr(set_session_project_dirs=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as raised:
        await chats_api.clear_chat_project_dir(
            "gone",
            mgr=mgr,
            workspace=SimpleNamespace(),
        )
    assert raised.value.status_code == 404


async def test_get_project_dirs_route_missing_chat_is_404() -> None:
    mgr = _mgr(get_chat=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as raised:
        await chats_api.get_chat_project_dirs(
            "gone",
            mgr=mgr,
            workspace=SimpleNamespace(),
        )
    assert raised.value.status_code == 404
    assert raised.value.detail == "Chat not found"


async def test_set_project_dirs_route_stores_normalized_list(dirs) -> None:
    stored = _spec(
        meta=_meta_dirs((str(dirs.outer), "L1"), (str(dirs.inner), None)),
    )
    mgr = _mgr(set_session_project_dirs=AsyncMock(return_value=stored))
    payload = await chats_api.set_chat_project_dirs(
        "c1",
        chats_api.ProjectDirsRequest(
            project_dirs=[
                chats_api.ProjectDirEntryPayload(
                    path=str(dirs.outer),
                    label="L1",
                ),
                chats_api.ProjectDirEntryPayload(path=str(dirs.inner)),
            ],
        ),
        mgr=mgr,
        workspace=_workspace(dirs.workspace),
    )
    mgr.set_session_project_dirs.assert_awaited_once_with(
        "c1",
        [
            {"path": str(dirs.outer), "label": "L1"},
            {"path": str(dirs.inner), "label": None},
        ],
    )
    assert payload["source"] == "session"
    assert len(payload["project_dirs"]) == 2


async def test_set_project_dirs_route_rejects_absent_directory(dirs) -> None:
    mgr = _mgr()
    with pytest.raises(HTTPException) as raised:
        await chats_api.set_chat_project_dirs(
            "c1",
            chats_api.ProjectDirsRequest(
                project_dirs=[
                    chats_api.ProjectDirEntryPayload(path=str(dirs.outer)),
                    chats_api.ProjectDirEntryPayload(
                        path=str(dirs.tmp / "absent"),
                    ),
                ],
            ),
            mgr=mgr,
            workspace=_workspace(dirs.workspace),
        )
    assert raised.value.status_code == 422
    assert raised.value.detail == f"Not a directory: {dirs.tmp / 'absent'}"
    mgr.set_session_project_dirs.assert_not_awaited()


async def test_set_project_dirs_route_rejects_blank_entries(dirs) -> None:
    """A payload of only unusable entries normalizes to nothing -> 422."""
    mgr = _mgr()
    with patch(
        "qwenpaw.services.project_directory.normalize_project_dir_list",
        return_value=[],
    ):
        with pytest.raises(HTTPException) as raised:
            await chats_api.set_chat_project_dirs(
                "c1",
                chats_api.ProjectDirsRequest(
                    project_dirs=[
                        chats_api.ProjectDirEntryPayload(
                            path=str(dirs.outer),
                        ),
                    ],
                ),
                mgr=mgr,
                workspace=_workspace(dirs.workspace),
            )
    assert raised.value.status_code == 422
    assert "at least one valid entry" in raised.value.detail
    mgr.set_session_project_dirs.assert_not_awaited()


async def test_set_project_dirs_route_guards_the_cap(dirs) -> None:
    """Over-cap guard: unreachable over HTTP today, kept as defence.

    ``ProjectDirsRequest`` allows at most ``MAX_PROJECT_DIRS`` entries and
    ``normalize_project_dir_list`` caps its own output, so the count can
    only exceed the cap if one of those two limits is ever raised.
    """
    from qwenpaw.services.project_directory import MAX_PROJECT_DIRS

    overflowing = [(dirs.tmp / f"d{index}", None) for index in range(12)]
    mgr = _mgr()
    with patch(
        "qwenpaw.services.project_directory.normalize_project_dir_list",
        return_value=overflowing,
    ):
        with pytest.raises(HTTPException) as raised:
            await chats_api.set_chat_project_dirs(
                "c1",
                chats_api.ProjectDirsRequest(
                    project_dirs=[
                        chats_api.ProjectDirEntryPayload(
                            path=str(dirs.outer),
                        ),
                    ],
                ),
                mgr=mgr,
                workspace=_workspace(dirs.workspace),
            )
    assert raised.value.status_code == 422
    assert raised.value.detail == (
        f"Too many project dirs (max {MAX_PROJECT_DIRS})"
    )
    mgr.set_session_project_dirs.assert_not_awaited()


async def test_set_project_dirs_route_missing_chat_is_404(dirs) -> None:
    mgr = _mgr(set_session_project_dirs=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as raised:
        await chats_api.set_chat_project_dirs(
            "gone",
            chats_api.ProjectDirsRequest(
                project_dirs=[
                    chats_api.ProjectDirEntryPayload(path=str(dirs.outer)),
                ],
            ),
            mgr=mgr,
            workspace=_workspace(dirs.workspace),
        )
    assert raised.value.status_code == 404
    assert raised.value.detail == "Chat not found: gone"


async def test_clear_project_dirs_route_passes_none(dirs) -> None:
    stored = _spec(meta={})
    mgr = _mgr(set_session_project_dirs=AsyncMock(return_value=stored))
    payload = await chats_api.clear_chat_project_dirs(
        "c1",
        mgr=mgr,
        workspace=_workspace(dirs.workspace),
    )
    mgr.set_session_project_dirs.assert_awaited_once_with("c1", None)
    assert payload["source"] == "workspace_fallback"


async def test_clear_project_dirs_route_missing_chat_is_404() -> None:
    mgr = _mgr(set_session_project_dirs=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as raised:
        await chats_api.clear_chat_project_dirs(
            "gone",
            mgr=mgr,
            workspace=SimpleNamespace(),
        )
    assert raised.value.status_code == 404
    assert raised.value.detail == "Chat not found: gone"


# --------------------------------------------------------------------- #
# GET /{chat_id}: history projection from persisted session state
# --------------------------------------------------------------------- #


def _state_with_context(text: str) -> dict:
    """Persisted 2.x state: messages live on ``agent.state.context``."""
    msg = Msg(
        name="user",
        content=[TextBlock(type="text", text=text)],
        role="user",
    )
    return {"agent": {"state": AgentState(context=[msg]).model_dump()}}


def _chat_workspace(*, backend: str = "qwenpaw", status: str = "idle"):
    """Workspace carrying the three collaborators ``get_chat`` touches."""
    return SimpleNamespace(
        config=SimpleNamespace(backend=backend, backend_settings={}),
        task_tracker=SimpleNamespace(
            get_status=AsyncMock(return_value=status),
        ),
        harness_runtime=SimpleNamespace(hydrate_session=AsyncMock()),
    )


async def test_get_chat_missing_spec_is_404() -> None:
    mgr = _mgr(get_chat=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as raised:
        await chats_api.get_chat(
            chat_id="gone",
            include_app_owned=True,
            mgr=mgr,
            session=SimpleNamespace(),
            workspace=_chat_workspace(),
        )
    assert raised.value.status_code == 404
    assert raised.value.detail == "Chat not found: gone"


async def test_get_chat_projects_context_messages() -> None:
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value=_state_with_context("hello"),
        ),
    )
    workspace = _chat_workspace(status="running")
    history = await chats_api.get_chat(
        chat_id="c1",
        include_app_owned=True,
        mgr=_mgr(),
        session=session,
        workspace=workspace,
    )
    session.get_session_state_dict.assert_awaited_once_with(
        "console:u",
        "u",
        "console",
    )
    assert history.status == "running"
    assert len(history.messages) == 1
    assert history.messages[0].role.value == "user"
    workspace.harness_runtime.hydrate_session.assert_not_awaited()


async def test_get_chat_without_state_returns_empty_history() -> None:
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value={}),
    )
    history = await chats_api.get_chat(
        chat_id="c1",
        include_app_owned=True,
        mgr=_mgr(),
        session=session,
        workspace=_chat_workspace(status="idle"),
    )
    assert history.messages == []
    assert history.status == "idle"


async def test_get_chat_hydrates_third_party_backend_sessions() -> None:
    """A non-qwenpaw backend without context is re-hydrated, then re-read."""
    empty = {"agent": {"state": {}}}
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            side_effect=[empty, _state_with_context("late")],
        ),
    )
    workspace = _chat_workspace(backend="claude_code")
    history = await chats_api.get_chat(
        chat_id="c1",
        include_app_owned=True,
        mgr=_mgr(),
        session=session,
        workspace=workspace,
    )
    workspace.harness_runtime.hydrate_session.assert_awaited_once_with(
        backend="claude_code",
        session_id="console:u",
        user_id="u",
        channel="console",
        settings={},
    )
    assert session.get_session_state_dict.await_count == 2
    assert len(history.messages) == 1


async def test_get_chat_swallows_failed_third_party_recovery() -> None:
    """Recovery is best-effort: the route still answers with what it has."""
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value={}),
    )
    workspace = _chat_workspace(backend="claude_code")
    workspace.harness_runtime.hydrate_session = AsyncMock(
        side_effect=RuntimeError("upstream down"),
    )
    history = await chats_api.get_chat(
        chat_id="c1",
        include_app_owned=True,
        mgr=_mgr(),
        session=session,
        workspace=workspace,
    )
    assert history.messages == []


async def test_get_chat_skips_hydration_for_native_backend() -> None:
    """``backend == 'qwenpaw'`` never reaches the recovery path."""
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value={}),
    )
    workspace = _chat_workspace(backend="qwenpaw")
    await chats_api.get_chat(
        chat_id="c1",
        include_app_owned=True,
        mgr=_mgr(),
        session=session,
        workspace=workspace,
    )
    workspace.harness_runtime.hydrate_session.assert_not_awaited()
    assert session.get_session_state_dict.await_count == 1


async def test_get_chat_falls_back_to_legacy_memory() -> None:
    """Unparseable 2.x state falls back to the 1.x ``agent.memory`` shape."""
    msg = Msg(
        name="user",
        content=[TextBlock(type="text", text="legacy")],
        role="user",
    )
    state = {
        "agent": {
            "state": {"context": "not-a-list"},
            "memory": {
                "content": [[msg.model_dump(), ["HINT"]]],
                "_compressed_summary": "S",
            },
        },
    }
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value=state),
    )
    history = await chats_api.get_chat(
        chat_id="c1",
        include_app_owned=True,
        mgr=_mgr(),
        session=session,
        workspace=_chat_workspace(),
    )
    assert len(history.messages) == 1


async def test_get_chat_ignores_empty_legacy_memory() -> None:
    """An empty 1.x memory block yields no messages and no crash."""
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={"agent": {"memory": {}}},
        ),
    )
    history = await chats_api.get_chat(
        chat_id="c1",
        include_app_owned=True,
        mgr=_mgr(),
        session=session,
        workspace=_chat_workspace(),
    )
    assert history.messages == []
