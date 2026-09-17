# -*- coding: utf-8 -*-
from __future__ import annotations

from click.testing import CliRunner

from qwenpaw.cli.deployment_backup_cmd import deployment_backup_group


def test_backup_output_must_be_inside_container_backup_root(tmp_path):
    result = CliRunner().invoke(
        deployment_backup_group,
        ["backup", "--output", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "/data/backups" in result.output


def test_restore_requires_existing_backup_directory(tmp_path):
    result = CliRunner().invoke(
        deployment_backup_group,
        ["restore", str(tmp_path / "missing")],
    )
    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_restore_source_must_be_inside_container_backup_root(tmp_path):
    source = tmp_path / "backup"
    source.mkdir()
    result = CliRunner().invoke(
        deployment_backup_group,
        ["restore", str(source)],
    )
    assert result.exit_code != 0
    assert "/data/backups" in result.output
