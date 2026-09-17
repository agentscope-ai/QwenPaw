# -*- coding: utf-8 -*-
from __future__ import annotations

def test_artifact_repository_rejects_unsafe_schema_name() -> None:
    from qwenpaw.artifacts.repository import PostgresArtifactRepository
    import pytest

    with pytest.raises(ValueError, match="invalid_database_schema"):
        PostgresArtifactRepository(schema="qwenpaw; DROP SCHEMA public")


import pytest


@pytest.mark.asyncio
async def test_register_rechecks_content_after_transaction_lock(monkeypatch):
    from contextlib import asynccontextmanager
    from dataclasses import asdict
    from datetime import UTC, datetime
    from uuid import uuid4
    from qwenpaw.artifacts.models import AgentArtifact
    from qwenpaw.artifacts.repository import PostgresArtifactRepository

    artifact = AgentArtifact(id=uuid4(), owner_user_id=uuid4(), agent_id=uuid4(), conversation_id=uuid4(), relative_path="artifacts/report.md", original_name="report.md", media_type="text/markdown", size=6, sha256="digest", source_tool="send_file_to_user", status="active", created_at=datetime.now(UTC), deleted_at=None)
    statements = []
    class Result:
        def mappings(self):
            return self
        def one_or_none(self):
            return asdict(artifact)
    class Session:
        async def execute(self, statement, parameters):
            statements.append(str(statement))
            return Result()
    @asynccontextmanager
    async def sessions():
        yield Session()
    async def set_user(*args):
        pass
    monkeypatch.setattr("qwenpaw.artifacts.repository.set_request_user", set_user)
    result = await PostgresArtifactRepository(session_factory=sessions).register(artifact)
    assert result == artifact
    assert "pg_advisory_xact_lock" in statements[0]
    assert "IS NOT DISTINCT FROM" in statements[1]
    assert not any("INSERT" in sql for sql in statements)
