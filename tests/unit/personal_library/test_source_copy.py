# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.chats.repo.conversation import AttachmentRecord
from qwenpaw.personal_library.service import PersonalLibrarySourceDenied, PersonalLibraryService
from tests.unit.personal_library.test_service import InMemoryRepository


class AttachmentRepository:
    def __init__(self, record: AttachmentRecord | None) -> None:
        self.record = record

    async def get_attachment(self, *, attachment_id, owner_user_id):
        if (
            self.record is not None
            and self.record.id == attachment_id
            and self.record.owner_user_id == owner_user_id
        ):
            return self.record
        return None


@pytest.mark.asyncio
async def test_copy_attachment_preserves_source_and_sets_library_metadata(tmp_path: Path) -> None:
    owner_id = uuid4()
    source = tmp_path / "uploads" / "source.pdf"
    source.parent.mkdir()
    source.write_bytes(b"original attachment")
    attachment = AttachmentRecord(
        id=uuid4(), agent_id=uuid4(), owner_user_id=owner_id,
        storage_key=str(source), original_name="source.pdf", media_type="application/pdf",
        size=source.stat().st_size, content_hash="hash", created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    service = PersonalLibraryService(
        repository=InMemoryRepository(), attachment_repository=AttachmentRepository(attachment), working_dir=tmp_path,
    )

    document = await service.copy_from_attachment(
        owner_user_id=owner_id, attachment_id=attachment.id, destination_path="references/source.pdf",
    )

    assert source.read_bytes() == b"original attachment"
    assert document.relative_path == "references/source.pdf"
    assert (tmp_path / "user_libraries" / str(owner_id) / str(agent_database_id("default")) / "references" / "source.pdf").read_bytes() == source.read_bytes()


@pytest.mark.asyncio
async def test_copy_runtime_file_rejects_path_outside_current_users_runtime_root(tmp_path: Path) -> None:
    owner_id, other_id = uuid4(), uuid4()
    other_file = tmp_path / "user_workspaces" / str(other_id) / "default" / "private.md"
    other_file.parent.mkdir(parents=True)
    other_file.write_text("private", encoding="utf-8")
    service = PersonalLibraryService(repository=InMemoryRepository(), working_dir=tmp_path)

    with pytest.raises(PersonalLibrarySourceDenied):
        await service.copy_from_runtime_file(
            owner_user_id=owner_id, agent_id="default", source_path="../" + str(other_file), destination_path="stolen.md",
        )


@pytest.mark.asyncio
async def test_copy_runtime_file_preserves_current_users_source(tmp_path: Path) -> None:
    owner_id = uuid4()
    source = tmp_path / "user_workspaces" / str(owner_id) / "default" / "notes" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("owned runtime file", encoding="utf-8")
    service = PersonalLibraryService(repository=InMemoryRepository(), working_dir=tmp_path)

    document = await service.copy_from_runtime_file(
        owner_user_id=owner_id, agent_id="default", source_path="notes/source.md", destination_path="references/source.md",
    )

    assert source.read_text(encoding="utf-8") == "owned runtime file"
    assert document.relative_path == "references/source.md"


@pytest.mark.asyncio
async def test_copy_artifact_only_accepts_artifacts_subtree(tmp_path: Path) -> None:
    owner_id = uuid4()
    service = PersonalLibraryService(repository=InMemoryRepository(), working_dir=tmp_path)
    runtime = tmp_path / "user_workspaces" / str(owner_id) / "default"
    (runtime / "output.md").parent.mkdir(parents=True)
    (runtime / "output.md").write_text("not an artifact", encoding="utf-8")

    with pytest.raises(PersonalLibrarySourceDenied):
        await service.copy_from_artifact(
            owner_user_id=owner_id, agent_id="default", source_path="output.md", destination_path="output.md",
        )
