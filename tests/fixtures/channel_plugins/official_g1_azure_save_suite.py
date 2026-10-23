"""Real schema-only Azure HTTP editing with isolated persistent files."""

import asyncio
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest
import pytest_asyncio

import official_g1_suite as core

registry = core.registry
saved_host = core.saved_host


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True).encode()
    ).hexdigest()


@pytest_asyncio.fixture
async def azure_api(saved_host, registry, tmp_path, monkeypatch, request):
    from qwenpaw.app.multi_agent_manager import MultiAgentManager
    from qwenpaw.app.routers import config as routes
    from qwenpaw.app.workspace import Workspace
    from qwenpaw.config.config import (
        AgentProfileConfig,
        Config,
        load_agent_config,
        save_agent_config,
    )
    from qwenpaw.config.utils import get_plugins_dir, save_config
    from qwenpaw.plugins.official_channels import bundled_channel_source

    mode = getattr(request, "param", "missing_code")
    workspace_path = tmp_path / "workspace"
    save_config(
        Config(
            agents={
                "active_agent": "azure-form",
                "profiles": {
                    "azure-form": {
                        "id": "azure-form",
                        "workspace_dir": str(workspace_path),
                    }
                },
            },
            plugins={"azure-bot": {"enabled": False}},
        )
    )
    if mode == "disabled":
        with bundled_channel_source("azure-bot") as source:
            shutil.copytree(source, get_plugins_dir() / "azure-bot")
    else:
        assert not (get_plugins_dir() / "azure-bot").exists()
    profile = AgentProfileConfig(
        id="azure-form",
        name="Retain this profile",
        channels={
            "azure_bot": {
                "enabled": False,
                "app_id": "old-test-app",
                "app_password": "old-test-only-password",
                "tenant_id": "test-tenant",
                "bot_prefix": "old-prefix",
                "media_dir": "saved-media",
            },
            "removed-plugin": {"enabled": False, "custom": {"keep": [1]}},
        },
    )
    save_agent_config("azure-form", profile)
    workspace = Workspace("azure-form", str(workspace_path))
    manager = MultiAgentManager()
    manager.agents[workspace.agent_id] = workspace
    reloads = []
    monkeypatch.setattr(
        routes,
        "schedule_agent_reload",
        lambda _request, agent_id: reloads.append(agent_id),
    )
    attempts = []
    blocked = (
        "qwenpaw_channel_azure_bot",
        "botbuilder",
        "azure.identity",
        "msal",
    )

    class NoAzureRuntime(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if any(
                fullname == name or fullname.startswith(name + ".")
                for name in blocked
            ):
                attempts.append(fullname)
                raise AssertionError("schema-only API imported " + fullname)

    async def no_spawn(*_args, **_kwargs):
        attempts.append("subprocess")
        raise AssertionError("schema-only API spawned a worker")

    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in sys.modules
        for prefix in blocked
    )
    monkeypatch.setattr(sys, "meta_path", [NoAzureRuntime(), *sys.meta_path])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_spawn)
    app = FastAPI()
    app.include_router(routes.router)
    app.state.multi_agent_manager = manager
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://schema-only.test",
        headers={"X-Agent-Id": workspace.agent_id},
    ) as client:
        yield SimpleNamespace(
            client=client,
            mode=mode,
            agent_file=workspace_path / "agent.json",
            root_file=saved_host,
            load=lambda: load_agent_config(workspace.agent_id),
            reloads=reloads,
            attempts=attempts,
            registry=registry,
            workspace=workspace,
            proof=Path(os.environ["TMPDIR"])
            / ("azure-schema-api-" + request.node.name + ".json"),
        )
    assert attempts == []
    assert workspace.channel_manager is None
    assert registry.get_registered_channels() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "azure_api", ["missing_code", "disabled"], indirect=True
)
async def test_actual_azure_schema_only_api_saves_and_reads_back(azure_api):
    api = azure_api
    before = api.load().model_dump(mode="json")
    before_bytes = api.agent_file.read_bytes()
    root_bytes = api.root_file.read_bytes()
    schemas = await api.client.get("/config/channels/schemas")
    assert schemas.status_code == 200
    metadata = schemas.json()["azure_bot"]
    assert metadata["owner"] == metadata["plugin_id"] == "azure-bot"
    assert metadata["availability"] == api.mode
    assert metadata["repair"] == {
        "action": "install" if api.mode == "missing_code" else "enable",
        "plugin_id": "azure-bot",
        "source": "bundled:azure-bot",
    }
    descriptor = json.loads(
        (core.ROOT / "plugins/channel/azure_bot/channel.json").read_text()
    )
    assert metadata["config_schema"] == descriptor["config_schema"]
    read = await api.client.get("/config/channels/azure_bot")
    assert read.status_code == 200
    initial = before["channels"]["azure_bot"]
    diagnostic = {
        "saved_keys": sorted(initial),
        "http_keys": sorted(read.json()),
        "missing_keys": sorted(set(initial) - set(read.json())),
        "added_keys": sorted(set(read.json()) - set(initial)),
        "changed_keys": sorted(
            key
            for key in set(initial) | set(read.json())
            if key not in initial
            or key not in read.json()
            or digest(initial[key]) != digest(read.json()[key])
        ),
    }
    api.proof.write_text(json.dumps(diagnostic, indent=2))
    assert digest(read.json()) == digest(initial), json.dumps(diagnostic)
    proposed = {
        **read.json(),
        "app_id": "updated-test-app",
        "app_password": "updated-test-only-password",
        "http_port": 43978,
        "bot_prefix": "new-prefix",
    }
    response = await api.client.put(
        "/config/channels/azure_bot", json=proposed
    )
    assert response.status_code == 200
    assert digest(response.json()["app_password"]) == digest(
        proposed["app_password"]
    )
    after = api.load().model_dump(mode="json")
    persisted = json.loads(api.agent_file.read_text())
    assert digest(after["channels"]["azure_bot"]) == digest(response.json())
    assert digest(persisted["channels"]["azure_bot"]) == digest(
        response.json()
    )
    assert digest(after["channels"]["removed-plugin"]) == digest(
        before["channels"]["removed-plugin"]
    )
    assert after["name"] == before["name"]
    assert after["channels"]["azure_bot"]["media_dir"] == "saved-media"
    assert after["channels"]["azure_bot"]["http_port"] == 43978
    assert api.agent_file.read_bytes() != before_bytes
    assert api.root_file.read_bytes() == root_bytes
    reread = await api.client.get("/config/channels/azure_bot")
    assert reread.status_code == 200
    assert digest(reread.json()) == digest(response.json())
    assert api.reloads == ["azure-form"]
    assert api.attempts == []
    api.proof.write_text(
        json.dumps(
            {
                "mode": api.mode,
                "statuses": [
                    schemas.status_code,
                    read.status_code,
                    response.status_code,
                    reread.status_code,
                ],
                "agent_before_sha256": hashlib.sha256(
                    before_bytes
                ).hexdigest(),
                "agent_after_sha256": hashlib.sha256(
                    api.agent_file.read_bytes()
                ).hexdigest(),
                "root_unchanged": api.root_file.read_bytes() == root_bytes,
                "runtime_imports_or_spawns": api.attempts,
            },
            indent=2,
        )
    )


@pytest.mark.asyncio
async def test_console_typed_model_get_put_preserves_its_own_json(azure_api):
    from qwenpaw.config.config import ConsoleConfig

    api = azure_api
    model = api.workspace.config.channels.console
    assert isinstance(model, ConsoleConfig)
    before = model.model_dump(mode="json")
    response = await api.client.get("/config/channels/console")
    assert response.status_code == 200
    assert response.json() == before
    proposed = {**before, "bot_prefix": "typed-console", "media_dir": "media"}
    expected = ConsoleConfig.model_validate(proposed).model_dump(mode="json")
    root_bytes = api.root_file.read_bytes()
    put = await api.client.put("/config/channels/console", json=proposed)
    assert put.status_code == 200
    assert put.json() == expected
    assert api.load().channels.console.model_dump(mode="json") == expected
    assert json.loads(api.agent_file.read_text())["channels"]["console"] == (
        expected
    )
    reread = await api.client.get("/config/channels/console")
    assert reread.status_code == 200
    assert reread.json() == expected
    assert api.root_file.read_bytes() == root_bytes
    assert api.reloads == ["azure-form"]


@pytest.mark.asyncio
async def test_third_party_raw_nested_json_get_put_is_not_platform_coerced(
    azure_api, tmp_path
):
    from qwenpaw.config.config import (
        BaseChannelConfig,
        ChannelConfig,
        save_agent_config,
    )
    from qwenpaw.plugins.channel_adapter import describe_channel

    api = azure_api
    source, manifest = core.channel_source(tmp_path / "third-party")
    descriptor_file = source / "channel.json"
    descriptor = json.loads(descriptor_file.read_text())
    descriptor["config_schema"]["properties"]["options"] = {
        "type": "object",
        "properties": {
            "rows": {"type": "array"},
            "nested": {"type": "object"},
        },
        "additionalProperties": False,
    }
    descriptor["config_fields"] = list(
        descriptor["config_schema"]["properties"]
    )
    descriptor_file.write_text(json.dumps(descriptor))
    api.registry.register_channel_descriptor(
        manifest.id, describe_channel(source, manifest)
    )
    raw = {
        "enabled": False,
        "api_token": "synthetic-nested-test-only",
        "options": {
            "rows": [1, "one", False, None, {"unicode": "文本"}],
            "nested": {"list": [{"number": 1.25}], "empty": {}},
        },
    }
    candidate = api.load()
    channels = candidate.channels.model_dump(mode="json")
    candidate.channels = ChannelConfig.model_validate(
        {**channels, "new_delivery": raw}
    )
    save_agent_config("azure-form", candidate)
    root_bytes = api.root_file.read_bytes()
    read = await api.client.get("/config/channels/new_delivery")
    assert read.status_code == 200
    assert digest(read.json()) == digest(raw)
    proposed = {**raw, "options": {**raw["options"], "rows": [None, True, 2]}}
    response = await api.client.put(
        "/config/channels/new_delivery", json=proposed
    )
    assert response.status_code == 200
    actual = response.json()
    assert actual["options"] == proposed["options"]
    assert digest(actual["api_token"]) == digest(raw["api_token"])
    expected = {**BaseChannelConfig().model_dump(mode="json"), **proposed}
    assert digest(actual) == digest(expected)
    assert digest(api.load().channels.model_dump()["new_delivery"]) == digest(
        actual
    )
    persisted = json.loads(api.agent_file.read_text())["channels"][
        "new_delivery"
    ]
    assert digest(persisted) == digest(actual)
    reread = await api.client.get("/config/channels/new_delivery")
    assert reread.status_code == 200
    assert digest(reread.json()) == digest(actual)
    assert api.root_file.read_bytes() == root_bytes
    assert api.reloads == ["azure-form"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"http_port": "3978"}, {"app_id": {}}])
async def test_actual_azure_schema_rejects_bad_types_without_writing(
    azure_api, bad
):
    api = azure_api
    original = await api.client.get("/config/channels/azure_bot")
    assert original.status_code == 200
    root_bytes = api.root_file.read_bytes()
    agent_bytes = api.agent_file.read_bytes()
    response = await api.client.put(
        "/config/channels/azure_bot", json={**original.json(), **bad}
    )
    assert response.status_code == 422
    assert api.root_file.read_bytes() == root_bytes
    assert api.agent_file.read_bytes() == agent_bytes
    assert api.reloads == []
    assert api.attempts == []
    reread = await api.client.get("/config/channels/azure_bot")
    assert reread.status_code == 200
    assert digest(reread.json()) == digest(original.json())
    api.proof.write_text(
        json.dumps(
            {
                "bad_field": next(iter(bad)),
                "status": response.status_code,
                "agent_unchanged": api.agent_file.read_bytes() == agent_bytes,
                "root_unchanged": api.root_file.read_bytes() == root_bytes,
                "runtime_imports_or_spawns": api.attempts,
            },
            indent=2,
        )
    )
