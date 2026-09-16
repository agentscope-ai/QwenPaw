# -*- coding: utf-8 -*-
"""文件页记忆读写必须使用服务端解析的作用域。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request

from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.app.agent_context import allowed_agent_roles_for_request
from qwenpaw.memory_scope.models import MemoryScope
from qwenpaw.app.routers.workspace import (
    MdFileContent,
    create_memory_file,
    list_memory_files,
    read_memory_file,
    write_memory_file,
)


def _request() -> SimpleNamespace:
    return SimpleNamespace()


def test_private_memory_write_allows_use_only_role_to_reach_scope_policy() -> None:
    request = Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/api/workspace/memory/a.md",
            "headers": [],
        },
    )

    assert allowed_agent_roles_for_request(request, "agent-a") == set(
        AgentResourceRole,
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/api/workspace/file-content"),
        ("POST", "/api/workspace/file-upload"),
        ("PUT", "/api/workspace/code-files/src/main.py"),
        ("POST", "/api/workspace/upload"),
    ],
)
def test_runtime_file_writes_reach_root_specific_policy(
    method: str,
    path: str,
) -> None:
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
        },
    )

    assert allowed_agent_roles_for_request(request, "agent-a") == set(
        AgentResourceRole,
    )


@pytest.mark.asyncio
async def test_private_memory_files_use_resolved_private_workspace(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "user_workspaces" / "user-a" / "agent-a"
    private_root.mkdir(parents=True)
    manager = SimpleNamespace(
        list_memory_mds=lambda section: [
            {
                "filename": "2026-08-25.md",
                "path": "daily/2026-08-25.md",
                "size": 3,
                "created_time": "2026-08-25T00:00:00Z",
                "modified_time": "2026-08-25T00:00:00Z",
            }
        ],
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace._resolve_memory_workspace",
            new=AsyncMock(return_value=(private_root, True)),
        ),
        patch(
            "qwenpaw.app.routers.workspace.AgentMdManager",
            return_value=manager,
        ) as manager_type,
    ):
        files = await list_memory_files(
            _request(),
            section="daily",
            scope=MemoryScope.PRIVATE,
        )

    assert files[0].filename == "2026-08-25.md"
    manager_type.assert_called_once_with(str(private_root), agent_id="agent-a")


@pytest.mark.asyncio
async def test_private_memory_files_list_nested_relative_paths(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "user_workspaces" / "user-a" / "agent-a"
    memory_file = private_root / "memory" / "2026-09-15" / "topic.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("private memory", encoding="utf-8")
    config = SimpleNamespace(
        running=SimpleNamespace(
            reme_light_memory_config=SimpleNamespace(
                daily_dir="memory",
                digest_dir="digest",
            ),
        ),
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace._resolve_memory_workspace",
            new=AsyncMock(return_value=(private_root, True)),
        ),
        patch(
            "qwenpaw.agents.memory.agent_md_manager.load_agent_config",
            return_value=config,
        ),
    ):
        files = await list_memory_files(
            _request(),
            section="daily",
            scope=MemoryScope.PRIVATE,
        )

    assert [file.filename for file in files] == ["2026-09-15/topic.md"]
    assert [file.path for file in files] == ["2026-09-15/topic.md"]


@pytest.mark.asyncio
async def test_read_does_not_accept_a_user_id_override(tmp_path: Path) -> None:
    resolver = AsyncMock(return_value=(tmp_path, True))
    manager = SimpleNamespace(read_memory_md=lambda path, section: "mine")
    with (
        patch(
            "qwenpaw.app.routers.workspace._resolve_memory_workspace",
            new=resolver,
        ),
        patch(
            "qwenpaw.app.routers.workspace.AgentMdManager",
            return_value=manager,
        ),
    ):
        response = await read_memory_file(
            "a.md",
            _request(),
            section="daily",
            scope=MemoryScope.PRIVATE,
        )

    assert response.content == "mine"
    resolver.assert_awaited_once_with(_request(), MemoryScope.PRIVATE, write=False)


@pytest.mark.asyncio
async def test_public_memory_write_requires_edit_permission(
    tmp_path: Path,
) -> None:
    with patch(
        "qwenpaw.app.routers.workspace._resolve_memory_workspace",
        new=AsyncMock(return_value=(tmp_path, False)),
    ):
        with pytest.raises(HTTPException) as error:
            await write_memory_file(
                "a.md",
                MdFileContent(content="forbidden"),
                _request(),
                section="daily",
                scope=MemoryScope.PUBLIC,
            )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_create_memory_file_rejects_existing_file(tmp_path: Path) -> None:
    manager = SimpleNamespace(
        create_memory_md=lambda path, content, section: (_ for _ in ()).throw(
            FileExistsError(path),
        ),
    )
    with (
        patch(
            "qwenpaw.app.routers.workspace._resolve_memory_workspace",
            new=AsyncMock(return_value=(tmp_path, True)),
        ),
        patch(
            "qwenpaw.app.routers.workspace.AgentMdManager",
            return_value=manager,
        ),
    ):
        with pytest.raises(HTTPException) as error:
            await create_memory_file(
                "existing.md",
                MdFileContent(content=""),
                _request(),
                section="daily",
                scope=MemoryScope.PUBLIC,
            )

    assert error.value.status_code == 409
