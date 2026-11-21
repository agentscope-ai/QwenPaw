from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from qwenpaw.app.routers import artifacts
from qwenpaw.artifacts.service import ArtifactService
from qwenpaw.workspaces.resolver import WorkspaceKind, WorkspaceResolver


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("case", ["owned", "new_browser", "foreign", "foreign_admin", "different_current_agent", "revoked", "disabled", "deleted"])
async def test_delivered_chinese_pdf_keeps_owner_access_independent_of_agent_use(tmp_path, monkeypatch, method, case):
    """本人已登记文件不随当前 Agent/运行授权变化失效，仍拒绝他人和已删除内容。"""
    owner = uuid4()
    resolver = WorkspaceResolver(working_dir=tmp_path)
    root = resolver.ensure_standard_directories(resolver.resolve(
        kind=WorkspaceKind.USER_RUNTIME, resource_id="reporter", actor_user_id=owner,
    ))
    source = root / "2026-09-17_防水行业新闻简报.pdf"
    source.write_bytes(b"%PDF-owned-news-brief")
    repository = SimpleNamespace(
        find_active_by_content=AsyncMock(return_value=None),
        register=AsyncMock(side_effect=lambda record: record),
    )
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    record = await service.publish(owner_user_id=owner, agent_key="reporter", source=source, conversation_id=uuid4())
    if case == "deleted":
        record = replace(record, status="deleted")
    repository.get = AsyncMock(side_effect=lambda owner_user_id, artifact_id: record if owner_user_id == owner and artifact_id == record.id else None)
    monkeypatch.setattr(artifacts, "get_actor", lambda request: SimpleNamespace(
        user_id=uuid4() if case in {"foreign", "foreign_admin"} else owner,
        platform_role="admin" if case == "foreign_admin" else "member",
    ))
    # A fresh service object per request simulates reopening the browser/server;
    # only the persisted ownership record and on-disk snapshot are carried over.
    monkeypatch.setattr(artifacts, "ArtifactService", lambda **kwargs: ArtifactService(repository=repository, working_dir=tmp_path))
    monkeypatch.setattr(artifacts, "PostgresArtifactRepository", lambda **kwargs: repository)

    async def agent_scope(request):
        if case in {"revoked", "disabled"}:
            raise HTTPException(403, "forbidden")
        return SimpleNamespace(agent_id=request.headers.get("X-Agent-Id") or "default")

    monkeypatch.setattr(artifacts, "get_agent_for_request", agent_scope)
    app = FastAPI()
    app.include_router(artifacts.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = {} if case == "new_browser" else {"X-Agent-Id": "other-agent" if case == "different_current_agent" else "reporter"}
        response = await client.request(method, f"/api/console/artifacts/{record.id}/download", headers=headers)
        if method == "GET":
            ranged = await client.get(f"/api/console/artifacts/{record.id}/download", headers={
                **headers, "Range": "bytes=0-3",
            })
            accessible = case not in {"foreign", "foreign_admin", "deleted"}
            assert ranged.status_code == (206 if accessible else 404)
            if accessible:
                assert ranged.content == b"%PDF"
            else:
                assert b"%PDF" not in ranged.content
    expected = 200 if case not in {"foreign", "foreign_admin", "deleted"} else 404
    assert response.status_code == expected
    if expected == 200:
        assert "application/pdf" in response.headers["content-type"]
        assert "filename*=utf-8''2026-09-17_" in response.headers["content-disposition"]
        assert response.content == (source.read_bytes() if method == "GET" else b"")
    elif method == "GET":
        assert b"%PDF-owned-news-brief" not in response.content


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["foreign_record", "wrong_registered_agent", "path_traversal", "missing_snapshot", "symlink_snapshot"])
async def test_persistent_owner_download_still_requires_registered_private_snapshot(tmp_path, case):
    owner = uuid4()
    resolver = WorkspaceResolver(working_dir=tmp_path)
    root = resolver.ensure_standard_directories(resolver.resolve(
        kind=WorkspaceKind.USER_RUNTIME, resource_id="reporter", actor_user_id=owner,
    ))
    source = root / "简报.pdf"
    source.write_bytes(b"%PDF-owner-archive")
    repository = SimpleNamespace(
        find_active_by_content=AsyncMock(return_value=None),
        register=AsyncMock(side_effect=lambda record: record),
    )
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    record = await service.publish(owner_user_id=owner, agent_key="reporter", source=source, conversation_id=uuid4())
    if case == "foreign_record":
        record = replace(record, owner_user_id=uuid4())
    elif case == "wrong_registered_agent":
        record = replace(record, agent_id=uuid4())
    elif case == "path_traversal":
        record = replace(record, relative_path="../../outside.pdf")
    elif case == "missing_snapshot":
        (root / record.relative_path).unlink()
    else:
        snapshot = root / record.relative_path
        snapshot.unlink()
        try:
            snapshot.symlink_to(source)
        except OSError:
            pytest.skip("The platform does not permit symlink creation")
    # Even an overbroad repository response must not grant foreign ownership.
    repository.get = AsyncMock(return_value=record)
    from qwenpaw.artifacts.service import ArtifactNotFound
    with pytest.raises(ArtifactNotFound):
        await ArtifactService(repository=repository, working_dir=tmp_path).download_owned_path(
            owner_user_id=owner, artifact_id=record.id,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["revoked_owner", "foreign_admin", "invalid_agent"])
async def test_owner_can_list_and_delete_historical_artifacts_without_agent_use(tmp_path, monkeypatch, case):
    owner = uuid4()
    actor_id = uuid4() if case == "foreign_admin" else owner
    resolver = WorkspaceResolver(working_dir=tmp_path)
    root = resolver.ensure_standard_directories(resolver.resolve(
        kind=WorkspaceKind.USER_RUNTIME, resource_id="reporter", actor_user_id=owner,
    ))
    source = root / "历史简报.pdf"
    source.write_bytes(b"%PDF-persistent-owner")
    repository = SimpleNamespace(
        find_active_by_content=AsyncMock(return_value=None),
        register=AsyncMock(side_effect=lambda value: value),
    )
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    record = await service.publish(owner_user_id=owner, agent_key="reporter", source=source, conversation_id=uuid4())
    stored = {"record": record}
    # Service must filter even if a faulty repository returns another owner's row.
    repository.list_active = AsyncMock(side_effect=lambda **kwargs: [stored["record"]])
    repository.get = AsyncMock(side_effect=lambda **kwargs: stored["record"])

    async def mark_deleted(**kwargs):
        assert kwargs["owner_user_id"] == owner
        stored["record"] = replace(stored["record"], status="deleted", deleted_at=kwargs["deleted_at"])
        return stored["record"]

    repository.mark_deleted = AsyncMock(side_effect=mark_deleted)
    forbidden_agent_runtime = AsyncMock(side_effect=HTTPException(403, "agent_revoked"))
    monkeypatch.setattr(artifacts, "get_agent_for_request", forbidden_agent_runtime)
    monkeypatch.setattr(artifacts, "get_actor", lambda request: SimpleNamespace(user_id=actor_id, platform_role="admin" if case == "foreign_admin" else "member"))
    monkeypatch.setattr(artifacts, "ArtifactService", lambda **kwargs: ArtifactService(repository=repository, working_dir=tmp_path))
    monkeypatch.setattr(artifacts, "PostgresArtifactRepository", lambda **kwargs: repository)
    app = FastAPI()
    app.include_router(artifacts.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-Agent-Id": "../other" if case == "invalid_agent" else "reporter"}
        listed = await client.get("/api/console/artifacts", headers=headers)
        if case == "invalid_agent":
            assert listed.status_code == 400
            repository.list_active.assert_not_awaited()
            return
        assert listed.status_code == 200
        if case == "foreign_admin":
            assert listed.json() == []
        else:
            assert [item["id"] for item in listed.json()] == [str(record.id)]
        deleted = await client.delete(f"/api/console/artifacts/{record.id}", headers={"X-Agent-Id": "another-current-agent"})
        assert deleted.status_code == (404 if case == "foreign_admin" else 200)
        if case == "foreign_admin":
            repository.mark_deleted.assert_not_awaited()
            assert (root / record.relative_path).is_file()
        else:
            assert deleted.json()["status"] == "deleted"
            assert not (root / record.relative_path).exists()
            reread = await client.get(f"/api/console/artifacts/{record.id}/download")
            assert reread.status_code == 404
    forbidden_agent_runtime.assert_not_awaited()
