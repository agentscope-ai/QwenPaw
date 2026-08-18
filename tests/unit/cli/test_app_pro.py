# -*- coding: utf-8 -*-
"""CLI tests for the QwenPaw Pro app mode."""

from unittest.mock import patch

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
    )


def test_app_pro_rejects_reload() -> None:
    result = CliRunner().invoke(app_cmd, ["--pro", "--reload"])

    assert result.exit_code != 0
    assert "--reload is not supported with --pro" in result.output
