# -*- coding: utf-8 -*-
"""Managed environment commands update the runtime, never local files."""

import httpx
import pytest
from click.testing import CliRunner

from qwenpaw.cli import env_cmd, plugin_commands


@pytest.fixture
def managed(monkeypatch):
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "user-runtime")
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "internal")
    monkeypatch.setenv("QWENPAW_RUNTIME_API_URL", "http://127.0.0.1:9001")
    monkeypatch.setenv("QWENPAW_RUNTIME_PROVISIONER", "local")


@pytest.mark.usefixtures("managed")
def test_managed_env_set_uses_runtime_api(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=[{"key": "MY_VALUE", "value": "new"}])

    monkeypatch.setattr(
        env_cmd,
        "api_client",
        lambda url: httpx.Client(
            base_url=url,
            transport=httpx.MockTransport(respond),
        ),
    )

    def no_local_store(*_args):
        pytest.fail("Managed CLI must not access the local env store")

    for name in ("load_envs", "set_env_var", "delete_env_var"):
        monkeypatch.setattr(env_cmd, name, no_local_store)
    result = CliRunner().invoke(env_cmd.env_group, ["set", "MY_VALUE", "new"])
    assert result.exit_code == 0, result.output
    assert len(requests) == 1
    assert requests[0].method == "PATCH"
    assert requests[0].url.host == "127.0.0.1"
    assert requests[0].url.port == 9001


@pytest.mark.usefixtures("managed")
def test_managed_env_does_not_fall_back_when_unreachable(monkeypatch):
    def unavailable(request):
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(
        env_cmd,
        "api_client",
        lambda url: httpx.Client(
            base_url=url,
            transport=httpx.MockTransport(unavailable),
        ),
    )
    result = CliRunner().invoke(env_cmd.env_group, ["set", "MY_VALUE", "new"])
    assert result.exit_code != 0
    assert "offline" in result.output


@pytest.mark.usefixtures("managed")
def test_managed_plugin_does_not_use_offline_install(monkeypatch):
    monkeypatch.setattr(plugin_commands, "read_runtime_api", lambda: None)
    result = CliRunner().invoke(
        plugin_commands.plugin,
        ["install", "https://example.test/app.zip"],
    )
    assert result.exit_code != 0
    assert "endpoint is unavailable" in result.output
