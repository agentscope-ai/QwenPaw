# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.routers import console
from qwenpaw.identity.models import PlatformRole
from qwenpaw.personal_library.service import PersonalLibraryService
from tests.unit.personal_library.test_runtime_access import GrantRepository


def _request(user_id) -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="personal-library-reference-test",
    )
    return request


@pytest.mark.asyncio
@pytest.mark.parametrize("refs", [{}, "", None, False])
async def test_rejects_malformed_unified_reference_values(monkeypatch, refs):
    payload = {"meta": {"request_context": {"file_references": refs}}}
    with pytest.raises(HTTPException) as caught:
        await console._resolve_personal_library_references(_request(uuid4()), SimpleNamespace(agent_id="default"), payload)
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_deleted_attachment_cannot_be_replayed_into_chat(monkeypatch, tmp_path):
    owner, chat, identifier = uuid4(), uuid4(), uuid4()
    path = tmp_path / "deleted.txt"
    path.write_text("retained bytes", encoding="utf-8")
    record = SimpleNamespace(id=identifier, owner_user_id=owner, agent_id=agent_database_id("default"),
        conversation_id=chat, lifecycle="deleted", storage_key=str(path))
    class Repository:
        def with_user(self, user):
            return self
        async def get_attachment(self, **kwargs):
            return record
    workspace = SimpleNamespace(agent_id="default", chat_manager=SimpleNamespace(conversation_repository=Repository()))
    payload = {"content_parts": [{"type":"file", "file_url":f"/api/console/attachments/{identifier}"}]}
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    with pytest.raises(HTTPException) as caught:
        await console._resolve_console_attachment_refs(_request(owner), workspace, payload, conversation_id=str(chat))
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_plain_filename_prompt_resolves_own_authorized_document(monkeypatch, tmp_path):
    owner = uuid4()
    repository = GrantRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await service.create_text(owner_user_id=owner, relative_path="AI写作需求文档.md", content="用户的真实需求")
    await repository.set_grant(owner_user_id=owner, agent_id=agent_database_id("default"), enabled=True)
    monkeypatch.setattr(console, "_personal_library_service", lambda: service)
    payload = {"content_parts": [{"type": "text", "text": "帮我看下我这个 ai 写作需求文档 有没有需要优化的地方"}]}
    await console._resolve_personal_library_references(_request(owner), SimpleNamespace(agent_id="default"), payload)
    assert payload["meta"]["request_context"]["personal_library_references"][0]["document_id"] == str(document.id)


@pytest.mark.asyncio
async def test_plain_filename_does_not_resolve_ambiguous_or_ungranted_documents(monkeypatch, tmp_path):
    owner = uuid4()
    repository = GrantRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    for path in ["a/AI写作需求文档.md", "b/AI写作需求文档.md"]:
        await service.create_text(owner_user_id=owner, relative_path=path, content="私有")
    monkeypatch.setattr(console, "_personal_library_service", lambda: service)
    for enabled in [False, True]:
        await repository.set_grant(owner_user_id=owner, agent_id=agent_database_id("default"), enabled=enabled)
        payload = {"content_parts": [{"type": "text", "text": "帮我优化AI写作需求文档"}]}
        await console._resolve_personal_library_references(_request(owner), SimpleNamespace(agent_id="default"), payload)
        assert not payload["meta"]["request_context"].get("personal_library_references")


@pytest.mark.asyncio
async def test_resolves_only_authenticated_users_selected_document(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owner_id = uuid4()
    repository = GrantRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await service.create_text(
        owner_user_id=owner_id,
        relative_path="AI写作需求文档.md",
        content="只属于当前用户的验收正文",
    )
    await repository.set_grant(
        owner_user_id=owner_id,
        agent_id=agent_database_id("default"),
        enabled=True,
    )
    monkeypatch.setattr(console, "_personal_library_service", lambda: service)
    payload = {
        "meta": {
            "request_context": {
                "personal_library_document_ids": [str(document.id)],
                "personal_library_references": [{"content": "客户端伪造内容"}],
            },
        },
    }

    await console._resolve_personal_library_references(
        _request(owner_id),
        SimpleNamespace(agent_id="default"),
        payload,
    )

    context = payload["meta"]["request_context"]
    assert "personal_library_document_ids" not in context
    assert context["personal_library_references"] == [
        {
            "document_id": str(document.id),
            "name": "AI写作需求文档.md",
            "relative_path": "AI写作需求文档.md",
            "content": "只属于当前用户的验收正文",
            "truncated": False,
        },
    ]


@pytest.mark.asyncio
async def test_rejects_reference_owned_by_another_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owner_id, other_id = uuid4(), uuid4()
    repository = GrantRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await service.create_text(
        owner_user_id=owner_id,
        relative_path="private.md",
        content="owner only",
    )
    await repository.set_grant(
        owner_user_id=other_id,
        agent_id=agent_database_id("default"),
        enabled=True,
    )
    monkeypatch.setattr(console, "_personal_library_service", lambda: service)
    payload = {
        "meta": {
            "request_context": {
                "personal_library_document_ids": [str(document.id)],
            },
        },
    }

    with pytest.raises(HTTPException) as raised:
        await console._resolve_personal_library_references(
            _request(other_id),
            SimpleNamespace(agent_id="default"),
            payload,
        )

    assert raised.value.status_code == 404
    assert raised.value.detail == "personal_library_reference_unavailable"
