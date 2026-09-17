# -*- coding: utf-8 -*-
"""Schema-isolated PostgreSQL fixtures without exposing credentials."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy.engine import URL

LEGACY_DATABASE_NAMES = frozenset({"qwenpaw_test_single_node"})
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SAFE_CONTAINER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_TEST_DATABASE = re.compile(r"^qwenpaw_test_[a-z0-9_]+$")
_TEST_SCHEMA = re.compile(r"^qwenpaw_test_[a-f0-9]{20}$")


def validate_test_database_name(database: str) -> str:
    """Allow only a dedicated test database and reject the legacy source."""
    normalized = database.strip().lower()
    if normalized in LEGACY_DATABASE_NAMES:
        raise ValueError(
            f"Legacy database is read-only for migration: {normalized}"
        )
    if not _SAFE_NAME.fullmatch(normalized) or not _TEST_DATABASE.fullmatch(
        normalized,
    ):
        raise ValueError(
            "PostgreSQL tests require a dedicated qwenpaw_test_* database",
        )
    return normalized


def build_test_schema_name(node_id: str) -> str:
    """Build a unique, SQL-safe schema name for one test invocation."""
    seed = f"{node_id}:{uuid.uuid4().hex}".encode()
    digest = hashlib.sha256(seed).hexdigest()[:20]
    return f"qwenpaw_test_{digest}"


@dataclass(frozen=True)
class PostgresTestConfig:
    """Explicit credential-free connection target for Docker-based tests."""

    container: str
    database: str

    @classmethod
    def from_env(cls) -> PostgresTestConfig | None:
        container = os.environ.get(
            "QWENPAW_TEST_POSTGRES_CONTAINER", ""
        ).strip()
        database = os.environ.get("QWENPAW_TEST_POSTGRES_DATABASE", "").strip()
        if not container and not database:
            return None
        if not container or not database:
            raise ValueError(
                "Both QWENPAW_TEST_POSTGRES_CONTAINER and "
                "QWENPAW_TEST_POSTGRES_DATABASE are required",
            )
        if not _SAFE_CONTAINER_NAME.fullmatch(container):
            raise ValueError("Unsafe PostgreSQL test container name")
        return cls(
            container=container,
            database=validate_test_database_name(database),
        )


@dataclass(frozen=True)
class PostgresTestSchema:
    """One disposable schema inside the dedicated test database."""

    config: PostgresTestConfig
    name: str

    def as_report(self) -> dict[str, str]:
        return {
            "container": self.config.container,
            "database": self.config.database,
            "schema": self.name,
        }

    def async_url(self) -> str:
        """Resolve a host URL for Alembic without storing it in reports."""
        completed = subprocess.run(
            ["docker", "inspect", self.config.container],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(completed.stdout)
        if len(payload) != 1:
            raise RuntimeError("Unexpected PostgreSQL container inspection")
        container = payload[0]
        environment = {}
        for item in container.get("Config", {}).get("Env", []):
            key, separator, value = item.partition("=")
            if separator:
                environment[key] = value
        bindings = (
            container.get("NetworkSettings", {})
            .get("Ports", {})
            .get("5432/tcp")
        )
        if not bindings or len(bindings) != 1:
            raise RuntimeError(
                "PostgreSQL test port must have one host binding"
            )
        binding = bindings[0]
        host = binding.get("HostIp") or "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        username = environment.get("POSTGRES_USER", "postgres")
        password = environment.get("POSTGRES_PASSWORD")
        if not password:
            raise RuntimeError("PostgreSQL test password is not configured")
        return URL.create(
            drivername="postgresql+asyncpg",
            username=username,
            password=password,
            host=host,
            port=int(binding["HostPort"]),
            database=self.config.database,
        ).render_as_string(hide_password=False)


def build_docker_psql_command(config: PostgresTestConfig) -> list[str]:
    """Build the fixed Docker command without embedding credentials or SQL."""
    return [
        "docker",
        "exec",
        "--env",
        "QWENPAW_TEST_SQL",
        config.container,
        "sh",
        "-lc",
        'psql -X -v ON_ERROR_STOP=1 -A -t -U "$POSTGRES_USER" '
        f'-d "{config.database}" -c "$QWENPAW_TEST_SQL"',
    ]


class DockerPostgresAdmin:
    """Execute fixed administrative SQL through the container-local user."""

    def __init__(self, config: PostgresTestConfig) -> None:
        self.config = config

    def execute(self, sql: str) -> str:
        command = build_docker_psql_command(self.config)
        environment = os.environ.copy()
        environment["QWENPAW_TEST_SQL"] = sql
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        return completed.stdout.strip()

    def create_schema(self, schema: str) -> None:
        if not _TEST_SCHEMA.fullmatch(schema):
            raise ValueError(f"Unsafe PostgreSQL test schema: {schema}")
        self.execute(f'CREATE SCHEMA "{schema}"')

    def schema_exists(self, schema: str) -> bool:
        if not _TEST_SCHEMA.fullmatch(schema):
            raise ValueError(f"Unsafe PostgreSQL test schema: {schema}")
        result = self.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_namespace "
            f"WHERE nspname = '{schema}')",
        )
        return result == "t"

    def drop_schema(self, schema: str) -> None:
        if not _TEST_SCHEMA.fullmatch(schema):
            raise ValueError(f"Unsafe PostgreSQL test schema: {schema}")
        self.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def postgres_test_schema(
    request: pytest.FixtureRequest,
) -> Iterator[PostgresTestSchema]:
    """Create and safely drop an independent schema for one test."""
    config = PostgresTestConfig.from_env()
    if config is None:
        pytest.skip("Dedicated PostgreSQL test database is not configured")
    schema = PostgresTestSchema(
        config=config,
        name=build_test_schema_name(request.node.nodeid),
    )
    admin = DockerPostgresAdmin(config)
    admin.create_schema(schema.name)
    if not admin.schema_exists(schema.name):
        raise RuntimeError(
            f"PostgreSQL test schema was not created: {schema.name}"
        )
    try:
        yield schema
    finally:
        admin.drop_schema(schema.name)
