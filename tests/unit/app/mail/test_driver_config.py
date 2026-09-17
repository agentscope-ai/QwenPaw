# -*- coding: utf-8 -*-
from __future__ import annotations

import sys

import pytest
import yaml

from qwenpaw.app.mail import driver_config


@pytest.mark.parametrize(
    ("backend_name", "cli_name"),
    [
        ("qwenpaw-backend", "qwenpaw"),
        ("qwenpaw-backend.exe", "qwenpaw.exe"),
    ],
)
def test_driver_card_uses_bundled_cli_when_frozen(
    tmp_path,
    monkeypatch,
    backend_name,
    cli_name,
):
    monkeypatch.delenv("QWENPAWMAIL_PYTHON", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / backend_name))

    assert driver_config.generate_qwenpawmail_driver_card(tmp_path)

    card_path = tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml"
    card = yaml.safe_load(card_path.read_text(encoding="utf-8"))
    assert card["endpoint"]["command"] == str(tmp_path / cli_name)
    assert card["endpoint"]["args"] == ["--internal-mail-mcp"]


def test_frozen_driver_card_preserves_python_override(monkeypatch):
    monkeypatch.setenv("QWENPAWMAIL_PYTHON", "/custom/bin/python")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    command, args = driver_config.resolve_qwenpawmail_endpoint()

    assert command == "/custom/bin/python"
    assert args == ["-m", "qwenpawmail_mcp"]
