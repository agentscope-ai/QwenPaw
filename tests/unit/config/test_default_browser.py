# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.config.utils import _exec_executable_token


@pytest.mark.parametrize(
    "exec_value, expected",
    [
        # Plain executable (most common, freedesktop default).
        ("/usr/bin/google-chrome-stable %U", "/usr/bin/google-chrome-stable"),
        ("firefox %u", "firefox"),
        # `env VAR=val /path` wrapper — produced by IME setups such as
        # ibus/fcitx; the real binary must be returned instead of `env`.
        (
            "env GTK_IM_MODULE=ibus QT_IM_MODULE=ibus "
            "/usr/bin/google-chrome-stable %U",
            "/usr/bin/google-chrome-stable",
        ),
        # `env` with no assignments, and the absolute /usr/bin/env form.
        ("env /usr/bin/firefox", "/usr/bin/firefox"),
        (
            "/usr/bin/env VAR=1 /opt/google/chrome/chrome",
            "/opt/google/chrome/chrome",
        ),
        # Quoted path with spaces.
        ('"/home/u/My Apps/Chrome" %U', "/home/u/My Apps/Chrome"),
    ],
)
def test_exec_executable_token(exec_value: str, expected: str) -> None:
    assert _exec_executable_token(exec_value) == expected


def test_exec_executable_token_only_assignments_returns_none() -> None:
    # `env VAR=val` with no command should not be mistaken for a browser.
    assert _exec_executable_token("env GTK_IM_MODULE=ibus") is None
