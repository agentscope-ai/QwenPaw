"""元数据更新失败后，本人附件原件和既有登记路径必须仍然有效。"""

from datetime import UTC, datetime
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.attachments.service import AttachmentLifecycleService
from qwenpaw.app.chats.repo import AttachmentRecord


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "move", "delete"])
@pytest.mark.parametrize("failure", ["exception", "cancelled", "missing"])
async def test_attachment_metadata_failure_preserves_existing_file(tmp_path, operation, failure):
    owner = uuid4()
    lifecycle = "temporary" if operation == "save" else "saved"
    source = tmp_path / ("media" if lifecycle == "temporary" else "documents") / "original.md"
    source.parent.mkdir(parents=True)
    source.write_text("owned original", encoding="utf-8")
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=owner, agent_id=agent_database_id("reporter"),
        storage_key=str(source), original_name=source.name, media_type="text/markdown",
        size=14, content_hash="fixture", lifecycle=lifecycle, created_at=datetime.now(UTC),
    )
    repository = SimpleNamespace(
        get_attachment=AsyncMock(return_value=record),
        update_attachment_lifecycle=AsyncMock(
            side_effect=RuntimeError("metadata unavailable") if failure == "exception"
            else asyncio.CancelledError() if failure == "cancelled" else None,
            return_value=None,
        ),
    )
    service = AttachmentLifecycleService(repository=repository, runtime_root=tmp_path)
    options = {"attachment_id": record.id, "owner_user_id": owner}
    if operation in {"save", "move"}:
        options["target_path"] = "renamed.md"
    error = RuntimeError if failure == "exception" else asyncio.CancelledError if failure == "cancelled" else FileNotFoundError
    with pytest.raises(error):
        await getattr(service, operation)(**options)
    assert source.is_file(), "Failed operation removed the file still referenced by its active record"
    assert source.read_text(encoding="utf-8") == "owned original"
    assert not (tmp_path / "documents" / "renamed.md").exists()
    assert not list(source.parent.glob("*.deleting"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "move", "delete"])
async def test_attachment_success_updates_record_and_file_together(tmp_path, operation):
    owner = uuid4()
    lifecycle = "temporary" if operation == "save" else "saved"
    source = tmp_path / ("media" if lifecycle == "temporary" else "documents") / "original.md"
    source.parent.mkdir(parents=True)
    source.write_text("owned original", encoding="utf-8")
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=owner, agent_id=agent_database_id("reporter"),
        storage_key=str(source), original_name=source.name, media_type="text/markdown",
        size=14, content_hash="fixture", lifecycle=lifecycle, created_at=datetime.now(UTC),
    )
    repository = SimpleNamespace(get_attachment=AsyncMock(return_value=record))

    async def update(**fields):
        return record.model_copy(update={name: value for name, value in fields.items() if name != "attachment_id"})

    repository.update_attachment_lifecycle = AsyncMock(side_effect=update)
    service = AttachmentLifecycleService(repository=repository, runtime_root=tmp_path)
    options = {"attachment_id": record.id, "owner_user_id": owner}
    if operation != "delete":
        options["target_path"] = "renamed.md"
    result = await getattr(service, operation)(**options)
    assert result.lifecycle == ("deleted" if operation == "delete" else "saved")
    assert not source.exists()
    assert not list(source.parent.glob("*.deleting"))
    if operation != "delete":
        assert Path(result.storage_key).read_text(encoding="utf-8") == "owned original"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "move"])
async def test_attachment_existing_target_does_not_change_either_file(tmp_path, operation):
    owner = uuid4()
    lifecycle = "temporary" if operation == "save" else "saved"
    source = tmp_path / ("media" if lifecycle == "temporary" else "documents") / "original.md"
    target = tmp_path / "documents" / "renamed.md"
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("original", encoding="utf-8")
    target.write_text("existing", encoding="utf-8")
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=owner, agent_id=agent_database_id("reporter"),
        storage_key=str(source), original_name=source.name, media_type="text/markdown",
        size=8, content_hash="fixture", lifecycle=lifecycle, created_at=datetime.now(UTC),
    )
    repository = SimpleNamespace(get_attachment=AsyncMock(return_value=record), update_attachment_lifecycle=AsyncMock())
    from qwenpaw.app.attachments.service import AttachmentLifecycleError
    with pytest.raises(AttachmentLifecycleError, match="attachment_target_exists"):
        await getattr(AttachmentLifecycleService(repository=repository, runtime_root=tmp_path), operation)(
            attachment_id=record.id, owner_user_id=owner, target_path="renamed.md",
        )
    assert source.read_text(encoding="utf-8") == "original"
    assert target.read_text(encoding="utf-8") == "existing"
    repository.update_attachment_lifecycle.assert_not_awaited()


def test_attachment_move_cannot_overwrite_racing_target(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    with pytest.raises(FileExistsError):
        AttachmentLifecycleService._move_without_overwrite(source, target)
    assert source.read_bytes() == b"source" and target.read_bytes() == b"target"


def test_attachment_failed_move_does_not_clean_a_replaced_target(tmp_path, monkeypatch):
    source, target, replacement = tmp_path / "source", tmp_path / "target", tmp_path / "replacement"
    source.write_bytes(b"source")
    replacement.write_bytes(b"replacement")
    original_unlink = Path.unlink

    def fail_source_unlink(path, *args, **kwargs):
        if path == source:
            os.replace(replacement, target)
            raise PermissionError("source busy")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_source_unlink)
        with pytest.raises(PermissionError):
            AttachmentLifecycleService._move_without_overwrite(source, target)
    assert source.read_bytes() == b"source"
    assert target.read_bytes() == b"replacement"


def test_attachment_copy_failure_cleans_only_its_partial_target(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"source")

    def failed_copy(origin, destination):
        destination.write(b"partial")
        raise OSError("copy failed")

    monkeypatch.setattr("qwenpaw.app.attachments.service.shutil.copyfileobj", failed_copy)
    with pytest.raises(OSError, match="copy failed"):
        AttachmentLifecycleService._move_without_overwrite(source, target)
    assert source.read_bytes() == b"source"
    assert not target.exists()


@pytest.mark.asyncio
async def test_attachment_delete_cleanup_failure_restores_source_and_metadata(tmp_path, monkeypatch):
    owner = uuid4()
    source = tmp_path / "documents" / "original.md"
    source.parent.mkdir()
    source.write_bytes(b"source")
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=owner, agent_id=agent_database_id("reporter"),
        storage_key=str(source), original_name=source.name, media_type="text/markdown",
        size=6, content_hash="fixture", lifecycle="saved", created_at=datetime.now(UTC),
    )
    state = {"record": record}

    async def update(**fields):
        state["record"] = record.model_copy(update={name: value for name, value in fields.items() if name != "attachment_id"})
        return state["record"]

    repository = SimpleNamespace(get_attachment=AsyncMock(return_value=record), update_attachment_lifecycle=AsyncMock(side_effect=update))
    service = AttachmentLifecycleService(repository=repository, runtime_root=tmp_path)
    original_unlink = Path.unlink
    blocked = []

    def fail_cleanup_once(path, *args, **kwargs):
        if path.name.endswith(".deleting") and not blocked:
            blocked.append(path)
            raise PermissionError("cleanup failed")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_cleanup_once)
        with pytest.raises(PermissionError, match="cleanup failed"):
            await service.delete(attachment_id=record.id, owner_user_id=owner)
    assert source.read_bytes() == b"source"
    assert state["record"].lifecycle == "saved"
    assert state["record"].storage_key == str(source)
    assert repository.update_attachment_lifecycle.await_count == 2
    assert not list(source.parent.glob("*.deleting"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "move", "delete"])
@pytest.mark.parametrize("mismatch", ["owner", "id"])
async def test_attachment_mutation_checks_repository_record_identity(tmp_path, operation, mismatch):
    owner, identifier = uuid4(), uuid4()
    lifecycle = "temporary" if operation == "save" else "saved"
    source = tmp_path / ("media" if lifecycle == "temporary" else "documents") / "original.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    record = AttachmentRecord(
        id=uuid4() if mismatch == "id" else identifier,
        owner_user_id=uuid4() if mismatch == "owner" else owner,
        agent_id=agent_database_id("reporter"), storage_key=str(source),
        original_name=source.name, media_type="text/markdown", size=6,
        content_hash="fixture", lifecycle=lifecycle, created_at=datetime.now(UTC),
    )
    repository = SimpleNamespace(get_attachment=AsyncMock(return_value=record), update_attachment_lifecycle=AsyncMock())
    with pytest.raises(FileNotFoundError):
        await getattr(AttachmentLifecycleService(repository=repository, runtime_root=tmp_path), operation)(
            attachment_id=identifier, owner_user_id=owner,
            **({"target_path": "renamed.md"} if operation != "delete" else {}),
        )
    assert source.read_bytes() == b"source"
    repository.update_attachment_lifecycle.assert_not_awaited()
