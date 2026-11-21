"""产物物理删除失败时，失败操作不得撤销本人既有读取权。"""

from pathlib import Path
from uuid import uuid4

import pytest

from qwenpaw.artifacts.service import ArtifactService
from tests.unit.artifacts.test_service import Repository


@pytest.mark.asyncio
@pytest.mark.parametrize("stable_owner", [False, True])
async def test_failed_artifact_delete_keeps_owned_registration_active(tmp_path, monkeypatch, stable_owner):
    owner = uuid4()
    repository = Repository()
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    source = service._runtime_root(owner, "reporter") / "report.md"
    source.write_bytes(b"owned original")
    artifact = await service.publish(owner_user_id=owner, agent_key="reporter", source=source)
    _, archive = await service.download_owned_path(owner_user_id=owner, artifact_id=artifact.id)
    original_unlink = Path.unlink

    def fail_archive_delete(path, *args, **kwargs):
        if path == archive:
            raise PermissionError("archive busy")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_archive_delete)
        with pytest.raises(PermissionError):
            if stable_owner:
                await service.delete_owned(owner_user_id=owner, artifact_id=artifact.id)
            else:
                await service.delete(owner_user_id=owner, agent_key="reporter", artifact_id=artifact.id)
    assert archive.read_bytes() == b"owned original"
    current = await repository.get(owner_user_id=owner, artifact_id=artifact.id)
    assert current.status == "active", "The failed delete made an intact owned archive inaccessible"
