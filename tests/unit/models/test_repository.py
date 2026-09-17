"""Repository SQL must preserve state and bind values separately."""

from contextlib import asynccontextmanager
from uuid import uuid4
import pytest


@pytest.mark.asyncio
async def test_import_does_not_update_status_or_insert_grants():
    from qwenpaw.models.repository import PostgresModelRepository

    statements = []

    class Session:
        async def execute(self, statement, params=None):
            statements.append((str(statement), params))

    @asynccontextmanager
    async def factory():
        yield Session()

    repo = PostgresModelRepository(schema="fixture", session_factory=factory)
    await repo.import_metadata(
        [
            {
                "id": str(uuid4()),
                "provider_id": "fixture",
                "provider_name": "Fixture",
                "model": "one",
                "name": "One",
                "supports_image": True,
                "supports_video": False,
                "max_input_length": 32000,
            }
        ],
        uuid4(),
    )
    assert len(statements) == 2
    for sql, _ in statements:
        assert "status=" not in sql.split("DO UPDATE SET")[1]
        assert "model_grants" not in sql
    assert statements[0][1]["metadata"] == '{"display_name": "Fixture"}'
