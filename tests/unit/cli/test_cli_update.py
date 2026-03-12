# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from copaw.__version__ import __version__
from copaw.cli.main import cli
from copaw.cli.update_cmd import (
    InstallInfo,
    RunningServiceInfo,
    _detect_installation,
    _is_newer_version,
    _detect_source_type,
)


def _install_info(
    *,
    source_type: str = "pypi",
    installer: str = "pip",
) -> InstallInfo:
    return InstallInfo(
        package_dir="/tmp/site-packages/copaw",
        python_executable="/tmp/venv/bin/python",
        environment_root="/tmp/venv",
        environment_kind="virtualenv",
        installer=installer,
        source_type=source_type,
        source_url=None,
    )


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("1.2.4", "1.2.3", True),
        ("1.2.3", "1.2.3", False),
        ("1.2.2", "1.2.3", False),
        ("1.2.3", "1.2.3rc1", True),
        ("1.2.3rc1", "1.2.3", False),
        ("main", "main", False),
        ("main", "feature", None),
        ("main", "1.2.3", None),
    ],
)
def test_is_newer_version(
    latest: str,
    current: str,
    expected: bool | None,
) -> None:
    assert _is_newer_version(latest, current) is expected


@pytest.mark.parametrize(
    ("direct_url", "expected"),
    [
        (None, ("pypi", None)),
        (
            {
                "url": "file:///Users/test/CoPaw",
                "dir_info": {"editable": True},
            },
            ("editable", "file:///Users/test/CoPaw"),
        ),
        (
            {
                "url": "https://github.com/agentscope-ai/CoPaw.git",
                "vcs_info": {"vcs": "git", "commit_id": "abc123"},
            },
            ("vcs", "https://github.com/agentscope-ai/CoPaw.git"),
        ),
        (
            {"url": "file:///tmp/copaw.whl"},
            ("local", "file:///tmp/copaw.whl"),
        ),
        (
            {"url": "https://example.com/copaw.whl"},
            ("direct-url", "https://example.com/copaw.whl"),
        ),
    ],
)
def test_detect_source_type(
    direct_url: dict[str, object] | None,
    expected: tuple[str, str | None],
) -> None:
    assert _detect_source_type(direct_url) == expected


@pytest.mark.parametrize(
    (
        "installer_text",
        "direct_url_text",
        "expected_installer",
        "expected_source_type",
        "expected_source_url",
    ),
    [
        (None, None, "pip", "pypi", None),
        (
            "uv\n",
            json.dumps(
                {
                    "url": "file:///Users/test/CoPaw",
                    "dir_info": {"editable": True},
                },
            ),
            "uv",
            "editable",
            "file:///Users/test/CoPaw",
        ),
    ],
)
def test_detect_installation(
    monkeypatch,
    installer_text: str | None,
    direct_url_text: str | None,
    expected_installer: str,
    expected_source_type: str,
    expected_source_url: str | None,
) -> None:
    from copaw.cli import update_cmd as update_cmd_module

    class _FakeDistribution:
        def read_text(self, name: str) -> str | None:
            mapping = {
                "INSTALLER": installer_text,
                "direct_url.json": direct_url_text,
            }
            return mapping.get(name)

    expected_python_executable = str(
        Path("/tmp/test-venv/bin/python").resolve(),
    )
    expected_environment_root = str(Path("/tmp/test-venv").resolve())
    expected_package_dir = str(
        Path(update_cmd_module.__file__).resolve().parent.parent,
    )

    monkeypatch.setattr(
        update_cmd_module.metadata,
        "distribution",
        lambda name: _FakeDistribution(),
    )
    monkeypatch.setattr(
        update_cmd_module.sys,
        "executable",
        "/tmp/test-venv/bin/python",
    )
    monkeypatch.setattr(update_cmd_module.sys, "prefix", "/tmp/test-venv")
    monkeypatch.setattr(update_cmd_module.sys, "base_prefix", "/usr/local")

    result = _detect_installation()

    assert result.installer == expected_installer
    assert result.source_type == expected_source_type
    assert result.source_url == expected_source_url
    assert result.python_executable == expected_python_executable
    assert result.environment_root == expected_environment_root
    assert result.environment_kind == "virtualenv"
    assert result.package_dir == expected_package_dir


def test_update_reports_up_to_date(monkeypatch) -> None:
    from copaw.cli import update_cmd as update_cmd_module

    install_info = _install_info()

    def _detect_installation() -> InstallInfo:
        return install_info

    def _fetch_latest_version() -> str:
        return __version__

    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        _detect_installation,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        _fetch_latest_version,
    )

    result = CliRunner().invoke(cli, ["update", "--yes"])

    assert result.exit_code == 0
    assert "CoPaw is already up to date." in result.output


def test_update_blocks_running_service(monkeypatch) -> None:
    from copaw.cli import update_cmd as update_cmd_module

    install_info = _install_info()

    def _detect_installation() -> InstallInfo:
        return install_info

    def _fetch_latest_version() -> str:
        return "9.9.9"

    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        _detect_installation,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        _fetch_latest_version,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_running_service",
        lambda host, port: RunningServiceInfo(
            is_running=True,
            base_url="http://127.0.0.1:8088",
            version=__version__,
        ),
    )

    result = CliRunner().invoke(cli, ["update", "--yes"])

    assert result.exit_code != 0
    assert "Please stop it before running `copaw update`." in result.output


def test_update_can_cancel_non_pypi_override(monkeypatch) -> None:
    from copaw.cli import update_cmd as update_cmd_module

    install_info = _install_info(source_type="editable")

    def _detect_installation() -> InstallInfo:
        return install_info

    def _fetch_latest_version() -> str:
        return "9.9.9"

    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        _detect_installation,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        _fetch_latest_version,
    )

    result = CliRunner().invoke(cli, ["update"], input="n\n")

    assert result.exit_code == 0
    assert "Detected a non-PyPI installation source: editable" in result.output
    assert "Continue and replace the current installation" in result.output
    assert "Cancelled." in result.output


def test_update_can_override_non_pypi_install_with_yes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from copaw.cli import update_cmd as update_cmd_module

    spawned: dict[str, object] = {}
    install_info = _install_info(source_type="editable")

    def _detect_installation() -> InstallInfo:
        return install_info

    def _fetch_latest_version() -> str:
        return "9.9.9"

    def _detect_running_service(
        host: str | None,
        port: int | None,
    ) -> RunningServiceInfo:
        del host, port
        return RunningServiceInfo(is_running=False)

    monkeypatch.setattr(update_cmd_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        _detect_installation,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        _fetch_latest_version,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_running_service",
        _detect_running_service,
    )

    def _fake_spawn(plan_path: Path) -> None:
        spawned["path"] = plan_path
        spawned["plan"] = json.loads(plan_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(update_cmd_module, "_spawn_update_worker", _fake_spawn)

    result = CliRunner().invoke(cli, ["update", "--yes"])

    assert result.exit_code == 0
    assert "Proceeding because `--yes` was provided." in result.output
    assert "Update process started in a separate process." in result.output
    assert isinstance(spawned["path"], Path)


def test_update_spawns_worker(monkeypatch, tmp_path: Path) -> None:
    from copaw.cli import update_cmd as update_cmd_module

    spawned: dict[str, object] = {}
    install_info = _install_info()

    def _detect_installation() -> InstallInfo:
        return install_info

    def _fetch_latest_version() -> str:
        return "9.9.9"

    def _detect_running_service(
        host: str | None,
        port: int | None,
    ) -> RunningServiceInfo:
        del host, port
        return RunningServiceInfo(is_running=False)

    monkeypatch.setattr(update_cmd_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        _detect_installation,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        _fetch_latest_version,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_running_service",
        _detect_running_service,
    )

    def _fake_spawn(plan_path: Path) -> None:
        spawned["path"] = plan_path
        spawned["plan"] = json.loads(plan_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(update_cmd_module, "_spawn_update_worker", _fake_spawn)

    result = CliRunner().invoke(cli, ["update", "--yes"])

    assert result.exit_code == 0
    assert "Update process started in a separate process." in result.output
    assert isinstance(spawned["path"], Path)
    plan = spawned["plan"]
    assert plan["latest_version"] == "9.9.9"  # type: ignore [index]
    assert plan["installer_label"] == "pip"  # type: ignore [index]
    assert plan["command"][:5] == [  # type: ignore [index]
        "/tmp/venv/bin/python",
        "-m",
        "pip",
        "install",
        "--upgrade",
    ]


def test_update_prompts_when_version_is_not_comparable(
    monkeypatch,
) -> None:
    from copaw.cli import update_cmd as update_cmd_module

    install_info = _install_info()

    def _detect_installation() -> InstallInfo:
        return install_info

    def _fetch_latest_version() -> str:
        return "main"

    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        _detect_installation,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        _fetch_latest_version,
    )

    result = CliRunner().invoke(cli, ["update"], input="n\n")

    assert result.exit_code == 0
    assert "Unable to compare the current version" in result.output
    assert "Cancelled." in result.output


def test_update_can_continue_when_version_is_not_comparable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from copaw.cli import update_cmd as update_cmd_module

    spawned: dict[str, object] = {}
    install_info = _install_info()

    def _detect_installation() -> InstallInfo:
        return install_info

    def _fetch_latest_version() -> str:
        return "main"

    def _detect_running_service(
        host: str | None,
        port: int | None,
    ) -> RunningServiceInfo:
        del host, port
        return RunningServiceInfo(is_running=False)

    monkeypatch.setattr(update_cmd_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        _detect_installation,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        _fetch_latest_version,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_running_service",
        _detect_running_service,
    )

    def _fake_spawn(plan_path: Path) -> None:
        spawned["path"] = plan_path
        spawned["plan"] = json.loads(plan_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(update_cmd_module, "_spawn_update_worker", _fake_spawn)

    result = CliRunner().invoke(cli, ["update"], input="y\ny\n")

    assert result.exit_code == 0
    assert isinstance(spawned["path"], Path)
    assert "Update process started in a separate process." in result.output
