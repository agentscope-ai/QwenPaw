# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import os
import socket
import sys
import types

import click
import pytest

from qwenpaw.tauri import entry
from qwenpaw.tauri.env import DESKTOP_CORS_ORIGINS_ENV, DESKTOP_READY_PREFIX


def test_install_desktop_runtime_preserves_existing_cors_values(monkeypatch):
    monkeypatch.setenv(
        DESKTOP_CORS_ORIGINS_ENV,
        "https://example.test,tauri://localhost",
    )

    entry._install_desktop_runtime()

    origins = os.environ[DESKTOP_CORS_ORIGINS_ENV].split(",")
    assert origins.count("tauri://localhost") == 1
    assert "https://example.test" in origins
    assert "http://127.0.0.1:5173" not in origins


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


def test_install_certifi_env_sets_bundle_paths(monkeypatch, tmp_path):
    cert_file = tmp_path / "cacert.pem"
    cert_file.write_text("test cert", encoding="utf-8")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "certifi",
        types.SimpleNamespace(where=lambda: str(cert_file)),
    )

    entry._install_certifi_env()

    assert os.environ["SSL_CERT_FILE"] == str(cert_file)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(cert_file)
    assert os.environ["CURL_CA_BUNDLE"] == str(cert_file)


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


def test_run_click_command_allows_successful_system_exit(capsys):
    @click.command()
    def command():
        raise SystemExit(0)

    entry._run_click_command(command, [], "backend startup")

    captured = capsys.readouterr()
    assert captured.err == ""


def test_emit_backend_ready_writes_stdout_protocol(capsys):
    entry._emit_backend_ready(54321)

    captured = capsys.readouterr()
    assert captured.out == f'{DESKTOP_READY_PREFIX} {{"port":54321}}\n'


def test_socket_port_returns_bound_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))

        assert entry._socket_port(sock) == sock.getsockname()[1]
