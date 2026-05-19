# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import os
import sys
import types

import click
import pytest

from qwenpaw.tauri import entry
from qwenpaw.tauri.env import DESKTOP_CORS_ORIGINS_ENV


def test_install_desktop_runtime_preserves_existing_cors_values(monkeypatch):
    monkeypatch.setenv(
        DESKTOP_CORS_ORIGINS_ENV,
        "https://example.test,tauri://localhost",
    )

    entry._install_desktop_runtime()

    origins = os.environ[DESKTOP_CORS_ORIGINS_ENV].split(",")
    assert origins.count("tauri://localhost") == 1
    assert "https://example.test" in origins
    assert "http://127.0.0.1:1420" in origins


def test_ensure_qwenpaw_app_not_loaded_rejects_late_cors(monkeypatch):
    monkeypatch.setitem(sys.modules, "qwenpaw.app._app", object())

    with pytest.raises(RuntimeError, match="desktop CORS origins"):
        entry._ensure_qwenpaw_app_not_loaded()


def test_sync_loaded_qwenpaw_constant_cors_origins(monkeypatch):
    constant_module = types.SimpleNamespace(CORS_ORIGINS="")
    monkeypatch.setitem(sys.modules, "qwenpaw.constant", constant_module)
    monkeypatch.setenv(DESKTOP_CORS_ORIGINS_ENV, "tauri://localhost")

    entry._sync_loaded_qwenpaw_constant_cors_origins()

    assert constant_module.CORS_ORIGINS == "tauri://localhost"


def test_run_click_command_wraps_click_exception(capsys):
    @click.command()
    def command():
        raise click.ClickException("bad input")

    with pytest.raises(
        RuntimeError,
        match="desktop initialization failed",
    ) as exc_info:
        entry._run_click_command(command, [], "initialization")

    captured = capsys.readouterr()
    assert "bad input" in captured.err
    assert isinstance(exc_info.value.__cause__, click.ClickException)


def test_run_click_command_wraps_click_abort(capsys):
    @click.command()
    def command():
        raise click.Abort()

    with pytest.raises(
        RuntimeError,
        match="desktop initialization aborted",
    ) as exc_info:
        entry._run_click_command(command, [], "initialization")

    captured = capsys.readouterr()
    assert "aborted" in captured.err
    assert isinstance(exc_info.value.__cause__, click.Abort)


def test_run_click_command_wraps_system_exit(capsys):
    @click.command()
    def command():
        raise SystemExit(7)

    with pytest.raises(
        RuntimeError,
        match="desktop backend startup exited",
    ) as exc_info:
        entry._run_click_command(command, [], "backend startup")

    captured = capsys.readouterr()
    assert "code 7" in captured.err
    assert isinstance(exc_info.value.__cause__, SystemExit)
