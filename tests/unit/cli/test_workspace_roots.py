# -*- coding: utf-8 -*-
"""Tests for local workspace root registry commands."""

from pathlib import Path

from click.testing import CliRunner

from qwenpaw.cli.main import cli


def _set_working_dir(monkeypatch, working_dir: Path) -> None:
    monkeypatch.setattr("qwenpaw.config.paths.WORKING_DIR", working_dir)


def test_workspace_root_add_list_and_remove(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Manage an external root without loading the application config."""
    working_dir = tmp_path / "qwenpaw"
    external = tmp_path / "external"
    external.mkdir()
    _set_working_dir(monkeypatch, working_dir)
    runner = CliRunner()

    added = runner.invoke(
        cli,
        [
            "workspace-root",
            "add",
            "--id",
            "external",
            "--path",
            str(external),
        ],
    )
    listed = runner.invoke(cli, ["workspace-root", "list"])
    removed = runner.invoke(
        cli,
        ["workspace-root", "remove", "external"],
    )

    assert added.exit_code == 0
    assert f"external\t{external.resolve()}" in listed.output
    assert removed.exit_code == 0
    assert external.is_dir()


def test_workspace_root_add_rejects_reserved_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Keep the built-in default root immutable."""
    working_dir = tmp_path / "qwenpaw"
    external = tmp_path / "external"
    external.mkdir()
    _set_working_dir(monkeypatch, working_dir)

    result = CliRunner().invoke(
        cli,
        [
            "workspace-root",
            "add",
            "--id",
            "default",
            "--path",
            str(external),
        ],
    )

    assert result.exit_code == 1
    assert "reserved" in result.output
