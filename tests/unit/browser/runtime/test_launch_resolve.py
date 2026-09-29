# -*- coding: utf-8 -*-
"""Tests for ``qwenpaw.browser.runtime.launch_resolve``."""

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.browser.runtime.launch_resolve import resolve_launch


def _config(**overrides):
    values = {
        "headless": "auto",
        "engine": "auto",
        "executable_path": None,
        "channel": None,
        "use_system_default": True,
        "args": [],
        "ignore_default_args": [],
        "viewport": None,
        "proxy": None,
        "user_data_dir": None,
        "backend": "auto",
        "cdp_url": None,
        "cdp_port": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _resolve(config):
    return resolve_launch(
        config,
        in_container=False,
        has_display=True,
        system_default=("chromium", "/usr/bin/chromium"),
        bundled_path="/opt/qwenpaw/chromium",
    )


def test_ignore_default_args_defaults_to_empty():
    assert not _resolve(_config())["ignore_default_args"]


def test_ignore_default_args_is_forwarded():
    launch = _resolve(
        _config(ignore_default_args=["--disable-extensions"]),
    )
    assert launch["ignore_default_args"] == ["--disable-extensions"]


def test_ignore_default_args_is_copied_not_aliased():
    switches = ["--disable-extensions"]
    config = _config(ignore_default_args=switches)
    launch = _resolve(config)

    launch["ignore_default_args"].append("--disable-sync")

    # Mutating the resolved spec must not reach back into the config.
    assert switches == ["--disable-extensions"]
    assert config.ignore_default_args == ["--disable-extensions"]


def test_ignore_default_args_survives_alongside_args():
    launch = _resolve(
        _config(
            args=["--window-size=1280,720"],
            ignore_default_args=["--disable-extensions"],
        ),
    )
    assert launch["args"] == ["--window-size=1280,720"]
    assert launch["ignore_default_args"] == ["--disable-extensions"]
