"""Agent 配置目录不得作为绕过用户归属的旧运行数据读取入口。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile
from io import BytesIO

import httpx
import pytest
from fastapi import FastAPI
from fastapi import HTTPException

from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.app.routers import workspace


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [AgentResourceRole.OWNER, AgentResourceRole.USER])
async def test_config_file_routes_hide_private_runtime_records(tmp_path, monkeypatch, role):
    shared = tmp_path / "shared-agent"
    private = tmp_path / "private-user"
    for root in (shared, private):
        (root / "sessions").mkdir(parents=True)
        (root / "sessions" / "old.json").write_text("private-history", encoding="utf-8")
    (shared / "AGENTS.md").write_text("shared-instructions", encoding="utf-8")
    project = private if role is AgentResourceRole.USER else shared
    access = SimpleNamespace(project=SimpleNamespace(path=project, read_only=False), workspace=SimpleNamespace(path=shared, read_only=False))
    monkeypatch.setattr(workspace, "get_agent_for_request", AsyncMock(return_value=SimpleNamespace(workspace_dir=shared, agent_id="shared-agent")))
    monkeypatch.setattr(workspace, "get_files_workspace_access", AsyncMock(return_value=access))
    monkeypatch.setattr(workspace, "get_project_dir_for_request", AsyncMock(return_value=shared))
    monkeypatch.setattr(workspace, "get_agent_access_state", lambda _: (role, False))
    monkeypatch.setattr(workspace, "is_multi_user_enabled", lambda: True)
    app = FastAPI()
    app.include_router(workspace.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for endpoint in ("file-content", "file-download", "file-metadata"):
            response = await client.get(f"/api/workspace/{endpoint}", params={"root": "workspace", "path": "sessions/old.json"})
            assert response.status_code == 403
            assert b"private-history" not in response.content
        tree = await client.get("/api/workspace/tree", params={"root": "workspace"})
        assert "sessions" not in {entry["name"] for entry in tree.json()["entries"]}
        public = await client.get("/api/workspace/file-content", params={"root": "workspace", "path": "AGENTS.md"})
        assert public.status_code == 200
        if role is AgentResourceRole.USER:
            mine = await client.get("/api/workspace/file-content", params={"root": "project", "path": "sessions/old.json"})
            assert mine.status_code == 200


def test_agent_export_has_no_private_runtime_records(tmp_path, monkeypatch):
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "other.json").write_text("private-history", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("instructions", encoding="utf-8")
    with ZipFile(workspace._zip_directory(tmp_path, exclude_private_state=True)) as archive:
        assert archive.namelist() == ["AGENTS.md"]


def test_wrapped_agent_import_cannot_overwrite_private_runtime_records(tmp_path):
    (tmp_path / "sessions").mkdir()
    target = tmp_path / "sessions" / "other.json"
    target.write_bytes(b"unchanged")
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("wrapper/sessions/other.json", "unexpected")
    with pytest.raises(HTTPException) as error:
        workspace._validate_and_extract_zip(payload.getvalue(), tmp_path, exclude_private_state=True)
    assert error.value.status_code == 403
    assert target.read_bytes() == b"unchanged"
