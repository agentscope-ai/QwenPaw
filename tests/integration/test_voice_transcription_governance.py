"""Task 7.3 uses a disposable PG schema; ASR never requires chat grants."""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from tests.integration.test_model_governance_repository import governance_database


@pytest.mark.asyncio
async def test_asr_obeys_registered_provider_and_model_status_without_grants(
    governance_database, monkeypatch
):
    from qwenpaw.models import runtime
    from qwenpaw.models.repository import PostgresModelRepository

    schema, dsn = governance_database
    engine = create_async_engine(dsn, poolclass=NullPool)
    factory = async_sessionmaker(engine)

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    repo = PostgresModelRepository(schema=schema, session_factory=session_factory)
    monkeypatch.setattr(runtime, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(runtime, "PostgresModelRepository", lambda **kwargs: repo)
    monkeypatch.setattr(runtime, "get_identity_schema", lambda: schema)
    pid, mid, admin = uuid4(), uuid4(), uuid4()
    try:
        # No registration or grant is required for administrator-selected ASR.
        await runtime.require_transcription_service("fake", "task73-whisper")
        async with session_factory() as session:
            await session.execute(
                text(
                    f"INSERT INTO \"{schema}\".users (id,username,password_hash,status,platform_role) VALUES (:id,'voice-admin','x','active','admin')"
                ),
                {"id": admin},
            )
            await session.execute(
                text(
                    f"INSERT INTO \"{schema}\".model_providers (id,name,type,status,created_by) VALUES (:id,'fake','runtime','disabled',:admin)"
                ),
                {"id": pid, "admin": admin},
            )
        with pytest.raises(runtime.ModelAccessError):
            await runtime.require_transcription_service("fake", "task73-whisper")
        async with session_factory() as session:
            await session.execute(
                text(
                    f"UPDATE \"{schema}\".model_providers SET status='active' WHERE id=:id"
                ),
                {"id": pid},
            )
            await session.execute(
                text(
                    f"INSERT INTO \"{schema}\".models (id,provider_id,model_key,display_name,capabilities,status) VALUES (:id,:pid,'task73-whisper','ASR','{{}}','disabled')"
                ),
                {"id": mid, "pid": pid},
            )
        with pytest.raises(runtime.ModelAccessError):
            await runtime.require_transcription_service("fake", "task73-whisper")
        await runtime.require_transcription_service("fake", "another-asr")
        async with session_factory() as session:
            await session.execute(
                text(f"UPDATE \"{schema}\".models SET status='active' WHERE id=:id"),
                {"id": mid},
            )
        await runtime.require_transcription_service("fake", "task73-whisper")
    finally:
        await engine.dispose()
