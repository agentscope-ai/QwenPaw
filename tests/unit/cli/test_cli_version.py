# -*- coding: utf-8 -*-
from click.testing import CliRunner

from qwenpaw.__version__ import __version__
from qwenpaw.cli.main import cli


def test_cli_version_option_outputs_current_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output
