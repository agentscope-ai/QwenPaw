from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from qwenpaw.artifacts.service import ArtifactNotFound, ArtifactService, ArtifactSourceDenied
from qwenpaw.workspaces.resolver import WorkspaceKind, WorkspaceResolver

USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")


class Repository:
    def __init__(self) -> None:
        self.items = {}

    async def register(self, artifact):
        self.items[artifact.id] = artifact
        return artifact

    async def find_active_by_content(self, *, owner_user_id, agent_id, conversation_id, sha256):
        return next(
            (
                item
                for item in self.items.values()
                if item.owner_user_id == owner_user_id
                and item.agent_id == agent_id
                and item.conversation_id == conversation_id
                and item.sha256 == sha256
                and item.status == "active"
            ),
            None,
        )

    async def list_active(self, *, owner_user_id, agent_id):
        return [item for item in self.items.values() if item.owner_user_id == owner_user_id and item.agent_id == agent_id and item.status == "active"]

    async def find_deleted_by_content(self, *, owner_user_id, agent_id, conversation_id, sha256):
        return next((item for item in self.items.values() if item.owner_user_id == owner_user_id and item.agent_id == agent_id and item.conversation_id == conversation_id and item.sha256 == sha256 and item.status == "deleted"), None)

    async def get(self, *, owner_user_id, artifact_id):
        item = self.items.get(artifact_id)
        return item if item and item.owner_user_id == owner_user_id else None

    async def mark_deleted(self, *, owner_user_id, artifact_id, deleted_at):
        item = await self.get(owner_user_id=owner_user_id, artifact_id=artifact_id)
        if item is None:
            return None
        updated = item.__class__(**{**{field: getattr(item, field) for field in item.__dataclass_fields__}, "status": "deleted", "deleted_at": deleted_at})
        self.items[item.id] = updated
        return updated


@pytest.mark.asyncio
async def test_user_artifact_is_copied_to_private_runtime_and_other_user_cannot_read(tmp_path: Path) -> None:
    repository = Repository()
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    root = WorkspaceResolver(working_dir=tmp_path).resolve(kind=WorkspaceKind.USER_RUNTIME, resource_id="public-agent", actor_user_id=USER_A)
    source_root = WorkspaceResolver(working_dir=tmp_path).ensure_standard_directories(root)
    source = source_root / "report.md"
    source.write_text("private", encoding="utf-8")

    artifact = await service.publish(owner_user_id=USER_A, agent_key="public-agent", source=source)

    _, path = await service.download_path(owner_user_id=USER_A, agent_key="public-agent", artifact_id=artifact.id)
    assert path.read_text(encoding="utf-8") == "private"
    assert "user_workspaces" in artifact.relative_path or path.is_relative_to(source_root)
    with pytest.raises(ArtifactNotFound):
        await service.download_path(owner_user_id=USER_B, agent_key="public-agent", artifact_id=artifact.id)


@pytest.mark.asyncio
async def test_delete_marks_tombstone_and_removes_private_file(tmp_path: Path) -> None:
    repository = Repository()
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    root = WorkspaceResolver(working_dir=tmp_path).resolve(kind=WorkspaceKind.USER_RUNTIME, resource_id="agent-a", actor_user_id=USER_A)
    source_root = WorkspaceResolver(working_dir=tmp_path).ensure_standard_directories(root)
    source = source_root / "report.md"
    source.write_text("private", encoding="utf-8")
    artifact = await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source)
    _, path = await service.download_path(owner_user_id=USER_A, agent_key="agent-a", artifact_id=artifact.id)

    deleted = await service.delete(owner_user_id=USER_A, agent_key="agent-a", artifact_id=artifact.id)

    assert deleted.status == "deleted"
    assert not path.exists()
    with pytest.raises(ArtifactNotFound):
        await service.download_path(owner_user_id=USER_A, agent_key="agent-a", artifact_id=artifact.id)


def test_standard_runtime_directory_names_are_english(tmp_path: Path) -> None:
    root = WorkspaceResolver(working_dir=tmp_path).resolve(
        kind=WorkspaceKind.USER_RUNTIME, resource_id="agent-a", actor_user_id=USER_A,
    )
    path = WorkspaceResolver(working_dir=tmp_path).ensure_standard_directories(root)

    assert (path / "media").is_dir()
    assert (path / "artifacts").is_dir()
    assert not (path / "资料").exists()


@pytest.mark.asyncio
async def test_publish_is_idempotent_for_same_conversation_and_content(tmp_path: Path) -> None:
    repository = Repository()
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    root = WorkspaceResolver(working_dir=tmp_path).resolve(
        kind=WorkspaceKind.USER_RUNTIME,
        resource_id="agent-a",
        actor_user_id=USER_A,
    )
    source_root = WorkspaceResolver(working_dir=tmp_path).ensure_standard_directories(root)
    source = source_root / "report.pdf"
    source.write_bytes(b"same report")
    conversation_id = UUID("33333333-3333-4333-8333-333333333333")

    first = await service.publish(
        owner_user_id=USER_A,
        agent_key="agent-a",
        source=source,
        conversation_id=conversation_id,
    )
    second = await service.publish(
        owner_user_id=USER_A,
        agent_key="agent-a",
        source=source,
        conversation_id=conversation_id,
    )

    assert second.id == first.id
    assert len(repository.items) == 1


@pytest.mark.asyncio
async def test_publish_rejects_link_ancestor_without_resolving_it(tmp_path, monkeypatch):
    service = ArtifactService(repository=Repository(), working_dir=tmp_path)
    source = service._runtime_root(USER_A, "agent-a") / "report.md"
    source.write_bytes(b"report")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == source or original(path))
    with pytest.raises(ArtifactSourceDenied, match="symlink"):
        await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source)


@pytest.mark.asyncio
async def test_trusted_root_cannot_authorize_another_private_user(tmp_path):
    service = ArtifactService(repository=Repository(), working_dir=tmp_path)
    source = service._runtime_root(USER_B, "agent-a") / "secret.md"
    source.write_text("secret", encoding="utf-8")
    with pytest.raises(ArtifactSourceDenied):
        await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source, trusted_source_roots=(tmp_path,))


@pytest.mark.asyncio
@pytest.mark.parametrize("library_user,library_agent", [(USER_B, "agent-a"), (USER_A, "agent-b")])
async def test_trusted_root_cannot_authorize_another_private_library(tmp_path, library_user, library_agent):
    from qwenpaw.access.agent_repository import agent_database_id
    service = ArtifactService(repository=Repository(), working_dir=tmp_path)
    source = tmp_path / "user_libraries" / str(library_user) / str(agent_database_id(library_agent)) / "secret.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"private library")
    with pytest.raises(ArtifactSourceDenied, match="private_source"):
        await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source, trusted_source_roots=(tmp_path,))


@pytest.mark.asyncio
async def test_own_private_library_still_requires_trusted_source_root(tmp_path):
    from qwenpaw.access.agent_repository import agent_database_id
    service = ArtifactService(repository=Repository(), working_dir=tmp_path)
    source = tmp_path / "user_libraries" / str(USER_A) / str(agent_database_id("agent-a")) / "report.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"own library")
    with pytest.raises(ArtifactSourceDenied):
        await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source)
    artifact = await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source, trusted_source_roots=(source.parent,))
    assert artifact.owner_user_id == USER_A


@pytest.mark.asyncio
async def test_collect_session_is_scoped_idempotent_and_retryable(tmp_path):
    repository = Repository()
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    conversation = UUID("33333333-3333-4333-8333-333333333333")
    folder = service._runtime_root(USER_A, "agent-a") / "artifacts" / str(conversation)
    folder.mkdir()
    for name in ("report.md", "image.png", "doc.pdf"):
        (folder / name).write_bytes(name.encode())
    (folder / "tmp").mkdir()
    (folder / "tmp" / "intermediate.pdf").write_bytes(b"intermediate")
    (folder / "unfinished.part").write_bytes(b"partial")
    original_register = repository.register
    async def fail_pdf(artifact):
        if artifact.original_name == "doc.pdf":
            raise RuntimeError("database unavailable")
        return await original_register(artifact)
    repository.register = fail_pdf
    first = await service.collect_session(owner_user_id=USER_A, agent_key="agent-a", conversation_id=conversation)
    assert len(first.artifacts) == 2 and len(first.failures) == 1
    assert (folder / "doc.pdf").exists()
    repository.register = original_register
    second = await service.collect_session(owner_user_id=USER_A, agent_key="agent-a", conversation_id=conversation)
    assert len(second.artifacts) == 3 and not second.failures
    assert len(repository.items) == 3


@pytest.mark.asyncio
async def test_publish_registration_failure_keeps_archive_for_retry(tmp_path):
    repository = Repository()
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    source = service._runtime_root(USER_A, "agent-a") / "report.md"
    source.write_bytes(b"report")
    async def fail(artifact):
        raise RuntimeError("offline")
    repository.register = fail
    with pytest.raises(RuntimeError):
        await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source)
    assert source.exists()
    assert list((source.parent / "artifacts").rglob("*.md"))


@pytest.mark.asyncio
async def test_deleting_one_conversation_does_not_break_another(tmp_path):
    service = ArtifactService(repository=Repository(), working_dir=tmp_path)
    source = service._runtime_root(USER_A, "agent-a") / "report.md"
    source.write_bytes(b"report")
    first = await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source, conversation_id=USER_A)
    second = await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source, conversation_id=USER_B)
    await service.delete(owner_user_id=USER_A, agent_key="agent-a", artifact_id=first.id)
    _, path = await service.download_path(owner_user_id=USER_A, agent_key="agent-a", artifact_id=second.id)
    assert path.read_bytes() == b"report"


@pytest.mark.asyncio
async def test_publish_rejects_symlink_before_resolution(tmp_path):
    service = ArtifactService(repository=Repository(), working_dir=tmp_path)
    root = service._runtime_root(USER_A, "agent-a")
    source = root / "report.md"
    source.write_bytes(b"report")
    link = root / "linked.md"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("Windows symlink permission unavailable")
    with pytest.raises(ArtifactSourceDenied):
        await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=link)


@pytest.mark.asyncio
async def test_wrong_agent_and_user_cannot_delete(tmp_path):
    service = ArtifactService(repository=Repository(), working_dir=tmp_path)
    source = service._runtime_root(USER_A, "agent-a") / "report.md"
    source.write_bytes(b"report")
    artifact = await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source)
    for user, agent in ((USER_B, "agent-a"), (USER_A, "agent-b")):
        with pytest.raises(ArtifactNotFound):
            await service.delete(owner_user_id=user, agent_key=agent, artifact_id=artifact.id)
    _, path = await service.download_path(owner_user_id=USER_A, agent_key="agent-a", artifact_id=artifact.id)
    assert path.exists()


@pytest.mark.asyncio
async def test_collector_does_not_resurrect_deleted_artifact(tmp_path):
    repository = Repository()
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    folder = service._runtime_root(USER_A, "agent-a") / "artifacts" / str(USER_A)
    folder.mkdir()
    (folder / "report.md").write_bytes(b"report")
    collected = await service.collect_session(owner_user_id=USER_A, agent_key="agent-a", conversation_id=USER_A)
    await service.delete(owner_user_id=USER_A, agent_key="agent-a", artifact_id=collected.artifacts[0].id)
    repeated = await service.collect_session(owner_user_id=USER_A, agent_key="agent-a", conversation_id=USER_A)
    assert not repeated.artifacts and not repeated.failures
    assert len(repository.items) == 1


@pytest.mark.asyncio
async def test_database_delete_failure_preserves_downloadable_archive(tmp_path):
    repository = Repository()
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    source = service._runtime_root(USER_A, "agent-a") / "report.md"
    source.write_bytes(b"report")
    artifact = await service.publish(owner_user_id=USER_A, agent_key="agent-a", source=source)
    async def fail(**kwargs):
        raise RuntimeError("offline")
    repository.mark_deleted = fail
    with pytest.raises(RuntimeError):
        await service.delete(owner_user_id=USER_A, agent_key="agent-a", artifact_id=artifact.id)
    _, path = await service.download_path(owner_user_id=USER_A, agent_key="agent-a", artifact_id=artifact.id)
    assert path.read_bytes() == b"report"


def test_snapshot_write_failure_never_leaves_partial_final_file(tmp_path, monkeypatch):
    import hashlib
    import os
    target = tmp_path / "report.md"
    payload = b"report"
    def fail_link(*args, **kwargs):
        raise OSError("disk unavailable")
    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="disk unavailable"):
        ArtifactService._write_snapshot(target, payload, hashlib.sha256(payload).hexdigest())
    assert not target.exists()


@pytest.mark.asyncio
async def test_collect_directory_error_is_retryable_failure(tmp_path, monkeypatch):
    service = ArtifactService(repository=Repository(), working_dir=tmp_path)
    folder = service._runtime_root(USER_A, "agent-a") / "artifacts" / str(USER_A)
    folder.mkdir()
    def fail_scan(path):
        raise PermissionError("directory unavailable")
    monkeypatch.setattr(service, "_session_files", fail_scan)
    result = await service.collect_session(owner_user_id=USER_A, agent_key="agent-a", conversation_id=USER_A)
    assert not result.artifacts
    assert len(result.failures) == 1
    assert result.failures[0].path == folder
    assert "retryable" in result.failures[0].error


def test_source_modified_during_read_is_retryable(tmp_path, monkeypatch):
    source = tmp_path / "report.md"
    source.write_bytes(b"before")
    original_read = Path.read_bytes
    def modifying_read(path):
        data = original_read(path)
        if path == source:
            path.write_bytes(b"changed while reading")
        return data
    monkeypatch.setattr(Path, "read_bytes", modifying_read)
    with pytest.raises(ArtifactSourceDenied, match="changed.*retryable"):
        ArtifactService._read_content(source)
    assert source.exists()
