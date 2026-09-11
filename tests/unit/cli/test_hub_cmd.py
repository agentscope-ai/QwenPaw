# -*- coding: utf-8 -*-
"""CLI tests for the QwenPaw Hub command."""

import sys
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


def test_app_rejects_removed_pro_option() -> None:
    result = CliRunner().invoke(app_cmd, ["--pro"])

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert "--pro" in result.output


def test_hub_is_registered_at_root() -> None:
    result = CliRunner().invoke(cli, ["hub", "--help"])

    assert result.exit_code == 0
    assert "Run the multi-user QwenPaw Hub control plane" in result.output


def test_hub_reports_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for module_name in (
        "qwenpaw.hub.control_app",
        "qwenpaw.hub.docker_images",
        "qwenpaw.hub.docker_provisioner",
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setitem(sys.modules, "docker", None)

    result = CliRunner().invoke(hub_cmd, [])

    assert result.exit_code != 0
    assert "Install qwenpaw[hub]" in result.output
