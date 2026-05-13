# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import os
import sys

import click
import pytest

from qwenpaw import desktop_entry
from qwenpaw.desktop_env import DESKTOP_CORS_ORIGINS_ENV


def test_ensure_desktop_cors_origins_preserves_existing_values(monkeypatch):
    monkeypatch.setenv(
        DESKTOP_CORS_ORIGINS_ENV,
        "https://example.test,tauri://localhost",
    )

    desktop_entry._ensure_desktop_cors_origins()

    origins = os.environ[DESKTOP_CORS_ORIGINS_ENV].split(",")
    assert origins.count("tauri://localhost") == 1
    assert "https://example.test" in origins
    assert "http://127.0.0.1:1420" in origins


def test_ensure_qwenpaw_constant_not_loaded_rejects_late_cors(monkeypatch):
    monkeypatch.setitem(sys.modules, "qwenpaw.constant", object())

    with pytest.raises(RuntimeError, match="desktop CORS origins"):
        desktop_entry._ensure_qwenpaw_constant_not_loaded()


def test_run_click_command_wraps_click_exception(capsys):
    @click.command()
    def command():
        raise click.ClickException("bad input")

    with pytest.raises(
        RuntimeError,
        match="desktop initialization failed",
    ) as exc_info:
        desktop_entry._run_click_command(command, [], "initialization")

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
        desktop_entry._run_click_command(command, [], "initialization")

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
        desktop_entry._run_click_command(command, [], "backend startup")

    captured = capsys.readouterr()
    assert "code 7" in captured.err
    assert isinstance(exc_info.value.__cause__, SystemExit)
