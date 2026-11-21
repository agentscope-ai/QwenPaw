"""附件读取只跟随可信归属与规范目录，不跟随旧绝对路径。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.attachments.service import resolve_owned_attachment_path
from qwenpaw.app.chats.repo import AttachmentRecord


@pytest.mark.parametrize("scope,lifecycle,directory", [
    ("private", "temporary", "media"), ("private", "saved", "documents"),
    ("private", "saved", "资料"), ("legacy", "temporary", "media"),
    ("legacy", "saved", "documents"), ("legacy", "saved", "资料"),
])
def test_owned_attachment_survives_data_root_change(tmp_path, scope, lifecycle, directory):
    owner = uuid4()
    prefix = f"user_workspaces/{owner}/reporter" if scope == "private" else "workspaces/reporter"
    target = tmp_path / prefix / directory / "文件.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-owned")
    record = AttachmentRecord(id=uuid4(), owner_user_id=owner,
        agent_id=agent_database_id("reporter"), storage_key=f"D:/old-install/{prefix}/{directory}/文件.pdf",
        original_name="文件.pdf", media_type="application/pdf", size=10, content_hash="test",
        lifecycle=lifecycle, created_at=datetime.now(UTC))
    assert resolve_owned_attachment_path(record, owner_user_id=owner, working_dir=tmp_path) == target.resolve()
    with pytest.raises(FileNotFoundError):
        resolve_owned_attachment_path(record, owner_user_id=uuid4(), working_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_owned_attachment_path(record.model_copy(update={"agent_id": uuid4()}),
                                      owner_user_id=owner, working_dir=tmp_path)


def test_owned_attachment_rejects_symlink_and_path_traversal(tmp_path):
    owner = uuid4()
    root = tmp_path / "user_workspaces" / str(owner) / "reporter"
    media = root / "media"
    media.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    record = AttachmentRecord(id=uuid4(), owner_user_id=owner,
        agent_id=agent_database_id("reporter"), storage_key=str(media / "../../../outside.txt"),
        original_name="outside.txt", media_type="text/plain", size=7, content_hash="test",
        created_at=datetime.now(UTC))
    with pytest.raises(FileNotFoundError):
        resolve_owned_attachment_path(record, owner_user_id=owner, working_dir=tmp_path)
    link = media / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("The platform does not permit symlink creation")
    with pytest.raises(FileNotFoundError):
        resolve_owned_attachment_path(record.model_copy(update={"storage_key": str(link)}),
                                      owner_user_id=owner, working_dir=tmp_path)


@pytest.mark.parametrize("scope", ["private", "legacy", "foreign_private"])
def test_missing_owned_attachment_never_reinterprets_nested_workspace_root(tmp_path, scope):
    owner = uuid4()
    shared = tmp_path / "workspaces" / "reporter" / "documents" / "victim.pdf"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(b"%PDF-other-user-secret")
    if scope == "legacy":
        prefix = "workspaces/reporter/documents"
    else:
        path_owner = uuid4() if scope == "foreign_private" else owner
        prefix = f"user_workspaces/{path_owner}/reporter/documents"
    storage = f"D:/old-install/{prefix}/workspaces/reporter/documents/victim.pdf"
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=owner, agent_id=agent_database_id("reporter"),
        storage_key=storage, original_name="mine.pdf", media_type="application/pdf",
        size=10, content_hash="sha256:own-original", lifecycle="saved",
        created_at=datetime.now(UTC),
    )
    with pytest.raises(FileNotFoundError):
        resolve_owned_attachment_path(record, owner_user_id=owner, working_dir=tmp_path)
    assert shared.read_bytes() == b"%PDF-other-user-secret"


@pytest.mark.parametrize("scope", ["private", "legacy"])
def test_existing_owned_attachment_keeps_nested_workspace_names_literal(tmp_path, scope):
    owner = uuid4()
    prefix = f"user_workspaces/{owner}/reporter" if scope == "private" else "workspaces/reporter"
    relative = "documents/workspaces/reporter/documents/mine.pdf"
    target = tmp_path / prefix / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-owned-nested")
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=owner, agent_id=agent_database_id("reporter"),
        storage_key=f"D:/old-install/{prefix}/{relative}", original_name="mine.pdf",
        media_type="application/pdf", size=17, content_hash="test", lifecycle="saved",
        created_at=datetime.now(UTC),
    )
    assert resolve_owned_attachment_path(record, owner_user_id=owner, working_dir=tmp_path) == target.resolve()


def test_current_data_root_can_contain_workspace_directory_names(tmp_path):
    owner = uuid4()
    base = tmp_path / "workspaces" / "data"
    target = base / "user_workspaces" / str(owner) / "reporter" / "media" / "mine.txt"
    target.parent.mkdir(parents=True)
    target.write_text("owned", encoding="utf-8")
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=owner, agent_id=agent_database_id("reporter"),
        storage_key=str(target), original_name="mine.txt", media_type="text/plain",
        size=5, content_hash="test", lifecycle="temporary", created_at=datetime.now(UTC),
    )
    assert resolve_owned_attachment_path(record, owner_user_id=owner, working_dir=base) == target.resolve()
