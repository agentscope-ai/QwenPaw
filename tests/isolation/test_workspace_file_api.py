# -*- coding: utf-8 -*-
"""Files 页面在共享 Agent 下的用户运行空间隔离契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.app.routers import workspace as workspace_router
from qwenpaw.app.routers import project_directory as project_directory_router
from qwenpaw.identity.models import PlatformRole
from qwenpaw.services import workspace_files
from qwenpaw.services.workspace_files import resolve_files_workspace_access


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")


def test_user_role_resolves_personal_project_and_read_only_agent_files(
    tmp_path: Path,
) -> None:
    """错误地把 user 项目根指回 Agent 草稿时，本测试必须失败。"""
    shared = tmp_path / "workspaces" / "shared-agent"
    shared.mkdir(parents=True)

    access = resolve_files_workspace_access(
        agent_id="shared-agent",
        agent_workspace=shared,
        agent_project=shared / "project",
        actor_user_id=USER_A,
        access_role=AgentResourceRole.USER,
        working_dir=tmp_path,
    )

    assert access.project.path == (
        tmp_path / "user_workspaces" / str(USER_A) / "shared-agent"
    )
    assert access.project.kind == "user_runtime"
    assert access.project.read_only is False
    assert access.workspace.path == shared
    assert access.workspace.read_only is True


def test_two_users_resolve_different_runtime_roots(tmp_path: Path) -> None:
    """移除 user_id 隔离键时，本测试必须失败。"""
    shared = tmp_path / "workspaces" / "shared-agent"
    shared.mkdir(parents=True)

    roots = [
        resolve_files_workspace_access(
            agent_id="shared-agent",
            agent_workspace=shared,
            agent_project=shared,
            actor_user_id=user_id,
            access_role=AgentResourceRole.USER,
            working_dir=tmp_path,
        ).project.path
        for user_id in (USER_A, USER_B)
    ]

    assert roots == [
        tmp_path / "user_workspaces" / str(USER_A) / "shared-agent",
        tmp_path / "user_workspaces" / str(USER_B) / "shared-agent",
    ]


@pytest.fixture(name="shared_agent_files_client")
def fixture_shared_agent_files_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """使用真实 Files 路由，只替换认证外部边界。"""
    shared = tmp_path / "workspaces" / "shared-agent"
    shared.mkdir(parents=True)
    (shared / "AGENTS.md").write_text("shared", encoding="utf-8")
    workspace = SimpleNamespace(
        agent_id="shared-agent",
        workspace_dir=shared,
        workspace_kind="draft",
        workspace_key="workspaces/shared-agent",
        workspace_read_only=False,
    )

    async def get_workspace(request, **_kwargs):
        user_id = UUID(request.headers["X-Test-User"])
        request.state.actor = ActorContext(
            user_id=user_id,
            actor_type=ActorType.USER,
            platform_role=PlatformRole.MEMBER,
            admin_mode=False,
            request_id="req-files-isolation",
        )
        request.state.agent_access = SimpleNamespace(
            role=AgentResourceRole.USER,
            historical_read_only=False,
        )
        return workspace

    monkeypatch.setattr(
        workspace_router,
        "get_agent_for_request",
        get_workspace,
    )
    monkeypatch.setattr(
        project_directory_router,
        "get_running_config_workspace",
        get_workspace,
    )
    monkeypatch.setattr(workspace_files, "WORKING_DIR", tmp_path)

    class FakeWorkspaceRepository:
        def __init__(self, **_kwargs) -> None:
            pass

        async def ensure_private(self, **_kwargs):
            return None

    persistence_module = __import__(
        "qwenpaw.persistence.agent_user_workspaces",
        fromlist=["AgentUserWorkspaceRepository"],
    )
    monkeypatch.setattr(
        persistence_module,
        "AgentUserWorkspaceRepository",
        FakeWorkspaceRepository,
    )

    app = FastAPI()
    app.state.shared_workspace = shared
    app.state.working_dir = tmp_path
    app.include_router(workspace_router.router, prefix="/api")
    app.include_router(project_directory_router.router, prefix="/api")
    return TestClient(app)


def test_user_can_write_personal_project_but_not_agent_workspace(
    shared_agent_files_client: TestClient,
) -> None:
    """恢复通用配置写权限校验时，本测试必须捕获 user 项目误拒绝。"""
    headers = {"X-Test-User": str(USER_A)}

    personal = shared_agent_files_client.put(
        "/api/workspace/file-content",
        params={"path": "notes.md", "root": "project"},
        headers=headers,
        json={"content": "private-a"},
    )
    shared = shared_agent_files_client.put(
        "/api/workspace/file-content",
        params={"path": "AGENTS.md", "root": "workspace"},
        headers=headers,
        json={"content": "overwritten"},
    )

    assert personal.status_code == 200
    assert shared.status_code == 403
    assert (
        shared_agent_files_client.app.state.working_dir
        / "user_workspaces"
        / str(USER_A)
        / "shared-agent"
        / "notes.md"
    ).read_text(encoding="utf-8") == "private-a"
    assert (
        shared_agent_files_client.app.state.shared_workspace / "AGENTS.md"
    ).read_text(encoding="utf-8") == "shared"


def test_same_filename_is_isolated_between_users(
    shared_agent_files_client: TestClient,
) -> None:
    """错误复用同一运行目录时，第二个用户会覆盖第一个用户并导致失败。"""
    for user_id, content in ((USER_A, "alpha"), (USER_B, "beta")):
        response = shared_agent_files_client.put(
            "/api/workspace/file-content",
            params={"path": "same-name.md", "root": "project"},
            headers={"X-Test-User": str(user_id)},
            json={"content": content},
        )
        assert response.status_code == 200

    working_dir = shared_agent_files_client.app.state.working_dir
    assert (
        working_dir
        / "user_workspaces"
        / str(USER_A)
        / "shared-agent"
        / "same-name.md"
    ).read_text(encoding="utf-8") == "alpha"
    assert (
        working_dir
        / "user_workspaces"
        / str(USER_B)
        / "shared-agent"
        / "same-name.md"
    ).read_text(encoding="utf-8") == "beta"


def test_user_runtime_preserves_file_preview_upload_and_download_features(
    shared_agent_files_client: TestClient,
) -> None:
    """任一读取或上传端点绕回 Agent 草稿时，本测试必须失败。"""
    headers = {"X-Test-User": str(USER_A)}
    uploaded = shared_agent_files_client.post(
        "/api/workspace/file-upload",
        params={"root": "project"},
        headers=headers,
        files={"files": ("page.html", b"<h1>private</h1>", "text/html")},
    )
    tree = shared_agent_files_client.get(
        "/api/workspace/tree",
        params={"root": "project"},
        headers=headers,
    )
    content = shared_agent_files_client.get(
        "/api/workspace/file-content",
        params={"root": "project", "path": "page.html"},
        headers=headers,
    )
    downloaded = shared_agent_files_client.get(
        "/api/workspace/file-download",
        params={"root": "project", "path": "page.html"},
        headers=headers,
    )
    preview = shared_agent_files_client.get(
        "/api/workspace/html-file-uri",
        params={"root": "project", "path": "page.html"},
        headers=headers,
    )

    assert uploaded.status_code == 200
    assert [item["name"] for item in tree.json()["entries"]] == [
        "artifacts",
        "media",
        "page.html",
    ]
    assert content.json()["content"] == "<h1>private</h1>"
    assert downloaded.content == b"<h1>private</h1>"
    assert preview.status_code == 200
    assert str(USER_A) in preview.json()["uri"]


def test_coding_and_zip_features_use_user_runtime(
    shared_agent_files_client: TestClient,
) -> None:
    """Coding/ZIP 仍使用共享 Agent 目录时，本测试必须失败。"""
    headers = {"X-Test-User": str(USER_A)}
    code_saved = shared_agent_files_client.put(
        "/api/workspace/code-files/src/main.py",
        headers=headers,
        json={"content": "print('private')"},
    )

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("imported.txt", "runtime")
    zip_uploaded = shared_agent_files_client.post(
        "/api/workspace/upload",
        headers=headers,
        files={"file": ("runtime.zip", archive.getvalue(), "application/zip")},
    )
    zip_downloaded = shared_agent_files_client.get(
        "/api/workspace/download",
        headers=headers,
    )

    assert code_saved.status_code == 200
    assert zip_uploaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_downloaded.content)) as bundle:
        assert bundle.read("src/main.py") == b"print('private')"
        assert bundle.read("imported.txt") == b"runtime"
        assert "AGENTS.md" not in bundle.namelist()

    shared = shared_agent_files_client.app.state.shared_workspace
    assert not (shared / "src" / "main.py").exists()
    assert not (shared / "imported.txt").exists()


def test_project_directory_reports_split_runtime_and_agent_permissions(
    shared_agent_files_client: TestClient,
) -> None:
    """GET 仍要求 Agent 配置编辑权时，仅使用用户无法打开文件页。"""
    response = shared_agent_files_client.get(
        "/api/workspace/project-directory",
        headers={"X-Test-User": str(USER_A)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_kind"] == "user_runtime"
    assert payload["project_read_only"] is False
    assert payload["workspace_kind"] == "draft"
    assert payload["workspace_read_only"] is True
    assert payload["path"].endswith(f"{USER_A}\\shared-agent")


def test_runtime_zip_rejects_sibling_prefix_escape(
    shared_agent_files_client: TestClient,
) -> None:
    """字符串前缀校验误把同级相似目录当作子目录时，本测试必须失败。"""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../shared-agent-evil/escaped.txt", "denied")

    response = shared_agent_files_client.post(
        "/api/workspace/upload",
        headers={"X-Test-User": str(USER_A)},
        files={"file": ("escape.zip", archive.getvalue(), "application/zip")},
    )

    assert response.status_code == 400
