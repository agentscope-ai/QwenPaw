"""自定义旧工作区需要登记根及原始内容证明，不能放开任意绝对路径。"""

from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.attachments.service import resolve_owned_attachment_path
from qwenpaw.app.chats.repo import AttachmentRecord


@pytest.mark.parametrize("case", ["retained", "disabled", "no_registration", "wrong_agent", "changed_content", "unverified_digest", "foreign", "outside_media"])
def test_custom_registered_attachment_read_is_bound_to_owner_and_original_content(tmp_path, monkeypatch, case):
    owner = uuid4()
    root = tmp_path / "custom-agent"
    source = root / ("config" if case == "outside_media" else "media") / "original.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"owned original")
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=owner,
        agent_id=agent_database_id("different" if case == "wrong_agent" else "reporter"),
        storage_key=str(source), original_name=source.name, media_type="text/markdown",
        size=14, content_hash="invalid" if case == "unverified_digest" else "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        created_at=datetime.now(UTC),
    )
    if case == "changed_content":
        source.write_bytes(b"different content")
    profiles = {} if case == "no_registration" else {"reporter": SimpleNamespace(workspace_dir=str(root), enabled=case != "disabled")}
    monkeypatch.setattr("qwenpaw.config.load_config", lambda: SimpleNamespace(agents=SimpleNamespace(profiles=profiles)))
    if case in {"retained", "disabled"}:
        assert resolve_owned_attachment_path(record, owner_user_id=owner, working_dir=tmp_path / "data") == source
    else:
        with pytest.raises(FileNotFoundError):
            resolve_owned_attachment_path(record, owner_user_id=uuid4() if case == "foreign" else owner, working_dir=tmp_path / "data")
