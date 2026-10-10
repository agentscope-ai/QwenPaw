# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from unittest.mock import patch

from qwenpaw.tauri import cli_entry


def test_internal_mail_mcp_dispatch_does_not_start_click(monkeypatch):
    monkeypatch.setattr(
        cli_entry.sys,
        "argv",
        ["qwenpaw", "--internal-mail-mcp"],
    )
    monkeypatch.delitem(sys.modules, "qwenpaw.cli.main", raising=False)

    with patch("qwenpawmail_mcp.__main__.main") as mail_mcp_main:
        cli_entry.main()

    mail_mcp_main.assert_called_once_with()
    assert "qwenpaw.cli.main" not in sys.modules


def test_other_arguments_start_click(monkeypatch):
    monkeypatch.setattr(cli_entry.sys, "argv", ["qwenpaw", "--version"])

    with patch("qwenpaw.cli.main.cli") as cli:
        cli_entry.main()

    cli.assert_called_once_with()
