from types import SimpleNamespace
from uuid import uuid4
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import files
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.chats.repo import AttachmentRecord


@pytest.fixture(autouse=True)
def authorized_preview_agent(monkeypatch):
    async def get_agent(request, agent_id=None, **kwargs):
        return SimpleNamespace(agent_id=agent_id or request.headers.get("X-Agent-Id") or "default")

    monkeypatch.setattr("qwenpaw.app.agent_context.get_agent_for_request", get_agent)
    monkeypatch.setattr("qwenpaw.artifacts.repository.PostgresArtifactRepository", lambda **kwargs: SimpleNamespace(
        list_active=AsyncMock(return_value=[]), get=AsyncMock(return_value=None),
    ))


@pytest.mark.parametrize("foreign", [False, True])
def test_multi_user_preview_is_limited_to_own_runtime(tmp_path, monkeypatch, foreign):
    owner = uuid4()
    path_owner = uuid4() if foreign else owner
    target = tmp_path / "user_workspaces" / str(path_owner) / "default" / "report.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-private-report")
    monkeypatch.setattr(files, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(files, "_ALLOWED_ROOT", tmp_path)
    monkeypatch.setattr(files, "_check_path", lambda path: None)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.access.dependencies.get_actor",
        lambda request: SimpleNamespace(user_id=owner),
    )
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    client = TestClient(app)
    response = client.get("/api/files/preview/" + target.as_posix())
    assert response.status_code == (403 if foreign else 200)
    if foreign:
        assert b"%PDF-private-report" not in response.content


@pytest.mark.parametrize("case", ["owned", "owned_saved", "foreign", "unregistered", "deleted", "wrong_agent", "outside_media", "symlink"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_legacy_media_preview_requires_matching_live_attachment(tmp_path, monkeypatch, case, method):
    owner = uuid4()
    relative = "AGENTS.md" if case == "outside_media" else ("documents/image.png" if case == "owned_saved" else "media/image.png")
    target = tmp_path / "workspaces" / "designer" / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(b"owned-legacy-image")
    now = datetime.now(UTC)
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=uuid4() if case == "foreign" else owner,
        agent_id=agent_database_id("default" if case == "wrong_agent" else "designer"),
        storage_key=str(target), original_name=target.name, media_type="image/png",
        size=18, content_hash="sha256:test", created_at=now,
        lifecycle="deleted" if case == "deleted" else ("saved" if case == "owned_saved" else "temporary"),
    )
    repository = SimpleNamespace(list_owned_attachments=AsyncMock(return_value=[] if case == "unregistered" else [record]))
    repository.with_user = lambda user_id: repository
    monkeypatch.setattr("qwenpaw.app.chats.repo.PostgresConversationRepository", lambda **kwargs: repository)
    monkeypatch.setattr(files, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(files, "_ALLOWED_ROOT", tmp_path)
    monkeypatch.setattr(files, "_check_path", lambda path: None)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.access.dependencies.get_actor", lambda request: SimpleNamespace(user_id=owner))
    if case == "symlink":
        def reject(path):
            raise ValueError("artifact_symlink_denied")
        monkeypatch.setattr("qwenpaw.artifacts.service.reject_symlink_path", reject)
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    response = TestClient(app).request(method, "/api/files/preview/" + target.as_posix())
    owned = case in {"owned", "owned_saved"}
    assert response.status_code == (200 if owned else 403)
    if owned and method == "GET":
        assert response.content == b"owned-legacy-image"
    elif not owned:
        assert b"owned-legacy-image" not in response.content


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("case", ["owned", "wrong_agent", "revoked"])
def test_preview_of_chinese_pdf_rechecks_current_agent_access(tmp_path, monkeypatch, method, case):
    owner = uuid4()
    target = (tmp_path / "user_workspaces" / str(owner) / "designer"
              / "artifacts" / ".registered" / "snapshot" / "2026-09-17_防水行业新闻简报.pdf")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-owned-waterproofing-brief")
    monkeypatch.setattr(files, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(files, "_ALLOWED_ROOT", tmp_path)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.access.dependencies.get_actor", lambda request: SimpleNamespace(user_id=owner))
    authorized = AsyncMock()

    async def get_agent(request, agent_id=None, **kwargs):
        await authorized(agent_id)
        if case == "revoked":
            from fastapi import HTTPException
            raise HTTPException(403, "forbidden")
        return SimpleNamespace(agent_id=agent_id)

    monkeypatch.setattr("qwenpaw.app.agent_context.get_agent_for_request", get_agent)
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    response = TestClient(app).request(
        method, "/api/files/preview/" + quote(target.as_posix(), safe=""),
        headers={"X-Agent-Id": "other-agent" if case == "wrong_agent" else "designer"},
    )
    assert response.status_code == (200 if case == "owned" else 403)
    if case != "wrong_agent":
        authorized.assert_awaited_once_with("designer")
    if case == "owned" and method == "GET":
        assert response.content == target.read_bytes()
    elif case != "owned":
        assert b"%PDF-owned-waterproofing-brief" not in response.content


@pytest.mark.asyncio
async def test_preview_does_not_decode_a_literal_percent_filename_again(tmp_path, monkeypatch):
    import httpx

    owner = uuid4()
    target = tmp_path / "user_workspaces" / str(owner) / "default" / "2026-09-17_%E9%98%B2.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-percent-name")
    monkeypatch.setattr(files, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(files, "_ALLOWED_ROOT", tmp_path)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.access.dependencies.get_actor", lambda request: SimpleNamespace(user_id=owner))
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    # 当前 Starlette TestClient 兼容层会额外 unquote；直接 ASGI transport
    # 保持与真实服务器一致的一次 URL 解码，才能检测应用层的重复解码。
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/files/preview/" + quote(target.as_posix(), safe=""))
    assert response.status_code == 200
    assert response.content == b"%PDF-percent-name"


@pytest.mark.asyncio
async def test_encoded_traversal_cannot_read_another_agent_in_same_user_tree(tmp_path, monkeypatch):
    import httpx

    owner = uuid4()
    own_root = tmp_path / "user_workspaces" / str(owner)
    (own_root / "designer").mkdir(parents=True)
    target = own_root / "other-agent" / "private.pdf"
    target.parent.mkdir()
    target.write_bytes(b"%PDF-other-agent-secret")
    monkeypatch.setattr(files, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(files, "_ALLOWED_ROOT", tmp_path)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.access.dependencies.get_actor", lambda request: SimpleNamespace(user_id=owner))
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    attack = own_root.as_posix() + "/designer/../other-agent/private.pdf"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/files/preview/" + quote(attack, safe=""), headers={"X-Agent-Id": "designer"})
    assert response.status_code == 403
    assert b"%PDF-other-agent-secret" not in response.content


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("case", ["owned", "other_selected_agent", "foreign_admin", "deleted"])
async def test_registered_preview_keeps_owner_access_without_agent_runtime(tmp_path, monkeypatch, method, case):
    import httpx
    from dataclasses import replace
    from qwenpaw.artifacts.service import ArtifactService

    owner = uuid4()
    actor_id = uuid4() if case == "foreign_admin" else owner
    runtime = tmp_path / "user_workspaces" / str(owner) / "designer"
    runtime.mkdir(parents=True)
    source = runtime / "已交付报告.pdf"
    source.write_bytes(b"%PDF-owned-persistent-report")
    repository = SimpleNamespace(
        find_active_by_content=AsyncMock(return_value=None),
        register=AsyncMock(side_effect=lambda record: record),
    )
    record = await ArtifactService(repository=repository, working_dir=tmp_path).publish(
        owner_user_id=owner, agent_key="designer", source=source, conversation_id=uuid4(),
    )
    target = runtime / record.relative_path
    if case == "deleted":
        record = replace(record, status="deleted", deleted_at=datetime.now(UTC))
    repository.list_active = AsyncMock(return_value=[record])
    repository.get = AsyncMock(return_value=record)
    monkeypatch.setattr("qwenpaw.artifacts.repository.PostgresArtifactRepository", lambda **kwargs: repository)
    monkeypatch.setattr(files, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(files, "_ALLOWED_ROOT", tmp_path)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.access.dependencies.get_actor", lambda request: SimpleNamespace(
        user_id=actor_id, platform_role="admin" if case == "foreign_admin" else "member",
    ))
    from fastapi import HTTPException
    runtime_lookup = AsyncMock(side_effect=HTTPException(403, "agent_unavailable"))
    monkeypatch.setattr("qwenpaw.app.agent_context.get_agent_for_request", runtime_lookup)
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/api/files/preview/" + quote(target.as_posix(), safe=""),
            headers={"X-Agent-Id": "other" if case == "other_selected_agent" else "designer"})
    allowed = case in {"owned", "other_selected_agent"}
    assert response.status_code == (200 if allowed else 403)
    if allowed:
        runtime_lookup.assert_not_awaited()
        assert response.content == (source.read_bytes() if method == "GET" else b"")
    else:
        assert b"%PDF-owned-persistent-report" not in response.content
