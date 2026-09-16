# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from io import BytesIO
from uuid import UUID, uuid4
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.datastructures import UploadFile

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole
from qwenpaw.personal_library.service import PersonalLibraryService
from tests.unit.personal_library.test_service import InMemoryRepository


def _request(user_id: UUID) -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="personal-library-router-test",
    )
    return request


async def _workspace(_request):
    return SimpleNamespace(agent_id="default")


@pytest.mark.asyncio
async def test_router_creates_and_reads_own_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.app.routers import personal_library as router

    user_id = uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(),
        working_dir=tmp_path,
    )
    monkeypatch.setattr(router, "_get_service", lambda: service)
    monkeypatch.setattr(router, "get_agent_for_request", _workspace)

    created = await router.create_text_document(
        request=_request(user_id),
        payload=router.CreateTextDocument(path="notes/hello.md", content="# hello"),
    )
    loaded = await router.read_text_document(
        request=_request(user_id),
        document_id=created.id,
        offset=0,
        limit=65_536,
    )

    assert created.relative_path == "notes/hello.md"
    assert loaded.content == "# hello"


@pytest.mark.asyncio
async def test_router_hides_another_users_document(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.app.routers import personal_library as router

    owner_id, other_id = uuid4(), uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(),
        working_dir=tmp_path,
    )
    monkeypatch.setattr(router, "_get_service", lambda: service)
    monkeypatch.setattr(router, "get_agent_for_request", _workspace)
    created = await router.create_text_document(
        request=_request(owner_id),
        payload=router.CreateTextDocument(path="private.md", content="owner only"),
    )

    with pytest.raises(HTTPException) as raised:
        await router.read_text_document(
                request=_request(other_id),
                document_id=created.id,
                offset=0,
                limit=65_536,
        )

    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_router_upload_binds_document_to_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.app.routers import personal_library as router

    owner_id, other_id = uuid4(), uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(),
        working_dir=tmp_path,
    )
    monkeypatch.setattr(router, "_get_service", lambda: service)
    monkeypatch.setattr(router, "get_agent_for_request", _workspace)

    created = await router.upload_document(
        request=_request(owner_id),
        file=UploadFile(filename="guide.txt", file=BytesIO(b"owner only")),
    )

    assert created.name == "guide.txt"
    with pytest.raises(HTTPException) as raised:
        await router.read_text_document(
            request=_request(other_id),
            document_id=created.id,
            offset=0,
            limit=65_536,
        )
    assert raised.value.status_code == 404
