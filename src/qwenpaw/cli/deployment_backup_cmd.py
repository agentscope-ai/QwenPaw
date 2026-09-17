# -*- coding: utf-8 -*-
"""Internal Docker maintenance command for production backup and restore."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import click

from ..platform_ops.deployment_backup import (
    BackupValidationError,
    atomic_publish_directory,
    create_tree_archive,
    extract_tree_archive,
    new_manifest,
    preflight_restore,
    write_manifest,
)


DATA_ROOT = Path("/data")


def _database_url() -> str:
    value = os.environ.get("QWENPAW_DATABASE_URL", "")
    if not value:
        raise click.ClickException("数据库连接未配置")
    return value


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException("维护命令执行失败，请查看容器日志") from exc


def _assert_database_empty() -> None:
    schema = os.environ.get("QWENPAW_DATABASE_SCHEMA", "public")
    result = subprocess.run(
        [
            "psql",
            "--tuples-only",
            "--no-align",
            "--dbname",
            _database_url(),
            "--command",
            "SELECT count(*) FROM information_schema.tables "
            f"WHERE table_schema = '{schema.replace(chr(39), chr(39) * 2)}';",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if int(result.stdout.strip() or "0") != 0:
        raise click.ClickException("恢复目标数据库必须为空")


@click.group("deployment-backup")
def deployment_backup_group() -> None:
    """Manage portable production backups."""


@deployment_backup_group.command("backup")
@click.option("--output", type=click.Path(path_type=Path), default=DATA_ROOT / "backups")
def backup_command(output: Path) -> None:
    output = output.resolve()
    allowed_root = (DATA_ROOT / "backups").resolve()
    if output != allowed_root and allowed_root not in output.parents:
        raise click.ClickException("备份输出必须位于 /data/backups 内")
    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_root = output / f"weldonagent-{timestamp}"
    temp_root = Path(tempfile.mkdtemp(prefix=".creating-", dir=output))
    try:
        _run(["pg_dump", "--format=custom", "--file", str(temp_root / "database.dump"), _database_url()])
        create_tree_archive(DATA_ROOT / "working", temp_root / "working.tar.gz")
        create_tree_archive(DATA_ROOT / "secrets", temp_root / "secrets.tar.gz")
        manifest = new_manifest(
            temp_root,
            environment={key: value for key, value in os.environ.items() if key.startswith(("WELDON_", "QWENPAW_"))},
            source_commit=os.environ.get("WELDON_SOURCE_COMMIT", "unknown"),
            image_digest=os.environ.get("WELDON_IMAGE_DIGEST", "unknown"),
            alembic_version=os.environ.get("WELDON_SCHEMA_VERSION", "unknown"),
        )
        write_manifest(temp_root, manifest)
        os.replace(temp_root, final_root)
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)
    click.echo(final_root)


@deployment_backup_group.command("restore")
@click.argument("source", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--target-data-root", type=click.Path(path_type=Path), default=DATA_ROOT)
def restore_command(source: Path, target_data_root: Path) -> None:
    source = source.resolve()
    target_data_root = target_data_root.resolve()
    allowed_backup_root = (DATA_ROOT / "backups").resolve()
    if source != allowed_backup_root and allowed_backup_root not in source.parents:
        raise click.ClickException("恢复源必须位于 /data/backups 内")
    if target_data_root != DATA_ROOT.resolve():
        raise click.ClickException("容器恢复目标必须是 /data")
    try:
        preflight_restore(source, target_data_root)
        _assert_database_empty()
    except (BackupValidationError, OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(str(exc)) from exc

    temp_root = Path(tempfile.mkdtemp(prefix=".restoring-", dir=target_data_root))
    try:
        extract_tree_archive(source / "working.tar.gz", temp_root)
        extract_tree_archive(source / "secrets.tar.gz", temp_root)
        _run(
            [
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "--dbname",
                _database_url(),
                str(source / "database.dump"),
            ]
        )
        atomic_publish_directory(temp_root, target_data_root / "working")
        atomic_publish_directory(temp_root, target_data_root / "secrets")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    click.echo("恢复完成；请执行数据库升级检查后再启动应用")
