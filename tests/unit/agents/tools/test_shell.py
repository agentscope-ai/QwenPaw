# -*- coding: utf-8 -*-
"""Tests for shell tool command preprocessing."""

import sys

import pytest

from qwenpaw.agents.tools import shell
from qwenpaw.agents.tools.shell import (
    _collapse_embedded_newlines,
    execute_shell_command,
)


def test_unix_preserves_comment_prefixed_multiline_command(monkeypatch):
    monkeypatch.setattr(shell.sys, "platform", "linux")

    command = "# inspect workspace\nprintf qwenpaw-ok"

    assert _collapse_embedded_newlines(command) == command


def test_unix_preserves_sequential_multiline_command(monkeypatch):
    monkeypatch.setattr(shell.sys, "platform", "linux")

    command = 'cd /tmp\nprintf "%s" "qwenpaw-ok"'

    assert _collapse_embedded_newlines(command) == command


def test_unix_normalizes_crlf_without_flattening_command_separator(
    monkeypatch,
):
    monkeypatch.setattr(shell.sys, "platform", "linux")

    command = "# inspect workspace\r\nprintf qwenpaw-ok"

    assert (
        _collapse_embedded_newlines(command)
        == "# inspect workspace\nprintf qwenpaw-ok"
    )


def test_unix_normalizes_lone_carriage_return(monkeypatch):
    monkeypatch.setattr(shell.sys, "platform", "linux")

    command = "# inspect workspace\rprintf qwenpaw-ok"

    assert (
        _collapse_embedded_newlines(command)
        == "# inspect workspace\nprintf qwenpaw-ok"
    )


def test_windows_still_collapses_newlines(monkeypatch):
    monkeypatch.setattr(shell.sys, "platform", "win32")

    command = "# inspect workspace\nprintf qwenpaw-ok"

    assert (
        _collapse_embedded_newlines(command)
        == "# inspect workspace printf qwenpaw-ok"
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="This verifies Unix shell newline separator behavior.",
)
async def test_execute_shell_command_runs_comment_prefixed_multiline(tmp_path):
    response = await execute_shell_command(
        "# inspect workspace\nprintf qwenpaw-ok",
        cwd=tmp_path,
    )

    assert response.content[0].text == "qwenpaw-ok"
