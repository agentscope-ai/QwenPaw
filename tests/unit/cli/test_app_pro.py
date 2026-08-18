# -*- coding: utf-8 -*-
"""CLI tests for the QwenPaw Pro app mode."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from qwenpaw.cli.app_cmd import app_cmd


def test_app_pro_dispatches_to_control_plane() -> None:
    with patch("qwenpaw.pro.control_app.run_pro_app") as run_pro:
        result = CliRunner().invoke(
            app_cmd,
            ["--pro", "--host", "127.0.0.1", "--port", "9090"],
        )

    assert result.exit_code == 0
    run_pro.assert_called_once_with(
        host="127.0.0.1",
        port=9090,
        log_level="info",
        config_path=None,
        force_public=False,
    )


def test_app_pro_rejects_reload() -> None:
    result = CliRunner().invoke(app_cmd, ["--pro", "--reload"])

    assert result.exit_code != 0
    assert "--reload is not supported with --pro" in result.output


def test_app_pro_passes_config_path(tmp_path) -> None:
    config_path = tmp_path / "pro.yaml"
    config_path.write_text("version: 1", encoding="utf-8")
    with patch("qwenpaw.pro.control_app.run_pro_app") as run_pro:
        result = CliRunner().invoke(
            app_cmd,
            ["--pro", "--config", str(config_path)],
        )

    assert result.exit_code == 0
    assert run_pro.call_args.kwargs["config_path"] == config_path


def test_app_config_requires_pro(tmp_path) -> None:
    config_path = tmp_path / "pro.yaml"
    config_path.write_text("version: 1", encoding="utf-8")

    result = CliRunner().invoke(
        app_cmd,
        ["--config", str(config_path)],
    )

    assert result.exit_code != 0
    assert "--config is only supported with --pro" in result.output


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_app_pro_requires_force_public_for_non_loopback(host: str) -> None:
    result = CliRunner().invoke(
        app_cmd,
        ["--pro", "--host", host],
    )

    assert result.exit_code != 0
    assert "Use --force-public" in result.output


def test_app_pro_forwards_force_public() -> None:
    with patch("qwenpaw.pro.control_app.run_pro_app") as run_pro:
        result = CliRunner().invoke(
            app_cmd,
            ["--pro", "--host", "::", "--force-public"],
        )

    assert result.exit_code == 0
    assert run_pro.call_args.kwargs["host"] == "::"
    assert run_pro.call_args.kwargs["force_public"] is True


def test_force_public_requires_pro() -> None:
    result = CliRunner().invoke(app_cmd, ["--force-public"])

    assert result.exit_code != 0
    assert "--force-public is only supported with --pro" in result.output
