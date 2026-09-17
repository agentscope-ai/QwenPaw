# -*- coding: utf-8 -*-
"""Tests for Files API project-directory request context."""

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from uuid import uuid4
from fastapi import HTTPException
from starlette.requests import Request
from qwenpaw.access.agent_repository import AgentVisibility

from qwenpaw.app.agent_context import (
    get_project_dir_for_request,
    get_running_config_workspace,
)


@pytest.mark.asyncio
async def test_private_chat_preview_uses_the_same_task_directory(tmp_path, monkeypatch):
    from qwenpaw.access.agent_repository import agent_database_id
    owner, chat_id = uuid4(), uuid4()
    conversation = SimpleNamespace(owner_user_id=owner, agent_id=agent_database_id("default"), shared_app_id=None, publication_id=None)
    repository = SimpleNamespace(get_conversation=AsyncMock(return_value=conversation))
    repository.with_user = lambda user: repository
    workspace = SimpleNamespace(agent_id="default", workspace_dir=tmp_path / "shared", chat_manager=SimpleNamespace(
        get_chat=AsyncMock(return_value=SimpleNamespace(id=str(chat_id), meta={})), conversation_repository=repository))
    monkeypatch.setattr("qwenpaw.app.agent_context.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.app.agent_context.get_actor", lambda request: SimpleNamespace(user_id=owner))
    expected = tmp_path / "private" / str(chat_id)
    monkeypatch.setattr("qwenpaw.services.workspace_files.resolve_private_task_directory", lambda **kwargs: expected)
    request = Request({"type": "http", "headers": [(b"x-chat-id", str(chat_id).encode())]})
    assert await get_project_dir_for_request(request, workspace) == expected
    conversation.owner_user_id = uuid4()
    with pytest.raises(HTTPException) as error:
        await get_project_dir_for_request(request, workspace)
    assert error.value.status_code == 404


def _request(project_dir: Path) -> Request:
    """Build a request carrying a pending Session directory."""
    return Request(
        {
            "type": "http",
            "headers": [
                (
                    b"x-session-project-dir",
                    str(project_dir).encode(),
                ),
            ],
        },
    )


@pytest.mark.asyncio
async def test_pending_session_project_dir_is_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the pending directory before a backend Chat exists."""
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=None),
    )
    workspace = SimpleNamespace(
        agent_id="default",
        workspace_dir=tmp_path / "workspace",
    )

    result = await get_project_dir_for_request(
        _request(tmp_path),
        workspace,
    )

    assert result == tmp_path.resolve()


@pytest.mark.asyncio
async def test_pending_session_project_dir_must_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an unavailable pending directory."""
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=None),
    )
    workspace = SimpleNamespace(
        agent_id="default",
        workspace_dir=tmp_path,
    )

    with pytest.raises(HTTPException) as error:
        await get_project_dir_for_request(
            _request(tmp_path / "missing"),
            workspace,
        )

    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_project_resolution_does_not_block_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slow configuration I/O runs outside the async request loop."""

    def _slow_load(_agent_id: str):
        time.sleep(0.1)
        return SimpleNamespace(project_dir=None)

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        _slow_load,
    )
    workspace = SimpleNamespace(
        agent_id="default",
        workspace_dir=tmp_path / "workspace",
    )
    started = asyncio.get_running_loop().time()

    resolution = asyncio.create_task(
        get_project_dir_for_request(_request(tmp_path), workspace),
    )
    await asyncio.sleep(0.01)

    assert asyncio.get_running_loop().time() - started < 0.08
    assert await resolution == tmp_path.resolve()


@pytest.mark.asyncio
async def test_runtime_config_governance_requires_admin_and_records_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/workspace/access",
            "headers": [
                (b"x-agent-id", b"managed-bot"),
                (b"x-agent-governance", b"runtime-config"),
            ],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    multi_agent_manager=SimpleNamespace(
                        get_agent=lambda _agent_id: None,
                    ),
                ),
            ),
        },
    )
    workspace = SimpleNamespace(agent_id="managed-bot")
    manager = SimpleNamespace(get_agent=AsyncMock(return_value=workspace))
    request.scope["app"].state.multi_agent_manager = manager
    governance = SimpleNamespace(
        agent_key="managed-bot",
        owner_user_id="owner-2",
        visibility=AgentVisibility.PRIVATE,
    )
    service = SimpleNamespace(
        require_admin_agent=AsyncMock(return_value=governance),
    )
    actor = SimpleNamespace(user_id="admin-1", platform_role="admin")
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_actor",
        lambda _request: actor,
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context._get_agent_governance_service",
        lambda: service,
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={"managed-bot": SimpleNamespace(enabled=True)},
            ),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.is_multi_user_enabled",
        lambda: True,
    )

    result = await get_running_config_workspace(
        request,
        action="agent.admin.runtime_config.view",
    )

    assert result is workspace
    assert request.state.agent_governance is governance
    service.require_admin_agent.assert_awaited_once_with(
        actor=actor,
        agent_key="managed-bot",
        action="agent.admin.runtime_config.view",
    )


@pytest.mark.asyncio
async def test_runtime_config_governance_marker_is_rejected_on_other_workspace_path() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/workspace/files",
            "headers": [
                (b"x-agent-id", b"managed-bot"),
                (b"x-agent-governance", b"runtime-config"),
            ],
            "app": SimpleNamespace(state=SimpleNamespace()),
        },
    )

    with pytest.raises(HTTPException) as error:
        await get_running_config_workspace(
            request,
            action="agent.admin.runtime_config.view",
        )

    assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/workspace/memory",
        "/api/workspace/memory/daily/2026-08-25.md",
        "/api/agents/managed-bot/memory/scopes",
        "/api/agents/managed-bot/memory/graph",
    ],
)
async def test_runtime_config_governance_accepts_memory_management_paths(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = SimpleNamespace(agent_id="managed-bot")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [
                (b"x-agent-id", b"managed-bot"),
                (b"x-agent-governance", b"runtime-config"),
            ],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    multi_agent_manager=SimpleNamespace(
                        get_agent=AsyncMock(return_value=workspace),
                    ),
                ),
            ),
        },
    )
    governance = SimpleNamespace(agent_key="managed-bot")
    monkeypatch.setattr(
        "qwenpaw.app.agent_context._get_agent_governance_service",
        lambda: SimpleNamespace(
            require_admin_agent=AsyncMock(return_value=governance),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_actor",
        lambda _request: SimpleNamespace(platform_role="admin"),
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={"managed-bot": SimpleNamespace(enabled=True)},
            ),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.is_multi_user_enabled",
        lambda: True,
    )

    result = await get_running_config_workspace(
        request,
        action="agent.admin.memory.view",
    )

    assert result is workspace


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/coding-mode",
        "/api/plan/config",
        "/api/workspace/project-directory",
        "/api/workspace/project-directory/list",
        "/api/workspace/project-directory/create",
        "/api/workspace/project-directory/clone",
        "/api/workspace/project-directory/import-local",
        "/api/workspace/project-directory/upload-zip",
        "/api/workspace/project-directory/browse-dirs",
    ],
)
async def test_runtime_config_governance_accepts_card_related_paths(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = SimpleNamespace(agent_id="managed-bot")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [
                (b"x-agent-id", b"managed-bot"),
                (b"x-agent-governance", b"runtime-config"),
            ],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    multi_agent_manager=SimpleNamespace(
                        get_agent=AsyncMock(return_value=workspace),
                    ),
                ),
            ),
        },
    )
    governance = SimpleNamespace(agent_key="managed-bot")
    monkeypatch.setattr(
        "qwenpaw.app.agent_context._get_agent_governance_service",
        lambda: SimpleNamespace(
            require_admin_agent=AsyncMock(return_value=governance),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_actor",
        lambda _request: SimpleNamespace(platform_role="admin"),
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={"managed-bot": SimpleNamespace(enabled=True)},
            ),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.is_multi_user_enabled",
        lambda: True,
    )

    result = await get_running_config_workspace(request, action="test.action")

    assert result is workspace
    assert request.state.agent_governance is governance
