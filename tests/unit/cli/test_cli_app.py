# -*- coding: utf-8 -*-
import os

import pytest
from click.testing import CliRunner

from qwenpaw.cli import app_cmd as app_cmd_module
from qwenpaw.config import utils as config_utils
from qwenpaw.desktop_env import DESKTOP_PORT_ENV


@pytest.fixture(autouse=True)
def clear_runtime_api_env(monkeypatch):
    for name in (
        config_utils.RUNTIME_API_HOST_ENV,
        config_utils.RUNTIME_API_PORT_ENV,
        config_utils.RUNTIME_API_INTERNAL_ENV,
        DESKTOP_PORT_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def test_app_cmd_sets_runtime_api_without_persisting_last_api(monkeypatch):
    runtime_calls = []
    last_api_calls = []
    uvicorn_calls = []

    monkeypatch.setenv(DESKTOP_PORT_ENV, "19088")
    monkeypatch.setattr(
        app_cmd_module,
        "set_runtime_api",
        lambda host, port: runtime_calls.append((host, port)),
    )
    monkeypatch.setattr(
        app_cmd_module,
        "write_last_api",
        lambda host, port: last_api_calls.append((host, port)),
    )
    monkeypatch.setattr(
        app_cmd_module.uvicorn,
        "run",
        lambda *args, **kwargs: uvicorn_calls.append((args, kwargs)),
    )

    result = CliRunner().invoke(
        app_cmd_module.app_cmd,
        ["--host", "0.0.0.0", "--port", "19088", "--no-write-last-api"],
    )

    assert result.exit_code == 0
    assert runtime_calls == [("127.0.0.1", 19088)]
    assert not last_api_calls
    assert uvicorn_calls[0][1]["host"] == "0.0.0.0"
    assert uvicorn_calls[0][1]["port"] == 19088


def test_app_cmd_rejects_runtime_api_outside_desktop(monkeypatch):
    def fail_uvicorn(*args, **kwargs):
        raise AssertionError("uvicorn should not start")

    monkeypatch.setattr(
        app_cmd_module.uvicorn,
        "run",
        fail_uvicorn,
    )

    result = CliRunner().invoke(
        app_cmd_module.app_cmd,
        ["--port", "19088", "--no-write-last-api"],
    )

    assert result.exit_code != 0
    assert "only for desktop sidecar startup" in result.output


def test_app_cmd_hides_runtime_api_option_from_help():
    result = CliRunner().invoke(app_cmd_module.app_cmd, ["--help"])

    assert result.exit_code == 0
    assert "--no-write-last-api" not in result.output


def test_app_cmd_clears_runtime_api_after_sidecar_exit(monkeypatch):
    def fail_write_last_api(host, port):
        raise AssertionError("write_last_api should not be called")

    monkeypatch.setenv(DESKTOP_PORT_ENV, "19088")
    monkeypatch.setattr(
        app_cmd_module,
        "write_last_api",
        fail_write_last_api,
    )
    monkeypatch.setattr(
        app_cmd_module.uvicorn,
        "run",
        lambda *args, **kwargs: None,
    )

    result = CliRunner().invoke(
        app_cmd_module.app_cmd,
        ["--host", "127.0.0.1", "--port", "19088", "--no-write-last-api"],
    )

    assert result.exit_code == 0
    assert config_utils.read_runtime_api() is None


def test_app_cmd_persists_last_api_by_default(monkeypatch):
    runtime_calls = []
    last_api_calls = []

    monkeypatch.setattr(
        app_cmd_module,
        "set_runtime_api",
        lambda host, port: runtime_calls.append((host, port)),
    )
    monkeypatch.setattr(
        app_cmd_module,
        "write_last_api",
        lambda host, port: last_api_calls.append((host, port)),
    )
    monkeypatch.setattr(
        app_cmd_module.uvicorn,
        "run",
        lambda *args, **kwargs: None,
    )

    result = CliRunner().invoke(
        app_cmd_module.app_cmd,
        ["--host", "127.0.0.1", "--port", "18088"],
    )

    assert result.exit_code == 0
    # Default path: persist to disk, do NOT write env
    assert not runtime_calls
    assert last_api_calls == [("127.0.0.1", 18088)]


def test_read_last_api_prefers_runtime_api(monkeypatch):
    def fail_load_config():
        raise AssertionError("load_config called")

    monkeypatch.setenv(config_utils.RUNTIME_API_HOST_ENV, "127.0.0.1")
    monkeypatch.setenv(config_utils.RUNTIME_API_PORT_ENV, "19088")
    monkeypatch.setenv(config_utils.RUNTIME_API_INTERNAL_ENV, "1")
    monkeypatch.setattr(config_utils, "load_config", fail_load_config)

    assert config_utils.read_last_api() == ("127.0.0.1", 19088)


def test_read_runtime_api_ignores_env_without_sentinel(monkeypatch):
    """Without the internal sentinel, shell-exported host/port must be ignored."""
    monkeypatch.setenv(config_utils.RUNTIME_API_HOST_ENV, "127.0.0.1")
    monkeypatch.setenv(config_utils.RUNTIME_API_PORT_ENV, "19088")
    monkeypatch.delenv(config_utils.RUNTIME_API_INTERNAL_ENV, raising=False)

    assert config_utils.read_runtime_api() is None


def test_set_runtime_api_overwrites_previous_env(monkeypatch):
    """set_runtime_api should overwrite existing env values."""
    monkeypatch.setenv(config_utils.RUNTIME_API_HOST_ENV, "127.0.0.1")
    monkeypatch.setenv(config_utils.RUNTIME_API_PORT_ENV, "8000")
    monkeypatch.setenv(config_utils.RUNTIME_API_INTERNAL_ENV, "1")

    config_utils.set_runtime_api("127.0.0.1", 9999)

    assert config_utils.read_runtime_api() == ("127.0.0.1", 9999)


def test_clear_runtime_api_removes_runtime_env(monkeypatch):
    config_utils.set_runtime_api("127.0.0.1", 9999)

    config_utils.clear_runtime_api()

    assert config_utils.read_runtime_api() is None
    assert config_utils.RUNTIME_API_HOST_ENV not in os.environ
