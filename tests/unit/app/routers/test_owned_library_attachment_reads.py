"""用户内容读取不依赖原智能体仍可运行，且不能借此扩大文件权限。"""

from datetime import UTC, datetime
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
import httpx
import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.identity.models import PlatformRole
from qwenpaw.personal_library.service import PersonalLibraryService
from qwenpaw.app.chats.repo import AttachmentRecord
from tests.unit.personal_library.test_service import InMemoryRepository


class OwnedRepository(InMemoryRepository):
    async def get_owned_document(self, *, owner_user_id, document_id):
        item = self.documents.get(document_id)
        return item if item and item.owner_user_id == owner_user_id else None


def actor(user_id, *, admin=False):
    return ActorContext(user_id=user_id, actor_type=ActorType.USER,
                        platform_role=PlatformRole.ADMIN if admin else PlatformRole.MEMBER,
                        admin_mode=False, request_id="owned-library-read")


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["revoked", "disabled", "removed"])
async def test_owner_library_reads_survive_agent_unavailability(tmp_path, monkeypatch, unavailable):
    from qwenpaw.app.routers import personal_library as router
    owner = uuid4()
    repository = OwnedRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await service.create_text(owner_user_id=owner, agent_key="reporter",
        relative_path="旅行计划.md", content="属于本人的旅行计划")
    runtime = AsyncMock(side_effect=HTTPException(403, unavailable))
    monkeypatch.setattr(router, "get_agent_for_request", runtime)
    monkeypatch.setattr(router, "_get_service", lambda: service)
    monkeypatch.setattr(router, "get_actor", lambda _: actor(owner))
    monkeypatch.setattr("qwenpaw.app.owned_content.get_actor", lambda _: actor(owner))
    app = FastAPI()
    app.include_router(router.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-Agent-Id": "reporter"}
        listed = await client.get("/api/console/personal-library/documents", headers=headers)
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [str(document.id)]
        page = await client.get("/api/console/personal-library/documents/page", headers=headers)
        assert page.status_code == 200 and page.json()["total"] == 1
        indexed = await client.get("/api/console/personal-library/index", headers=headers)
        assert indexed.status_code == 200
        # A stable document ID is independent of the currently selected Agent.
        for method in ("GET", "HEAD"):
            downloaded = await client.request(method,
                f"/api/console/personal-library/documents/{document.id}/download",
                headers={"X-Agent-Id": "another-agent"})
            assert downloaded.status_code == 200
            assert downloaded.content == ("属于本人的旅行计划".encode() if method == "GET" else b"")
        read = await client.get(f"/api/console/personal-library/documents/{document.id}/text",
                               headers={"X-Agent-Id": "another-agent"})
        assert read.status_code == 200 and read.json()["content"] == "属于本人的旅行计划"
        runtime.assert_not_awaited()
        denied = await client.post("/api/console/personal-library/documents/text",
                                  headers=headers, json={"path": "new.md", "content": "new"})
        assert denied.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_owned_library_ids_hide_foreign_documents_after_agent_revocation(tmp_path, monkeypatch, admin):
    from qwenpaw.app.routers import personal_library as router
    owner, other = uuid4(), uuid4()
    service = PersonalLibraryService(repository=OwnedRepository(), working_dir=tmp_path)
    document = await service.create_text(owner_user_id=owner, agent_key="reporter",
                                        relative_path="private.md", content="private")
    monkeypatch.setattr(router, "get_agent_for_request", AsyncMock(side_effect=HTTPException(403, "revoked")))
    monkeypatch.setattr(router, "_get_service", lambda: service)
    monkeypatch.setattr(router, "get_actor", lambda _: actor(other, admin=admin))
    monkeypatch.setattr("qwenpaw.app.owned_content.get_actor", lambda _: actor(other, admin=admin))
    app = FastAPI()
    app.include_router(router.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for suffix in ("text", "download"):
            response = await client.get(f"/api/console/personal-library/documents/{document.id}/{suffix}")
            assert response.status_code == 404
            assert b"private" not in response.content


@pytest.mark.asyncio
async def test_attachment_list_remains_owned_without_starting_agent(monkeypatch):
    from qwenpaw.app.routers import attachments as router
    owner = uuid4()
    repository = SimpleNamespace(with_user=lambda _: repository,
                                 list_owned_attachments=AsyncMock(return_value=[]))
    runtime = AsyncMock(side_effect=HTTPException(403, "revoked"))
    monkeypatch.setattr(router, "get_actor", lambda _: actor(owner))
    monkeypatch.setattr("qwenpaw.app.owned_content.get_actor", lambda _: actor(owner))
    monkeypatch.setattr(router, "get_agent_for_request", runtime)
    monkeypatch.setattr(router, "PostgresConversationRepository", lambda **_: repository, raising=False)
    app = FastAPI()
    app.include_router(router.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/console/attachments", headers={"X-Agent-Id": "reporter"})
        assert response.status_code == 200 and response.json() == []
    runtime.assert_not_awaited()
    repository.list_owned_attachments.assert_awaited_once_with(owner_user_id=owner,
        agent_id=agent_database_id("reporter"), lifecycle=None, conversation_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["moved_server", "foreign_path", "foreign_record", "deleted", "traversal"])
async def test_attachment_download_uses_owned_registered_location_after_restart(tmp_path, monkeypatch, case):
    from qwenpaw.app.routers import console as router
    import qwenpaw.app.chats.repo as repositories
    owner, other = uuid4(), uuid4()
    target = tmp_path / "user_workspaces" / str(owner) / "reporter" / "media" / "资料.txt"
    target.parent.mkdir(parents=True)
    target.write_text("owner attachment", encoding="utf-8")
    foreign = tmp_path / "user_workspaces" / str(other) / "reporter" / "media" / "secret.txt"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("foreign secret", encoding="utf-8")
    storage = str(target)
    if case == "moved_server":
        storage = f"C:/previous/server/user_workspaces/{owner}/reporter/media/资料.txt"
    elif case == "foreign_path":
        storage = str(foreign)
    elif case == "traversal":
        storage = f"{target.parent}/../../../../{other}/reporter/media/secret.txt"
    record = AttachmentRecord(id=uuid4(), agent_id=agent_database_id("reporter"),
        owner_user_id=other if case == "foreign_record" else owner,
        storage_key=storage, original_name="资料.txt", media_type="text/plain", size=16,
        lifecycle="deleted" if case == "deleted" else "temporary",
        content_hash="sha256:fixture", created_at=datetime.now(UTC))
    repository = SimpleNamespace(with_user=lambda _: repository, get_attachment=AsyncMock(return_value=record))
    monkeypatch.setattr(repositories, "PostgresConversationRepository", lambda **_: repository)
    monkeypatch.setattr(router, "get_actor", lambda _: actor(owner))
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.app.attachments.service.WORKING_DIR", tmp_path, raising=False)
    app = FastAPI()
    app.include_router(router.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/console/attachments/{record.id}",
                                   headers={"X-Agent-Id": "another-agent"})
        assert response.status_code == (200 if case == "moved_server" else 404)
        if case == "moved_server":
            assert response.text == "owner attachment"
        else:
            assert "foreign secret" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "foreign", "traversal", "scope_mismatch"])
async def test_owned_document_reads_fail_closed_on_invalid_registration(tmp_path, case):
    from qwenpaw.personal_library.service import PersonalLibraryNotFound
    owner = uuid4()
    repository = OwnedRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await service.create_text(owner_user_id=owner, agent_key="reporter",
                                        relative_path="private.md", content="private")
    if case == "missing":
        await service.delete(owner_user_id=owner, agent_key="reporter", document_id=document.id)
    elif case == "foreign":
        repository.get_owned_document = AsyncMock(return_value=replace(document, owner_user_id=uuid4()))
    elif case == "traversal":
        repository.documents[document.id] = replace(document, relative_path="../../../../outside.txt")
    for operation in (service.read_owned_text, service.resolve_owned_download):
        with pytest.raises(PersonalLibraryNotFound):
            await operation(owner_user_id=owner, document_id=document.id,
                            expected_agent_key="other" if case == "scope_mismatch" else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["owner", "foreign_admin", "wrong_scope", "conflicting_header"])
async def test_scoped_library_dependency_keeps_only_owned_reads_without_agent_profile(tmp_path, monkeypatch, case):
    from qwenpaw.app.routers import agent_scoped, personal_library as router
    owner, other = uuid4(), uuid4()
    current_actor = actor(other, admin=True) if case == "foreign_admin" else actor(owner)
    service = PersonalLibraryService(repository=OwnedRepository(), working_dir=tmp_path)
    document = await service.create_text(owner_user_id=owner, agent_key="retired-agent",
                                        relative_path="notes.md", content="personal history")
    runtime = AsyncMock(side_effect=HTTPException(403, "agent_removed"))
    monkeypatch.setattr(router, "get_agent_for_request", runtime)
    monkeypatch.setattr(router, "_get_service", lambda: service)
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_scoped, "load_config", lambda: SimpleNamespace(agents=SimpleNamespace(profiles={})))
    app = FastAPI()

    @app.middleware("http")
    async def trusted_identity(request, call_next):
        request.state.actor = current_actor
        return await call_next(request)

    app.include_router(router.router, prefix="/api/agents/{agentId}",
                       dependencies=[Depends(agent_scoped.require_agent_scoped_access)])
    selected = "another-agent" if case == "wrong_scope" else "retired-agent"
    headers = {"X-Agent-Id": "another-agent"} if case == "conflicting_header" else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/agents/{selected}/console/personal-library/documents/{document.id}/download", headers=headers)
        assert response.status_code == {"owner": 200, "foreign_admin": 404,
                                        "wrong_scope": 404, "conflicting_header": 403}[case]
        if case == "owner":
            assert response.text == "personal history"
        else:
            assert "personal history" not in response.text
        denied = await client.post(f"/api/agents/{selected}/console/personal-library/index/rebuild",
                                   json={"document_ids": [str(document.id)]})
        assert denied.status_code == 403
    runtime.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["moved_server", "foreign_path", "foreign_record"])
async def test_attachment_import_and_runtime_refs_share_owned_path_validation(tmp_path, monkeypatch, case):
    from starlette.requests import Request
    from qwenpaw.app.routers import console as router
    from qwenpaw.personal_library.service import PersonalLibraryNotFound
    owner, other = uuid4(), uuid4()
    source = tmp_path / "user_workspaces" / str(owner) / "reporter" / "media" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("own reference", encoding="utf-8")
    foreign = tmp_path / "user_workspaces" / str(other) / "reporter" / "media" / "secret.txt"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("foreign secret", encoding="utf-8")
    storage = f"C:/old-data/user_workspaces/{owner}/reporter/media/source.txt"
    if case != "moved_server":
        storage = str(foreign)
    record = AttachmentRecord(id=uuid4(), owner_user_id=other if case == "foreign_record" else owner,
        agent_id=agent_database_id("reporter"), storage_key=storage, original_name="source.txt",
        media_type="text/plain", size=13, content_hash="test", created_at=datetime.now(UTC))
    repository = SimpleNamespace(with_user=lambda _: repository, get_attachment=AsyncMock(return_value=record))
    service = PersonalLibraryService(repository=OwnedRepository(), attachment_repository=repository, working_dir=tmp_path)
    monkeypatch.setattr("qwenpaw.app.attachments.service.WORKING_DIR", tmp_path)
    monkeypatch.setattr(router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(router, "get_actor", lambda _: actor(owner))
    request = Request({"type": "http", "headers": []})
    workspace = SimpleNamespace(agent_id="reporter", chat_manager=SimpleNamespace(conversation_repository=repository))
    payload = {"content_parts": [{"type": "file", "file_url": f"/api/console/attachments/{record.id}"}]}
    if case == "moved_server":
        copied = await service.copy_from_attachment(owner_user_id=owner, attachment_id=record.id,
            agent_key="reporter", destination_path="source.txt")
        assert (await service.read_owned_text(owner_user_id=owner, document_id=copied.id)).content == "own reference"
        await router._resolve_console_attachment_refs(request, workspace, payload, conversation_id=str(uuid4()))
        assert payload["content_parts"][0]["file_url"] == str(source.resolve())
        assert source.read_text(encoding="utf-8") == "own reference"
    else:
        with pytest.raises(PersonalLibraryNotFound):
            await service.copy_from_attachment(owner_user_id=owner, attachment_id=record.id,
                agent_key="reporter", destination_path="source.txt")
        with pytest.raises(HTTPException) as denied:
            await router._resolve_console_attachment_refs(request, workspace, payload, conversation_id=str(uuid4()))
        assert denied.value.status_code == 404
