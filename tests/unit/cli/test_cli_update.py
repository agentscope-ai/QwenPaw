# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from qwenpaw.__version__ import __version__
from qwenpaw.cli.main import cli
from qwenpaw.cli.update_cmd import (
    InstallInfo,
    RunningServiceInfo,
    _detect_running_service,
    _detect_installation,
    _is_newer_version,
    _probe_service,
    _detect_source_type,
    _run_update_worker_detached,
    _run_update_worker_foreground,
    run_update_worker,
)


def _install_info(
    *,
    source_type: str = "pypi",
    installer: str = "pip",
) -> InstallInfo:
    return InstallInfo(
        package_dir="/tmp/site-packages/qwenpaw",
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
                "url": "file:///Users/test/QwenPaw",
                "dir_info": {"editable": True},
            },
            ("editable", "file:///Users/test/QwenPaw"),
        ),
        (
            {
                "url": "https://github.com/agentscope-ai/QwenPaw.git",
                "vcs_info": {"vcs": "git", "commit_id": "abc123"},
            },
            ("vcs", "https://github.com/agentscope-ai/QwenPaw.git"),
        ),
        (
            {"url": "file:///tmp/qwenpaw.whl"},
            ("local", "file:///tmp/qwenpaw.whl"),
        ),
        (
            {"url": "https://example.com/qwenpaw.whl"},
            ("direct-url", "https://example.com/qwenpaw.whl"),
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
                    "url": "file:///Users/test/QwenPaw",
                    "dir_info": {"editable": True},
                },
            ),
            "uv",
            "editable",
            "file:///Users/test/QwenPaw",
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
    from qwenpaw.cli import update_cmd as update_cmd_module

    class _FakeDistribution:
        def read_text(self, name: str) -> str | None:
            mapping = {
                "INSTALLER": installer_text,
                "direct_url.json": direct_url_text,
            }
            return mapping.get(name)

    expected_python_executable = "/tmp/test-venv/bin/python"
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
    from qwenpaw.cli import update_cmd as update_cmd_module

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
    assert "QwenPaw is already up to date." in result.output


def test_probe_service_ignores_proxy_env(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"version": "1.2.3"}

    def _fake_get(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("qwenpaw.cli.update_cmd.httpx.get", _fake_get)

    result = _probe_service("http://127.0.0.1:8088")

    assert result.is_running is True
    assert result.base_url == "http://127.0.0.1:8088"
    assert result.version == "1.2.3"
    assert captured["trust_env"] is False


def test_probe_service_returns_not_running_on_http_error(monkeypatch) -> None:
    def _fake_get(_url: str, **_kwargs):
        raise httpx.HTTPError("bad gateway")

    monkeypatch.setattr("qwenpaw.cli.update_cmd.httpx.get", _fake_get)

    result = _probe_service("http://127.0.0.1:8088")

    assert result.is_running is False


def test_detect_running_service_handles_wildcard_host(monkeypatch) -> None:
    from qwenpaw.cli import update_cmd as update_cmd_module

    monkeypatch.setattr(update_cmd_module, "read_last_api", lambda: None)
    monkeypatch.setattr(
        update_cmd_module,
        "_probe_service",
        lambda base_url: RunningServiceInfo(
            is_running=base_url == "http://127.0.0.1:9090",
            base_url=base_url if base_url == "http://127.0.0.1:9090" else None,
        ),
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_running_service_from_processes",
        lambda _hosts: RunningServiceInfo(is_running=False),
    )

    result = _detect_running_service("0.0.0.0", 9090)

    assert result.is_running is True
    assert result.base_url == "http://127.0.0.1:9090"


def test_detect_running_service_falls_back_to_process_ports(
    monkeypatch,
) -> None:
    from qwenpaw.cli import update_cmd as update_cmd_module

    monkeypatch.setattr(update_cmd_module, "read_last_api", lambda: None)
    monkeypatch.setattr(
        update_cmd_module,
        "_probe_service",
        lambda _base_url: RunningServiceInfo(is_running=False),
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_running_service_from_processes",
        lambda hosts: RunningServiceInfo(
            is_running=True,
            base_url=f"http://{hosts[0]}:8088",
        ),
    )

    result = _detect_running_service(None, None)

    assert result.is_running is True
    assert result.base_url == "http://127.0.0.1:8088"


def test_update_blocks_running_service(monkeypatch) -> None:
    from qwenpaw.cli import update_cmd as update_cmd_module

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
    assert "Please stop it before running `qwenpaw update`" in result.output
    assert (
        "without `--yes` to confirm a forced `qwenpaw shutdown`"
        in result.output
    )


def test_update_can_cancel_forced_shutdown(monkeypatch) -> None:
    from qwenpaw.cli import update_cmd as update_cmd_module

    install_info = _install_info()

    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        lambda: install_info,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        lambda: "9.9.9",
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

    result = CliRunner().invoke(cli, ["update"], input="n\n")

    assert result.exit_code == 0
    assert (
        "forcibly terminate the current QwenPaw backend/frontend "
        "processes" in result.output
    )
    assert (
        "Run `qwenpaw shutdown` now and continue with the update?"
        in result.output
    )
    assert "Cancelled." in result.output


def test_update_can_force_shutdown_running_service(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.cli import update_cmd as update_cmd_module

    install_info = _install_info()
    spawned: dict[str, object] = {}
    service_checks = iter(
        [
            RunningServiceInfo(
                is_running=True,
                base_url="http://127.0.0.1:8088",
                version=__version__,
            ),
            RunningServiceInfo(is_running=False),
        ],
    )

    monkeypatch.setattr(update_cmd_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(update_cmd_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        lambda: install_info,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        lambda: "9.9.9",
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_running_service",
        lambda host, port: next(service_checks),
    )

    def _fake_shutdown(
        command,
        stdout,
        stderr,
        text,
        encoding,
        errors,
        check,
    ):
        del stdout, stderr, text, encoding, errors, check
        assert command == [
            "/tmp/venv/bin/python",
            "-m",
            "qwenpaw",
            "--port",
            "8088",
            "shutdown",
        ]

        class _Result:
            returncode = 0
            stdout = "Stopped QwenPaw processes: 1234\n"

        return _Result()

    def _fake_run_worker(plan_path: Path) -> int:
        spawned["path"] = plan_path
        spawned["plan"] = json.loads(plan_path.read_text(encoding="utf-8"))
        return 0

    monkeypatch.setattr(update_cmd_module.subprocess, "run", _fake_shutdown)
    monkeypatch.setattr(
        update_cmd_module,
        "_run_update_worker_foreground",
        _fake_run_worker,
    )

    result = CliRunner().invoke(cli, ["update"], input="y\ny\n")

    assert result.exit_code == 0
    assert "Running `qwenpaw shutdown` before updating..." in result.output
    assert "Stopped QwenPaw processes: 1234" in result.output
    assert "Starting QwenPaw update..." in result.output
    assert isinstance(spawned["path"], Path)


def test_update_can_cancel_non_pypi_override(monkeypatch) -> None:
    from qwenpaw.cli import update_cmd as update_cmd_module

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
    from qwenpaw.cli import update_cmd as update_cmd_module

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
    monkeypatch.setattr(update_cmd_module.sys, "platform", "darwin")
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

    def _fake_run_worker(plan_path: Path) -> int:
        spawned["path"] = plan_path
        spawned["plan"] = json.loads(plan_path.read_text(encoding="utf-8"))
        return 0

    monkeypatch.setattr(
        update_cmd_module,
        "_run_update_worker_foreground",
        _fake_run_worker,
    )

    result = CliRunner().invoke(cli, ["update", "--yes"])

    assert result.exit_code == 0
    assert "Proceeding because `--yes` was provided." in result.output
    assert "Starting QwenPaw update..." in result.output
    assert isinstance(spawned["path"], Path)


def test_update_spawns_worker(monkeypatch, tmp_path: Path) -> None:
    from qwenpaw.cli import update_cmd as update_cmd_module

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
    monkeypatch.setattr(update_cmd_module.sys, "platform", "darwin")
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

    def _fake_run_worker(plan_path: Path) -> int:
        spawned["path"] = plan_path
        spawned["plan"] = json.loads(plan_path.read_text(encoding="utf-8"))
        return 0

    monkeypatch.setattr(
        update_cmd_module,
        "_run_update_worker_foreground",
        _fake_run_worker,
    )

    result = CliRunner().invoke(cli, ["update", "--yes"])

    assert result.exit_code == 0
    assert "Starting QwenPaw update..." in result.output
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
    from qwenpaw.cli import update_cmd as update_cmd_module

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
    from qwenpaw.cli import update_cmd as update_cmd_module

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
    monkeypatch.setattr(update_cmd_module.sys, "platform", "darwin")
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

    def _fake_run_worker(plan_path: Path) -> int:
        spawned["path"] = plan_path
        spawned["plan"] = json.loads(plan_path.read_text(encoding="utf-8"))
        return 0

    monkeypatch.setattr(
        update_cmd_module,
        "_run_update_worker_foreground",
        _fake_run_worker,
    )

    result = CliRunner().invoke(cli, ["update"], input="y\ny\n")

    assert result.exit_code == 0
    assert isinstance(spawned["path"], Path)
    assert "Starting QwenPaw update..." in result.output


def test_update_returns_worker_exit_code(monkeypatch, tmp_path: Path) -> None:
    from qwenpaw.cli import update_cmd as update_cmd_module

    install_info = _install_info()

    monkeypatch.setattr(update_cmd_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(update_cmd_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        lambda: install_info,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        lambda: "9.9.9",
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_running_service",
        lambda host, port: RunningServiceInfo(is_running=False),
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_run_update_worker_foreground",
        lambda plan_path: 2,
    )

    result = CliRunner().invoke(cli, ["update", "--yes"])

    assert result.exit_code == 2
    assert "Starting QwenPaw update..." in result.output


def test_update_detaches_worker_on_windows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.cli import update_cmd as update_cmd_module

    install_info = _install_info()
    spawned: dict[str, object] = {}

    monkeypatch.setattr(update_cmd_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(update_cmd_module.sys, "platform", "win32")
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_installation",
        lambda: install_info,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_fetch_latest_version",
        lambda: "9.9.9",
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_detect_running_service",
        lambda host, port: RunningServiceInfo(is_running=False),
    )

    def _fake_run_detached(plan_path: Path) -> None:
        spawned["path"] = plan_path
        spawned["plan"] = json.loads(plan_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        update_cmd_module,
        "_run_update_worker_detached",
        _fake_run_detached,
    )
    monkeypatch.setattr(
        update_cmd_module,
        "_run_update_worker_foreground",
        lambda plan_path: pytest.fail("foreground worker should not run"),
    )

    result = CliRunner().invoke(cli, ["update", "--yes"])

    assert result.exit_code == 0
    assert "Starting QwenPaw update..." in result.output
    assert "continue after this command exits" in result.output
    assert isinstance(spawned["path"], Path)
    assert spawned["plan"]["launcher_pid"] is not None  # type: ignore[index]


def test_update_worker_waits_for_launcher_exit(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    plan_path = tmp_path / "update-plan-wait.json"
    _write_plan(
        plan_path,
        command=[
            sys.executable,
            "-u",
            "-c",
            "print('installer: done', flush=True)",
        ],
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["launcher_pid"] = 4321
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    waited: list[tuple[int | None, float]] = []
    monkeypatch.setattr(
        "qwenpaw.cli.update_cmd._wait_for_process_exit",
        lambda pid, timeout=15.0: waited.append((pid, timeout)),
    )

    return_code = run_update_worker(plan_path)
    captured = capsys.readouterr()

    assert return_code == 0
    assert waited == [(4321, 15.0)]
    assert "installer: done" in captured.out


def test_run_update_worker_detached_spawns_without_capture(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _fake_spawn(plan_path: Path, *, capture_output: bool = True):
        captured["path"] = plan_path
        captured["capture_output"] = capture_output
        return object()

    monkeypatch.setattr(
        "qwenpaw.cli.update_cmd._spawn_update_worker",
        _fake_spawn,
    )

    plan_path = tmp_path / "update-plan.json"
    plan_path.write_text("{}", encoding="utf-8")

    _run_update_worker_detached(plan_path)

    assert captured == {
        "path": plan_path,
        "capture_output": False,
    }


def _write_plan(
    plan_path: Path,
    *,
    command: list[str],
    current_version: str = "1.0.0",
    latest_version: str = "9.9.9",
) -> None:
    plan = {
        "current_version": current_version,
        "latest_version": latest_version,
        "installer_label": "integration-test",
        "command": command,
        "install": {},
    }
    plan_path.write_text(json.dumps(plan), encoding="utf-8")


def test_update_worker_foreground_streams_output_and_cleans_plan(
    tmp_path: Path,
    capsys,
) -> None:
    """Test that the foreground worker streams child output and cleans up."""
    plan_path = tmp_path / "update-plan.json"
    _write_plan(
        plan_path,
        command=[
            sys.executable,
            "-u",
            "-c",
            (
                "print('installer: preparing', flush=True);"
                "print('installer: done', flush=True)"
            ),
        ],
    )

    return_code = _run_update_worker_foreground(plan_path)
    captured = capsys.readouterr()

    assert return_code == 0
    assert "[qwenpaw] Updating QwenPaw 1.0.0 -> 9.9.9..." in captured.out
    assert "[qwenpaw] Using installer: integration-test" in captured.out
    assert "installer: preparing" in captured.out
    assert "installer: done" in captured.out
    assert "[qwenpaw] Update completed successfully." in captured.out
    assert not plan_path.exists()


def test_update_worker_foreground_propagates_failure_exit_code(
    tmp_path: Path,
    capsys,
) -> None:
    """Test that the foreground worker returns the installer exit code."""
    plan_path = tmp_path / "update-plan-fail.json"
    _write_plan(
        plan_path,
        command=[
            sys.executable,
            "-u",
            "-c",
            (
                "import sys;"
                "print('installer: failing', flush=True);"
                "sys.exit(7)"
            ),
        ],
    )

    return_code = _run_update_worker_foreground(plan_path)
    captured = capsys.readouterr()

    assert return_code == 7
    assert "installer: failing" in captured.out
    assert "[qwenpaw] Update failed with exit code 7." in captured.out
    assert not plan_path.exists()
