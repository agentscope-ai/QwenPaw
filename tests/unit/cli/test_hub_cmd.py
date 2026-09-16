# -*- coding: utf-8 -*-
"""CLI tests for the QwenPaw Hub command."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from qwenpaw.cli.app_cmd import app_cmd
from qwenpaw.cli.hub_cmd import hub_cmd
from qwenpaw.cli.main import cli


def test_hub_dispatches_to_control_plane() -> None:
    with patch("qwenpaw.hub.control_app.run_hub_app") as run_hub:
        result = CliRunner().invoke(
            hub_cmd,
            ["--host", "127.0.0.1", "--port", "9090"],
        )

    assert result.exit_code == 0
    run_hub.assert_called_once_with(
        host="127.0.0.1",
        port=9090,
        log_level="info",
        config_path=None,
        force_public=False,
    )


def test_hub_passes_config_path(tmp_path) -> None:
    config_path = tmp_path / "hub.yaml"
    config_path.write_text("version: 1", encoding="utf-8")
    with patch("qwenpaw.hub.control_app.run_hub_app") as run_hub:
        result = CliRunner().invoke(
            hub_cmd,
            ["--config", str(config_path)],
        )

    assert result.exit_code == 0
    assert run_hub.call_args.kwargs["config_path"] == config_path


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_hub_requires_force_public_for_non_loopback(host: str) -> None:
    result = CliRunner().invoke(hub_cmd, ["--host", host])

    assert result.exit_code != 0
    assert "Use --force-public" in result.output


def test_hub_forwards_force_public() -> None:
    with patch("qwenpaw.hub.control_app.run_hub_app") as run_hub:
        result = CliRunner().invoke(
            hub_cmd,
            ["--host", "::", "--force-public"],
        )

    assert result.exit_code == 0
    assert run_hub.call_args.kwargs["host"] == "::"
    assert run_hub.call_args.kwargs["force_public"] is True


def test_hub_initializes_admin_without_starting_server() -> None:
    with (
        patch("qwenpaw.hub.bootstrap.ensure_admin_initialization_available"),
        patch(
            "qwenpaw.hub.bootstrap.initialize_hub_admin",
        ) as initialize_admin,
    ):
        initialize_admin.return_value.username = "owner"
        result = CliRunner().invoke(
            hub_cmd,
            ["--init-admin", "owner"],
            input="safe-password\nsafe-password\n",
        )

    assert result.exit_code == 0
    initialize_admin.assert_called_once_with("owner", "safe-password")
    assert "initialized" in result.output


def test_hub_initialization_does_not_load_runtime_provisioners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner_modules = (
        "qwenpaw.hub.provisioner",
        "qwenpaw.hub.local_provisioner",
        "qwenpaw.hub.docker_provisioner",
        "qwenpaw.hub.docker_images",
    )
    for module_name in provisioner_modules:
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    with (
        patch("qwenpaw.hub.bootstrap.ensure_admin_initialization_available"),
        patch(
            "qwenpaw.hub.bootstrap.initialize_hub_admin",
        ) as initialize_admin,
    ):
        initialize_admin.return_value.username = "owner"
        result = CliRunner().invoke(
            hub_cmd,
            ["--init-admin", "owner"],
            input="safe-password\nsafe-password\n",
        )

    assert result.exit_code == 0
    assert all(name not in sys.modules for name in provisioner_modules)


def test_hub_reports_existing_admin_during_initialization() -> None:
    with (
        patch(
            "qwenpaw.hub.bootstrap.ensure_admin_initialization_available",
            side_effect=PermissionError("Hub is already initialized."),
        ),
        patch(
            "qwenpaw.hub.bootstrap.initialize_hub_admin",
        ) as initialize_admin,
    ):
        result = CliRunner().invoke(
            hub_cmd,
            ["--init-admin", "owner"],
        )

    assert result.exit_code != 0
    assert "already initialized" in result.output
    assert "Administrator password" not in result.output
    initialize_admin.assert_not_called()


def test_hub_rejects_init_admin_with_server_options() -> None:
    result = CliRunner().invoke(
        hub_cmd,
        ["--init-admin", "owner", "--host", "0.0.0.0"],
    )

    assert result.exit_code != 0
    assert "cannot be combined with --host" in result.output
    assert "Administrator password" not in result.output


def test_app_rejects_removed_pro_option() -> None:
    result = CliRunner().invoke(app_cmd, ["--pro"])

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert "--pro" in result.output


def test_hub_is_registered_at_root() -> None:
    result = CliRunner().invoke(cli, ["hub", "--help"])

    assert result.exit_code == 0
    assert "Run the multi-user QwenPaw Hub control plane" in result.output


def test_hub_starts_local_without_docker_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for module_name in (
        "qwenpaw.hub.control_app",
        "qwenpaw.hub.docker_images",
        "qwenpaw.hub.docker_provisioner",
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setitem(sys.modules, "docker", None)
    monkeypatch.setenv("QWENPAW_HUB_DIR", str(tmp_path))

    with patch("qwenpaw.hub.control_app.uvicorn.run") as uvicorn_run:
        result = CliRunner().invoke(hub_cmd, [])

    assert result.exit_code == 0
    uvicorn_run.assert_called_once()
    app = uvicorn_run.call_args.args[0]
    docker_status = app.state.runtime_service.provisioner_statuses()["docker"]
    assert docker_status["available"] is False
    assert "qwenpaw[hub]" in str(docker_status["reason"])
