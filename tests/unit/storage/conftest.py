# -*- coding: utf-8 -*-
"""Isolated real backend fixtures for the storage contract suite."""

import os
from uuid import uuid4

import pytest

from qwenpaw.storage.config import PostgreSQLConfig, StorageConfig
from qwenpaw.storage.factory import create_database
from qwenpaw.storage.schema import initialize


@pytest.fixture(params=[f"sqlite", f"postgresql"])
async def db(request, tmp_path, monkeypatch):
    """Use a fresh namespace and only an explicitly supplied test server."""
    backend = request.param
    if backend == f"postgresql":
        dsn = os.environ.get(f"QWENPAW_TEST_POSTGRES_DSN")
        if not dsn:
            pytest.skip(f"Set QWENPAW_TEST_POSTGRES_DSN for PG integration")
        monkeypatch.setenv(f"QWENPAW_STORAGE_TEST_CONNECTION", dsn)
    config = StorageConfig(
        backend=backend,
        deployment_id=f"test-deployment",
        postgresql=PostgreSQLConfig(
            dsn_env=f"QWENPAW_STORAGE_TEST_CONNECTION",
            schema=f"test_{uuid4().hex}",
            table_prefix=f"a_",
        ),
    )
    database = create_database(config, tmp_path)
    await database.open(create=True)
    await initialize(database)
    try:
        yield database
    finally:
        if backend == f"postgresql":
            async with database.transaction(write=True) as tx:
                schema = config.postgresql.schema_name
                await tx.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await database.close()
