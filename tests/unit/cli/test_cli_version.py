# -*- coding: utf-8 -*-
from click.testing import CliRunner

from qwenpaw.__version__ import __version__, get_qwenpaw_compat_label
from qwenpaw.cli.main import cli


def test_cli_version_option_outputs_current_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_get_qwenpaw_compat_label_maps_to_major_x() -> None:
    assert get_qwenpaw_compat_label("1.1.12") == "1.x"
    assert get_qwenpaw_compat_label("2.0.0b1") == "2.x"
    assert get_qwenpaw_compat_label("2.1.0.post2") == "2.x"


def test_get_qwenpaw_compat_label_defaults_to_current_version() -> None:
    label = get_qwenpaw_compat_label()
    assert label.endswith(".x")
    assert label == f"{__version__.split('.', 1)[0]}.x"


def test_get_qwenpaw_compat_label_handles_empty_and_none() -> None:
    # Empty/None inputs fall back to the current version.
    assert get_qwenpaw_compat_label("") == get_qwenpaw_compat_label()
    assert get_qwenpaw_compat_label(None) == get_qwenpaw_compat_label()
