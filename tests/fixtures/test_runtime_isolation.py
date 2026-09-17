# -*- coding: utf-8 -*-
"""Safety contracts for isolated test runtime resources."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from postgres import (
    DockerPostgresAdmin,
    LEGACY_DATABASE_NAMES,
    PostgresTestConfig,
    PostgresTestSchema,
    build_docker_psql_command,
    build_test_schema_name,
    validate_test_database_name,
)
from runtime_dirs import (
    UnsafeTestPathError,
    cleanup_runtime_dirs,
    create_runtime_dirs,
    validate_test_root,
)


def test_rejects_workspace_home_and_existing_data_roots(
    tmp_path: Path,
) -> None:
    """A weakened forbidden-path check must never target live data."""
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    data = tmp_path / "live-data"
    for path in (workspace, home, data):
        path.mkdir()

    for unsafe_path in (
        workspace,
        home,
        data,
        workspace / "child",
        home / "child",
    ):
        with pytest.raises(UnsafeTestPathError):
            validate_test_root(
                unsafe_path,
                workspace_root=workspace,
                home_dir=home,
                existing_data_dirs=(data,),
            )


def test_creates_separate_working_secret_and_backup_directories(
    tmp_path: Path,
) -> None:
    """Collapsing runtime data back into one directory must fail this test."""
    runtime = create_runtime_dirs(
        tmp_path / "safe-test-root",
        workspace_root=tmp_path / "workspace",
        home_dir=tmp_path / "home",
        existing_data_dirs=(tmp_path / "live-data",),
    )

    assert runtime.working_dir == runtime.root / "working"
    assert runtime.secret_dir == runtime.root / "secret"
    assert runtime.backup_dir == runtime.root / "backup"
    assert (
        len(
            {
                runtime.working_dir.resolve(),
                runtime.secret_dir.resolve(),
                runtime.backup_dir.resolve(),
            },
        )
        == 3
    )
    assert all(path.is_dir() for path in runtime.resource_dirs)

    cleanup_runtime_dirs(runtime)


def test_cleanup_refuses_resource_resolving_outside_test_root(
    tmp_path: Path,
) -> None:
    """Removing the containment check must expose this path traversal."""
    runtime = create_runtime_dirs(
        tmp_path / "safe-test-root",
        workspace_root=tmp_path / "workspace",
        home_dir=tmp_path / "home",
        existing_data_dirs=(),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    unsafe_runtime = replace(runtime, secret_dir=outside)

    with pytest.raises(UnsafeTestPathError):
        cleanup_runtime_dirs(unsafe_runtime)

    assert outside.is_dir()
    cleanup_runtime_dirs(runtime)


def test_database_target_rejects_legacy_and_non_test_databases() -> None:
    """A relaxed database-name guard must not reach the legacy database."""
    for database in (*LEGACY_DATABASE_NAMES, "postgres", "qwenpaw"):
        with pytest.raises(ValueError):
            validate_test_database_name(database)

    assert validate_test_database_name("qwenpaw_test_isolation") == (
        "qwenpaw_test_isolation"
    )


def test_each_postgres_schema_name_is_unique_and_test_scoped() -> None:
    """Reusing a shared schema across tests must fail this contract."""
    first = build_test_schema_name("tests/test_chat.py::test_first")
    second = build_test_schema_name("tests/test_chat.py::test_second")

    assert first.startswith("qwenpaw_test_")
    assert second.startswith("qwenpaw_test_")
    assert first != second


def test_postgres_config_requires_explicit_test_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing test configuration must never fall back to an app database."""
    monkeypatch.delenv("QWENPAW_TEST_POSTGRES_CONTAINER", raising=False)
    monkeypatch.delenv("QWENPAW_TEST_POSTGRES_DATABASE", raising=False)

    assert PostgresTestConfig.from_env() is None


def test_docker_psql_command_forwards_sql_without_credentials() -> None:
    """Dropping Docker's explicit env forwarding must break SQL execution."""
    config = PostgresTestConfig(
        container="qwenpaw-pg",
        database="qwenpaw_test_isolation",
    )

    assert build_docker_psql_command(config) == [
        "docker",
        "exec",
        "--env",
        "QWENPAW_TEST_SQL",
        "qwenpaw-pg",
        "sh",
        "-lc",
        'psql -X -v ON_ERROR_STOP=1 -A -t -U "$POSTGRES_USER" '
        '-d "qwenpaw_test_isolation" -c "$QWENPAW_TEST_SQL"',
    ]


def test_postgres_schema_builds_async_url_without_exposing_it_in_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build a migration URL without exposing it in fixture reports."""
    import json
    import subprocess

    config = PostgresTestConfig(
        container="qwenpaw-pg-test",
        database="qwenpaw_test_migrations",
    )
    schema = PostgresTestSchema(
        config=config,
        name="qwenpaw_test_0123456789abcdef0123",
    )
    inspect_payload = [
        {
            "Config": {
                "Env": [
                    "POSTGRES_USER=qwenpaw",
                    "POSTGRES_PASSWORD=top-secret",
                ],
            },
            "NetworkSettings": {
                "Ports": {
                    "5432/tcp": [
                        {"HostIp": "127.0.0.1", "HostPort": "55433"},
                    ],
                },
            },
        },
    ]

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(inspect_payload),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert schema.async_url() == (
        "postgresql+asyncpg://qwenpaw:top-secret@127.0.0.1:55433/"
        "qwenpaw_test_migrations"
    )
    assert "top-secret" not in repr(schema)


def test_autouse_runtime_fixture_exports_only_its_own_directories(
    isolated_runtime_dirs,
) -> None:
    """Future tests must receive the unique per-test environment paths."""
    import os

    assert Path(os.environ["QWENPAW_TEST_ROOT"]) == isolated_runtime_dirs.root
    assert Path(os.environ["QWENPAW_WORKING_DIR"]) == (
        isolated_runtime_dirs.working_dir
    )
    assert Path(os.environ["QWENPAW_SECRET_DIR"]) == (
        isolated_runtime_dirs.secret_dir
    )
    assert Path(os.environ["QWENPAW_BACKUP_DIR"]) == (
        isolated_runtime_dirs.backup_dir
    )


@pytest.mark.integration
def test_postgres_fixture_creates_one_disposable_schema(
    postgres_test_schema,
) -> None:
    """The real fixture must expose only its independently created schema."""
    admin = DockerPostgresAdmin(postgres_test_schema.config)

    assert postgres_test_schema.name.startswith("qwenpaw_test_")
    assert admin.schema_exists(postgres_test_schema.name)
