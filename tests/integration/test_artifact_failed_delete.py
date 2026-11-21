"""专用测试数据库验证失败删除只补偿同一所有者的本次操作。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qwenpaw.artifacts.repository import PostgresArtifactRepository
from qwenpaw.artifacts.service import ArtifactService
from tests.integration.test_automation_repository import automation_database, _seed


@pytest.mark.asyncio
async def test_failed_delete_restore_is_owned_and_compare_and_swap(automation_database, tmp_path):
    schema, sessions = automation_database
    key, owner, other = await _seed(schema, sessions)
    repository = PostgresArtifactRepository(schema=schema, session_factory=sessions)
    service = ArtifactService(repository=repository, working_dir=tmp_path)
    source = service._runtime_root(owner, key) / "report.md"
    source.write_bytes(b"owned original")
    record = await service.publish(owner_user_id=owner, agent_key=key, source=source)
    stamp = datetime.now(UTC)
    await repository.mark_deleted(owner_user_id=owner, artifact_id=record.id, deleted_at=stamp)
    for user_id, identifier, deleted_at in (
        (other, record.id, stamp), (owner, uuid4(), stamp),
        (owner, record.id, stamp + timedelta(seconds=1)),
    ):
        assert await repository.restore_failed_delete(owner_user_id=user_id, artifact_id=identifier, deleted_at=deleted_at) is None
    assert (await repository.get(owner_user_id=owner, artifact_id=record.id)).status == "deleted"
    restored = await repository.restore_failed_delete(owner_user_id=owner, artifact_id=record.id, deleted_at=stamp)
    assert restored.status == "active" and restored.deleted_at is None
    assert await repository.restore_failed_delete(owner_user_id=owner, artifact_id=record.id, deleted_at=stamp) is None
