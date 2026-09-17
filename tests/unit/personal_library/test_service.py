# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qwenpaw.personal_library.models import PersonalLibraryDocument
from qwenpaw.personal_library.service import PersonalLibraryNotFound, PersonalLibraryService
from qwenpaw.access.agent_repository import agent_database_id


class InMemoryRepository:
    def __init__(self) -> None:
        self.documents: dict[UUID, PersonalLibraryDocument] = {}

    async def get_document(self, *, owner_user_id: UUID, agent_id: UUID, document_id: UUID):
        document = self.documents.get(document_id)
        return document if document and document.owner_user_id == owner_user_id and document.agent_id == agent_id else None

    async def get_by_path(self, *, owner_user_id: UUID, agent_id: UUID, relative_path: str):
        return next(
            (item for item in self.documents.values() if item.owner_user_id == owner_user_id and item.agent_id == agent_id and item.relative_path == relative_path),
            None,
        )

    async def list_documents(self, *, owner_user_id: UUID, agent_id: UUID):
        return [
            item
            for item in self.documents.values()
            if item.owner_user_id == owner_user_id and item.agent_id == agent_id
        ]

    async def save_document(self, document: PersonalLibraryDocument):
        self.documents[document.id] = document
        return document

    async def delete_document(self, *, owner_user_id: UUID, agent_id: UUID, document_id: UUID):
        document = await self.get_document(owner_user_id=owner_user_id, agent_id=agent_id, document_id=document_id)
        if document is None:
            return False
        del self.documents[document_id]
        return True


@pytest.mark.asyncio
async def test_create_and_read_own_text_document(tmp_path: Path) -> None:
    repository = InMemoryRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    user_id = uuid4()

    created = await service.create_text(
        owner_user_id=user_id,
        relative_path="notes/hello.md",
        content="# hello",
    )
    content = await service.read_text(owner_user_id=user_id, document_id=created.id)

    assert created.relative_path == "notes/hello.md"
    assert content.content == "# hello"
    assert (tmp_path / "user_libraries" / str(user_id) / str(agent_database_id("default")) / "notes" / "hello.md").is_file()


@pytest.mark.asyncio
async def test_upload_stores_binary_document_in_current_users_library(tmp_path: Path) -> None:
    repository = InMemoryRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    user_id = uuid4()

    created = await service.save_upload(
        owner_user_id=user_id,
        filename="reference.pdf",
        content=b"%PDF-test",
        media_type="application/pdf",
    )

    assert created.relative_path == "reference.pdf"
    assert created.media_type == "application/pdf"
    assert (tmp_path / "user_libraries" / str(user_id) / str(agent_database_id("default")) / "reference.pdf").read_bytes() == b"%PDF-test"


@pytest.mark.asyncio
async def test_other_user_cannot_read_document(tmp_path: Path) -> None:
    repository = InMemoryRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    owner_id, other_id = uuid4(), uuid4()
    created = await service.create_text(owner_user_id=owner_id, relative_path="private.md", content="owner only")

    with pytest.raises(PersonalLibraryNotFound):
        await service.read_text(owner_user_id=other_id, document_id=created.id)


@pytest.mark.asyncio
async def test_same_user_has_independent_libraries_for_each_agent(tmp_path: Path) -> None:
    repository = InMemoryRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    owner_id = uuid4()
    first = await service.create_text(
        owner_user_id=owner_id, agent_key="agent-a", relative_path="note.md", content="agent a",
    )
    second = await service.create_text(
        owner_user_id=owner_id, agent_key="agent-b", relative_path="note.md", content="agent b",
    )

    assert first.id != second.id
    assert (await service.read_text(owner_user_id=owner_id, agent_key="agent-a", document_id=first.id)).content == "agent a"
    assert (await service.read_text(owner_user_id=owner_id, agent_key="agent-b", document_id=second.id)).content == "agent b"
    with pytest.raises(PersonalLibraryNotFound):
        await service.read_text(owner_user_id=owner_id, agent_key="agent-b", document_id=first.id)


@pytest.mark.asyncio
async def test_text_read_preserves_utf8_boundaries(tmp_path: Path) -> None:
    repository = InMemoryRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    user_id = uuid4()
    created = await service.create_text(
        owner_user_id=user_id,
        relative_path="notes/chinese.md",
        content="你好，世界",
    )

    content = await service.read_text(
        owner_user_id=user_id,
        document_id=created.id,
        offset=1,
        limit=4,
    )

    assert content.content == "好"
    assert content.offset == 3
    assert content.next_offset == 6


@pytest.mark.asyncio
async def test_list_documents_only_returns_current_users_direct_directory(
    tmp_path: Path,
) -> None:
    repository = InMemoryRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    owner_id, other_id = uuid4(), uuid4()
    await service.create_text(
        owner_user_id=owner_id,
        relative_path="notes/one.md",
        content="one",
    )
    await service.create_text(
        owner_user_id=owner_id,
        relative_path="notes/deep/two.md",
        content="two",
    )
    await service.create_text(
        owner_user_id=other_id,
        relative_path="notes/other.md",
        content="other",
    )

    documents = await service.list_directory(owner_user_id=owner_id, path="notes")

    assert [document.relative_path for document in documents] == ["notes/one.md"]


@pytest.mark.asyncio
async def test_list_documents_in_root_includes_nested_files(tmp_path: Path) -> None:
    repository = InMemoryRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    user_id = uuid4()
    await service.create_text(
        owner_user_id=user_id,
        relative_path="root-note.md",
        content="root",
    )
    await service.create_text(
        owner_user_id=user_id,
        relative_path="notes/nested.md",
        content="nested",
    )

    documents = await service.list_directory(owner_user_id=user_id)

    assert [document.relative_path for document in documents] == ["notes/nested.md", "root-note.md"]


@pytest.mark.asyncio
async def test_move_and_delete_own_document(tmp_path: Path) -> None:
    repository = InMemoryRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    user_id = uuid4()
    created = await service.create_text(
        owner_user_id=user_id,
        relative_path="draft.md",
        content="draft",
    )

    moved = await service.move(
        owner_user_id=user_id,
        document_id=created.id,
        destination_path="notes/final.md",
    )
    await service.delete(owner_user_id=user_id, document_id=moved.id)

    root = tmp_path / "user_libraries" / str(user_id) / str(agent_database_id("default"))
    assert moved.relative_path == "notes/final.md"
    assert not (root / "draft.md").exists()
    assert not (root / "notes" / "final.md").exists()
