# -*- coding: utf-8 -*-
from importlib.metadata import version as package_version

from packaging.version import Version

from click.testing import CliRunner

from qwenpaw.__version__ import __version__
from qwenpaw.cli.main import cli


def test_cli_version_option_outputs_current_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_click_version_is_supported_for_lazy_group_parser() -> None:
    click_version = Version(package_version("click"))

    assert Version("8.1") <= click_version < Version("9")
