# -*- coding: utf-8 -*-
# Pytest fixture injection and real boundary-state checks are intentional.
# pylint: disable=unused-argument
# pylint: disable=redefined-outer-name
# pylint: disable=protected-access
"""G1/G2 boundaries: generic data validation and three independent gates."""

import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.channel_adapter import (
    ChannelRuntimeSettings,
    describe_channel,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = {
    "type": "object",
    "properties": {
        "enabled": {"type": "boolean", "default": False},
        "api_token": {"type": "string", "default": ""},
        "rooms": {"type": "array", "items": {"type": "string"}, "default": []},
        "options": {
            "type": "object",
            "default": {},
            "properties": {
                "retries": {"type": "integer", "minimum": 0, "default": 3},
                "headers": {"type": "object", "default": {"X-Test": "yes"}},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


def sample_plugin(tmp_path, key="sample_chat", *, schema=None):
    """A parameterized descriptor with no official platform dependencies."""
    root = tmp_path / key
    root.mkdir(parents=True)
    data = {
        "id": key,
        "version": "1.0.0",
        "name": "Sample Chat",
        "type": "channel",
        "entry": {"descriptor": "channel.json"},
    }
    schema = SCHEMA if schema is None else schema
    descriptor = {
        "schema_version": 2,
        "channel_key": key,
        "label": {"en": "Sample Chat", "zh": "测试聊天"},
        "process_mode": "runner_process",
        "dependency_mode": "shared",
        "entrypoint": {
            "scope": "runner",
            "module": key + ".driver",
            "qualname": "Driver",
        },
        "requirements_file": "requirements.txt",
        "config_schema": deepcopy(schema),
        "config_fields": list(schema["properties"]),
        "capabilities": ["channel.generic.v1"],
    }
    (root / "plugin.json").write_text(json.dumps(data))
    (root / "channel.json").write_text(json.dumps(descriptor))
    (root / "requirements.txt").write_text("")
    package = root / key
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "driver.py").write_text(
        "raise AssertionError('static access imported driver')\n",
    )
    return root, PluginManifest.from_dict(data)


@pytest.fixture
def registry():
    from qwenpaw.plugins.registry import PluginRegistry

    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        yield PluginRegistry()
    finally:
        PluginRegistry._instance = previous


def runtime(selection=frozenset()):
    return ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version="2.2.2b4",
        selected_channels=selection,
    )


def config_api():
    module = importlib.import_module("qwenpaw.plugins.channel_config")
    return module.validate_channel_config, module.channel_config_defaults


async def unused_process(_request):
    raise AssertionError("Configuration started Agent processing")
    # Preserve async-generator shape for the ProcessHandler contract.
    # pylint: disable-next=unreachable
    yield


@pytest.mark.parametrize(
    "selection,expected",
    [
        (None, True),
        (frozenset(), False),
        (frozenset({"sample_chat"}), True),
        (frozenset({"feishu"}), False),
    ],
)
def test_deployment_selection_accepts_generic_keys_and_preserves_empty_deny(
    selection,
    expected,
):
    assert runtime(selection).allows("sample_chat") is expected


def test_default_policy_denies_until_host_explicitly_selects():
    assert runtime().allows("sample_chat") is False


def test_schema_defaults_are_recursive_and_detached():
    validate, defaults = config_api()
    first = defaults(SCHEMA)
    assert first["options"] == {"retries": 3, "headers": {"X-Test": "yes"}}
    first["options"]["headers"]["X-Test"] = "changed"
    first["rooms"].append("other")
    second = validate(SCHEMA, {"options": {"retries": 7}})
    assert second["rooms"] == []
    assert second["options"] == {"retries": 7, "headers": {"X-Test": "yes"}}
    # Exact mapping assertion rejects falsey values of the wrong type.
    # pylint: disable-next=use-implicit-booleaness-not-comparison
    assert SCHEMA["properties"]["options"]["default"] == {}


@pytest.mark.parametrize(
    "bad",
    [
        {"options": {"retries": "3"}},
        {"rooms": [9]},
        {"options": {"retries": -1}},
        {"surprise": 1},
    ],
)
def test_plugin_schema_rejects_bad_types_and_forbidden_unknowns(bad):
    validate, _ = config_api()
    with pytest.raises(ValueError):
        validate(SCHEMA, bad)


@pytest.mark.parametrize(
    "bad",
    [
        {"enabled": "not-bool"},
        {"allow_from": 1},
        {"dm_policy": "unsafe"},
        {"tool_result_max_length": -1},
    ],
)
def test_plugin_schema_cannot_relax_host_controls(bad):
    validate, _ = config_api()
    with pytest.raises(ValueError):
        validate(
            {"type": "object", "properties": {}, "additionalProperties": True},
            bad,
        )


def test_public_fields_keep_existing_normalization_and_open_schema_extras():
    validate, _ = config_api()
    values = validate(
        {"type": "object", "properties": {}, "additionalProperties": True},
        {
            "enabled": "true",
            "tool_call_max_length": "0",
            "custom": {"items": [1]},
        },
    )
    assert values["enabled"] is True and values["tool_call_max_length"] == 0
    assert values["custom"] == {"items": [1]}
    assert values["dm_policy"] == "open" and values["allow_from"] == []


def test_network_schema_references_fail_without_resolution(monkeypatch):
    validate, _ = config_api()
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Schema validation used network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    with pytest.raises(ValueError):
        validate(
            {
                "type": "object",
                "properties": {
                    "remote": {"$ref": "https://schemas.invalid/channel"},
                },
            },
            {"remote": {}},
        )


def test_draft_202012_local_reference_validation():
    validate, _ = config_api()
    schema = {
        "type": "object",
        "$defs": {"count": {"type": "integer", "minimum": 1}},
        "properties": {"count": {"$ref": "#/$defs/count"}},
    }
    assert validate(schema, {"count": 2})["count"] == 2
    with pytest.raises(ValueError):
        validate(schema, {"count": 0})


@pytest.mark.parametrize("shape", ["dict", "model", "namespace"])
def test_generic_factory_retains_nested_values_without_sdk_or_spawn(
    tmp_path,
    monkeypatch,
    shape,
):
    source, manifest = sample_plugin(tmp_path)
    description = describe_channel(source, manifest)
    values = {
        "enabled": True,
        "api_token": "test-token",
        "rooms": ["room-A"],
        "options": {"retries": 5},
    }

    class Options(BaseModel):
        retries: int

    class Settings(BaseModel):
        enabled: bool
        api_token: str
        rooms: list[str]
        options: Options

    config = {
        "dict": values,
        "model": Settings(**values),
        "namespace": NS(**{**values, "options": NS(retries=5)}),
    }[shape]

    async def forbidden(*args, **kwargs):
        raise AssertionError("Factory spawned Driver")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    proxy = description.create_proxy(
        unused_process,
        config,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="sample-instance",
        generation=1,
        qwenpaw_version="2.2.2b4",
        workspace_dir=tmp_path / "workspace",
    )
    values["rooms"].append("later")
    assert proxy._launch_spec.config["rooms"] == ["room-A"]
    assert proxy._launch_spec.config["options"] == {
        "retries": 5,
        "headers": {"X-Test": "yes"},
    }
    assert proxy._launch_spec.config["api_token"] == "test-token"
    assert proxy.channel_process.health_snapshot()["pid"] is None
    assert not (tmp_path / "workspace").exists()


async def load_sample(
    tmp_path,
    registry,
    selection=None,
    enabled=True,
    key="sample_chat",
    schema=None,
):
    """Use Loader's public discovery/lifecycle, never private owner tables."""
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    source, manifest = sample_plugin(
        tmp_path / "installed",
        key,
        schema=schema,
    )
    loader = PluginLoader([source.parent], channel_runtime=runtime(selection))
    loader.registry.projector = WorkspaceProjector(live_workspaces=lambda: [])
    record = await loader.load_plugin(
        manifest,
        source,
        {"enabled": enabled},
        activate=False,
    )
    return loader, record


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selection,enabled,state",
    [
        (None, True, "validation_pending"),
        (frozenset(), True, "missing_runtime"),
        (None, False, "disabled"),
    ],
)
async def test_generic_catalog_reports_gate_state_and_static_defaults(
    tmp_path,
    registry,
    selection,
    enabled,
    state,
):
    from qwenpaw.app.channels.catalog import get_configurable_channel_catalog

    loader, record = await load_sample(tmp_path, registry, selection, enabled)
    row = get_configurable_channel_catalog()["sample_chat"]
    assert record.status != "failed"
    assert row["owner"] == "sample_chat" and row["form_kind"] == "schema"
    assert row["process_mode"] == "runner_process"
    assert row["global_enabled"] is enabled and row["availability"] == state
    assert row["defaults"]["options"] == {
        "retries": 3,
        "headers": {"X-Test": "yes"},
    }
    assert not str(row.get("repair", {}).get("source", "")).startswith(
        "bundled:",
    )
    assert (
        loader.registry.get_channel_catalog_entry(
            "sample_chat",
        ).description_record
        is not None
    )
    assert "sample_chat.driver" not in sys.modules


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selection,global_enabled,workspace_enabled,installed",
    [
        (None, False, True, True),
        (None, True, False, True),
        (frozenset(), True, True, True),
        (None, True, True, False),
    ],
)
async def test_generic_manager_enforces_all_gates_before_factory(
    tmp_path,
    registry,
    monkeypatch,
    selection,
    global_enabled,
    workspace_enabled,
    installed,
):
    from qwenpaw.app.channels.manager import instantiate_channel
    from qwenpaw.plugins.channel_adapter import ChannelDescription

    if installed:
        await load_sample(tmp_path, registry, selection, global_enabled)

    def forbidden(*args, **kwargs):
        raise AssertionError("A closed gate reached the Driver factory")

    monkeypatch.setattr(ChannelDescription, "create_proxy", forbidden)
    config = NS(channels=NS(sample_chat={"enabled": workspace_enabled}))
    with pytest.raises(RuntimeError, match="CHANNEL_UNAVAILABLE"):
        instantiate_channel(
            "sample_chat",
            config,
            process=unused_process,
            workspace_dir=tmp_path / "workspace",
        )


@pytest.mark.asyncio
async def test_real_manager_namespace_construction_preserves_generic_nested_data(  # noqa: E501
    tmp_path,
    registry,
):
    from qwenpaw.app.channels.manager import (
        channel_cfg_for_key,
        instantiate_channel,
    )
    from qwenpaw.config.config import ChannelConfig
    from qwenpaw.app.channels.registry import selected_process_channels
    from qwenpaw.config.utils import get_available_channels

    await load_sample(tmp_path, registry)
    config = NS(
        channels=ChannelConfig.model_validate(
            {
                "sample_chat": {
                    "enabled": True,
                    "api_token": "test-manager",
                    "no_text_debounce": "false",
                    "rooms": ["room-A"],
                    "options": {"retries": 4},
                },
            },
        ),
    )
    assert isinstance(channel_cfg_for_key(config, "sample_chat"), NS)
    assert "sample_chat" in selected_process_channels()
    assert "sample_chat" in get_available_channels()
    proxy = instantiate_channel(
        "sample_chat",
        config,
        process=unused_process,
        workspace_dir=tmp_path / "workspace",
    )
    assert proxy._launch_spec.config["api_token"] == "test-manager"
    assert proxy._launch_spec.config["no_text_debounce"] is False
    assert proxy._launch_spec.config["options"] == {
        "retries": 4,
        "headers": {"X-Test": "yes"},
    }
    assert proxy.channel_process.health_snapshot()["pid"] is None


@pytest.mark.asyncio
async def test_disabled_descriptor_reserves_key_against_same_name_legacy_class(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.app.channels import registry as channels

    await load_sample(tmp_path, registry, frozenset(), False)

    class Legacy:
        pass

    monkeypatch.setattr(
        channels,
        "_get_plugin_channels",
        lambda: {"sample_chat": Legacy},
    )
    assert "sample_chat" in channels.selected_process_channels()
    assert "sample_chat" not in channels.get_channel_registry()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["console"])
async def test_generic_loader_rejects_protected_builtin_name(
    tmp_path,
    registry,
    key,
):
    from qwenpaw.plugins.loader import PluginLoader

    source, manifest = sample_plugin(tmp_path / "installed", key)
    loader = PluginLoader([source.parent], channel_runtime=runtime(None))
    with pytest.raises(ValueError, match="owner 'builtin' conflicts"):
        await loader.load_plugin(
            manifest, source, {"enabled": True}, activate=False
        )
    assert registry.get_channel_catalog_entry(key) is None
    assert loader.get_loaded_plugin(key) is None
    assert key + ".driver" not in sys.modules
    assert (source / "driver.py").exists() is False


@pytest.mark.asyncio
async def test_generic_loader_rejects_other_owner_claiming_official_slack_key(
    tmp_path, registry
):
    from qwenpaw.plugins.loader import PluginLoader

    source, manifest = sample_plugin(tmp_path / "installed", "intruder")
    path = source / "channel.json"
    descriptor = json.loads(path.read_text())
    descriptor["channel_key"] = "slack"
    path.write_text(json.dumps(descriptor))
    loader = PluginLoader([source.parent], channel_runtime=runtime(None))
    with pytest.raises(
        ValueError,
        match="Channel 'slack' owner 'slack' conflicts with plugin 'intruder'",
    ):
        await loader.load_plugin(
            manifest, source, {"enabled": True}, activate=False
        )
    assert registry.get_channel_catalog_entry("slack") is None
    assert registry.get_channel_catalog_entry("intruder") is None
    assert loader.get_loaded_plugin("intruder") is None
    assert registry.runtime_owners.leases("intruder") == ()
    assert "intruder.driver" not in sys.modules


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_generic_loader_accepts_official_slack_same_owner_without_import(
    tmp_path, registry, enabled, monkeypatch
):
    from qwenpaw.plugins.loader import PluginLoader

    async def forbidden(*args, **kwargs):
        raise AssertionError("Static admission launched a worker")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    source, manifest = sample_plugin(tmp_path / "installed", "slack")
    loader = PluginLoader([source.parent], channel_runtime=runtime(None))
    record = await loader.load_plugin(
        manifest, source, {"enabled": enabled}, activate=False
    )
    assert record.status != "failed"
    assert loader.get_loaded_plugin("slack") is record
    row = registry.get_channel_catalog_entry("slack")
    assert row.plugin_id == row.channel_key == "slack"
    assert row.global_enabled is enabled
    assert row.description_record.plugin_id == "slack"
    assert registry.runtime_owners.leases("slack") == ()
    assert "slack.driver" not in sys.modules


@pytest.fixture
async def api_case(tmp_path, registry, monkeypatch, request):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from qwenpaw.config.config import (
        Config,
        AgentProfileConfig,
        ChannelConfig,
        save_agent_config,
    )
    from qwenpaw.config import utils
    from qwenpaw.app.routers import config as routes
    from qwenpaw.plugins import official_channels
    from qwenpaw.__version__ import __version__

    # The real bundle builder binds every current official owner and digest.
    builder = importlib.util.spec_from_file_location(
        "g2_admission_bundle",
        ROOT / "scripts/pack/generate_plugin_metadata.py",
    )
    module = importlib.util.module_from_spec(builder)
    builder.loader.exec_module(module)
    resources = tmp_path / "official-bundle"
    module.build_official_channel_bundle(
        ROOT, resources, host_version=__version__
    )
    monkeypatch.setattr(official_channels, "_resource_root", lambda: resources)

    workspace = tmp_path / "workspace"
    monkeypatch.setattr(
        utils,
        "get_config_path",
        lambda: tmp_path / "host/config.json",
    )
    utils.save_config(
        Config(
            agents={
                "profiles": {
                    "phase1": {
                        "id": "phase1",
                        "name": "Phase1",
                        "workspace_dir": str(workspace),
                    },
                },
            },
        ),
    )
    await load_sample(
        tmp_path,
        registry,
        schema=getattr(request, "param", None),
    )
    profile = AgentProfileConfig(
        id="phase1",
        name="Phase1",
        channels=ChannelConfig.model_validate(
            {
                "sample_chat": {
                    "enabled": False,
                    "api_token": "saved",
                    "options": {"retries": 8},
                },
                "removed_plugin": {"enabled": False, "custom": {"items": [1]}},
            },
        ),
    )
    agent = NS(agent_id="phase1", config=profile)

    async def get_agent(_request):
        return agent

    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_agent_for_request",
        get_agent,
    )
    reloads = []
    monkeypatch.setattr(
        routes,
        "schedule_agent_reload",
        lambda request, agent_id: reloads.append(agent_id),
    )
    save_agent_config("phase1", profile)
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield NS(
            client=client,
            agent=agent,
            saved=workspace / "agent.json",
            reloads=reloads,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [True, False])
@pytest.mark.parametrize(
    "bad",
    [
        {"options": {"retries": "3"}},
        {"rooms": [9]},
        {"dm_policy": "unsafe"},
        {"surprise": True},
    ],
)
async def test_invalid_generic_put_returns_422_before_memory_disk_or_reload(
    api_case,
    single,
    bad,
):
    baseline = api_case.agent.config.model_dump()
    original = api_case.saved.read_bytes()
    payload = {"enabled": False, **bad}
    if not single:
        payload = {
            "sample_chat": payload,
            "removed_plugin": {"custom": "would-change"},
        }
    endpoint = "/config/channels/sample_chat" if single else "/config/channels"
    response = await api_case.client.put(endpoint, json=payload)
    assert response.status_code == 422, response.text
    assert api_case.agent.config.model_dump() == baseline
    assert api_case.saved.read_bytes() == original
    assert api_case.reloads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [True, False])
async def test_generic_put_persists_defaults_without_catalog_metadata(
    api_case,
    single,
):
    payload = {
        "enabled": False,
        "api_token": "changed",
        "options": {"retries": 2},
        "owner": "wrong",
        "isBuiltin": False,
        "availability": "running",
        "process_mode": "in_process",
        "config_schema": {"type": "object"},
        "description": "Catalog prose",
        "label": "Catalog label",
        "icon": "catalog-icon",
    }
    endpoint = "/config/channels/sample_chat" if single else "/config/channels"
    response = await api_case.client.put(
        endpoint,
        json=payload if single else {"sample_chat": payload},
    )
    assert response.status_code == 200, response.text
    saved = json.loads(api_case.saved.read_text())["channels"]
    assert saved["sample_chat"]["options"] == {
        "retries": 2,
        "headers": {"X-Test": "yes"},
    }
    assert saved["sample_chat"]["rooms"] == []
    assert not {
        "owner",
        "isBuiltin",
        "availability",
        "process_mode",
        "config_schema",
        "description",
        "label",
        "icon",
    }.intersection(saved["sample_chat"])
    assert saved["removed_plugin"] == {
        "enabled": False,
        "custom": {"items": [1]},
    }


@pytest.mark.asyncio
async def test_missing_plugin_settings_remain_editable(api_case):
    response = await api_case.client.put(
        "/config/channels/removed_plugin",
        json={"enabled": False, "custom": {"items": [2]}},
    )
    assert response.status_code == 200, response.text
    saved = json.loads(api_case.saved.read_text())["channels"][
        "removed_plugin"
    ]
    assert saved == {"enabled": False, "custom": {"items": [2]}}


@pytest.mark.asyncio
async def test_generic_schema_api_reports_live_runtime_state(api_case):
    class Manager:
        async def get_channel(self, key):
            if key != "sample_chat":
                return None
            return NS(
                channel_process=NS(
                    health_snapshot=lambda: {
                        "state": "ready",
                        "platform_state": "connected",
                        "last_error": None,
                    },
                ),
            )

    api_case.agent.channel_manager = Manager()
    response = await api_case.client.get("/config/channels/schemas")
    assert response.status_code == 200, response.text
    row = response.json()["sample_chat"]
    assert (
        row["availability"] == "running"
        and row["runtime_state"] == "connected"
    )
    configs = (await api_case.client.get("/config/channels")).json()
    assert "removed_plugin" in configs and "sample_chat" in configs


def test_draft_202012_prefix_items_are_enforced():
    validate, _ = config_api()
    schema = {
        "type": "object",
        "properties": {
            "coordinates": {
                "type": "array",
                "prefixItems": [{"type": "integer"}],
                "items": {"type": "string"},
            },
        },
    }
    assert validate(schema, {"coordinates": [1, "north"]})["coordinates"] == [
        1,
        "north",
    ]
    with pytest.raises(ValueError):
        validate(schema, {"coordinates": ["wrong", "north"]})


@pytest.mark.parametrize(
    "domain",
    [
        "feishu",
        "lark",
        "http://gateway.test",
        "https://gateway.test",
        "invalid-region",
    ],
)
def test_feishu_schema_has_existing_domain_constraints(domain):
    from c6_artifacts import description

    validate, _ = config_api()
    schema = description("feishu").descriptor.config_schema
    if domain == "invalid-region":
        with pytest.raises(ValueError):
            validate(schema, {"domain": domain})
    else:
        assert validate(schema, {"domain": domain})["domain"] == domain


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [True, False])
async def test_official_schema_permitted_unknown_fields_survive_save_and_reload(  # noqa: E501
    api_case,
    single,
):
    from qwenpaw.config.config import load_agent_config

    payload = {"enabled": False, "domain": "lark", "custom": {"items": [1, 2]}}
    endpoint = "/config/channels/feishu" if single else "/config/channels"
    response = await api_case.client.put(
        endpoint,
        json=payload if single else {"feishu": payload},
    )
    assert response.status_code == 200, response.text
    saved = json.loads(api_case.saved.read_text())["channels"]["feishu"]
    assert saved["custom"] == {"items": [1, 2]}
    assert load_agent_config("phase1").channels.feishu.model_dump()[
        "custom"
    ] == {
        "items": [1, 2],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [True, False])
async def test_official_invalid_domain_put_leaves_saved_state_unchanged(
    api_case,
    single,
):
    original = api_case.saved.read_bytes()
    memory = api_case.agent.config.model_dump()
    payload = {"enabled": False, "domain": "invalid-region"}
    endpoint = "/config/channels/feishu" if single else "/config/channels"
    response = await api_case.client.put(
        endpoint,
        json=payload if single else {"feishu": payload},
    )
    assert response.status_code == 422, response.text
    assert api_case.agent.config.model_dump() == memory
    assert api_case.saved.read_bytes() == original and api_case.reloads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, 7, "invalid", []])
async def test_bulk_nonobject_channel_value_returns_422_without_changes(
    api_case,
    value,
):
    original = api_case.saved.read_bytes()
    memory = api_case.agent.config.model_dump()
    response = await api_case.client.put(
        "/config/channels",
        json={"sample_chat": value},
    )
    assert response.status_code == 422, response.text
    assert api_case.agent.config.model_dump() == memory
    assert api_case.saved.read_bytes() == original and api_case.reloads == []


def test_open_schema_factory_keeps_host_launch_controls_out_of_driver_config(
    tmp_path,
):
    source, manifest = sample_plugin(tmp_path)
    path = source / "channel.json"
    descriptor = json.loads(path.read_text())
    descriptor["config_schema"]["additionalProperties"] = True
    path.write_text(json.dumps(descriptor))
    description = describe_channel(source, manifest)
    controls = {
        "python_executable": "/evil/python",
        "support_root": "/evil/site",
        "code_root": "/evil/code",
        "descriptor_path": "/evil/channel.json",
        "source_revision": "evil",
        "channel_key": "evil",
        "instance_id": "evil",
        "generation": 999,
        "qwenpaw_version": "evil",
        "dependency_paths": ["/evil/deps"],
        "runtime_identity": {"evil": True},
        "startup_timeout": 999,
        "shutdown_timeout": 999,
    }
    proxy = description.create_proxy(
        unused_process,
        {"enabled": True, "ordinary_extra": {"answer": 42}, **controls},
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="trusted-instance",
        generation=2,
        qwenpaw_version="2.2.2b4",
    )
    spec = proxy._launch_spec
    assert not set(controls).intersection(spec.config)
    assert (
        spec.config["ordinary_extra"] == {"answer": 42}
        and spec.config["enabled"] is True
    )
    assert (
        spec.python_executable == sys.executable
        and spec.support_root == ROOT / "src"
    )
    assert spec.code_root == source and spec.channel_key == "sample_chat"
    assert spec.instance_id == "trusted-instance" and spec.generation == 2


@pytest.mark.parametrize("flag_schema", [True, False])
def test_nested_boolean_schema_accepts_omitted_flag_without_default_crash(
    tmp_path,
    flag_schema,
):
    schema = deepcopy(SCHEMA)
    schema["properties"]["options"] = {
        "type": "object",
        "default": {},
        "properties": {"flag": flag_schema},
    }
    source, manifest = sample_plugin(tmp_path, schema=schema)
    accepted = describe_channel(source, manifest).descriptor.config_schema
    validate, defaults = config_api()
    assert defaults(accepted)["options"] == {}
    assert validate(accepted, {})["options"] == {}


@pytest.mark.parametrize("flag_schema,valid", [(True, True), (False, False)])
def test_nested_boolean_schema_validates_supplied_flag(
    tmp_path,
    flag_schema,
    valid,
):
    schema = deepcopy(SCHEMA)
    schema["properties"]["options"] = {
        "type": "object",
        "default": {},
        "properties": {"flag": flag_schema},
    }
    source, manifest = sample_plugin(tmp_path, schema=schema)
    accepted = describe_channel(source, manifest).descriptor.config_schema
    validate, _ = config_api()
    if valid:
        assert validate(accepted, {"options": {"flag": {"nested": [1]}}})[
            "options"
        ] == {"flag": {"nested": [1]}}
    else:
        with pytest.raises(ValueError):
            validate(accepted, {"options": {"flag": {"nested": [1]}}})


PRESENTATION_NAME_SCHEMA = deepcopy(SCHEMA)
PRESENTATION_NAME_SCHEMA["properties"].update(
    {
        "description": {"type": "string"},
        "label": {"type": "string"},
        "icon": {"type": "string"},
    },
)
PRESENTATION_NAME_SCHEMA["required"] = ["description"]


@pytest.mark.asyncio
@pytest.mark.parametrize("api_case", [PRESENTATION_NAME_SCHEMA], indirect=True)
@pytest.mark.parametrize("single", [True, False])
async def test_schema_declared_presentation_names_survive_put_and_driver_config(  # noqa: E501
    api_case,
    single,
    registry,
):
    expected = {
        "description": "Webhook destination",
        "label": "Operations",
        "icon": "chat-mark",
    }
    payload = {
        "enabled": False,
        **expected,
        "owner": "fake-catalog-owner",
        "availability": "running",
    }
    endpoint = "/config/channels/sample_chat" if single else "/config/channels"
    response = await api_case.client.put(
        endpoint,
        json=payload if single else {"sample_chat": payload},
    )
    assert response.status_code == 200, response.text
    saved = json.loads(api_case.saved.read_text())["channels"]["sample_chat"]
    for field, value in expected.items():
        assert saved[field] == value
    assert not {"owner", "availability"}.intersection(saved)
    row = registry.get_channel_catalog_entry("sample_chat")
    proxy = row.description_record.create_proxy(
        unused_process,
        saved,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="presentation-fields",
        generation=1,
        qwenpaw_version="2.2.2b4",
    )
    for field, value in expected.items():
        assert proxy._launch_spec.config[field] == value


def schema_candidate(directory, key, field):
    source, manifest = sample_plugin(directory, key=key)
    path = source / "channel.json"
    data = json.loads(path.read_text())
    data["config_schema"] = {
        "type": "object",
        "properties": {"credential": field},
        "required": ["credential"],
        "additionalProperties": False,
    }
    data["config_fields"] = ["credential"]
    path.write_text(json.dumps(data))
    return source, manifest


@pytest.mark.parametrize(
    "field",
    [
        {"type": "invalid-type"},
        {"$ref": "https://schemas.invalid/channel-credential"},
    ],
)
def test_static_description_rejects_malformed_or_nonlocal_schema_before_python(
    tmp_path,
    field,
):
    source, manifest = schema_candidate(tmp_path, "broken_schema", field)
    with pytest.raises(ValueError, match="schema"):
        describe_channel(source, manifest)
    assert "broken_schema.driver" not in sys.modules


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        {"type": "invalid-type"},
        {"$ref": "https://schemas.invalid/channel-credential"},
    ],
)
async def test_disabled_bad_schema_load_fails_without_breaking_valid_catalog(
    tmp_path,
    registry,
    monkeypatch,
    field,
):
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector
    from qwenpaw.app.channels.catalog import get_configurable_channel_catalog

    async def forbidden(*args, **kwargs):
        raise AssertionError("Disabled static discovery spawned Driver")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    _good, good_manifest = sample_plugin(tmp_path, "valid_schema")
    bad, bad_manifest = schema_candidate(tmp_path, "broken_schema", field)
    loader = PluginLoader([tmp_path], channel_runtime=runtime(None))
    loader.registry.projector = WorkspaceProjector(live_workspaces=lambda: [])
    with pytest.raises(ValueError, match="schema"):
        await loader.load_plugin(
            bad_manifest,
            bad,
            {"enabled": False},
            activate=False,
        )
    assert loader.registry.get_channel_catalog_entry("broken_schema") is None
    # Host startup discovery catches one rejected source and keeps
    # healthy rows.
    await loader.load_all_plugins(
        configs={
            "valid_schema": {"enabled": False},
            "broken_schema": {"enabled": False},
        },
    )
    good_record = loader.get_loaded_plugin(good_manifest.id)
    bad_record = loader.get_loaded_plugin(bad_manifest.id)
    assert good_record.status != "failed"
    assert bad_record.status == "failed"
    assert "schema" in " ".join(bad_record.diagnostics).lower()
    rows = get_configurable_channel_catalog({"valid_schema", "broken_schema"})
    assert rows["valid_schema"]["availability"] == "disabled"
    assert rows["valid_schema"]["defaults"]["options"]["retries"] == 3
    assert "broken_schema.driver" not in sys.modules
    assert "valid_schema.driver" not in sys.modules


@pytest.mark.asyncio
async def test_static_valid_schema_with_missing_required_values_remains_discoverable(  # noqa: E501
    tmp_path,
    registry,
):
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector
    from qwenpaw.app.channels.catalog import get_configurable_channel_catalog
    from qwenpaw.plugins.channel_config import validate_channel_config

    source, manifest = schema_candidate(
        tmp_path,
        "required_schema",
        {"type": "string", "minLength": 1},
    )
    description = describe_channel(source, manifest)
    loader = PluginLoader([tmp_path], channel_runtime=runtime(None))
    loader.registry.projector = WorkspaceProjector(live_workspaces=lambda: [])
    record = await loader.load_plugin(
        manifest,
        source,
        {"enabled": False},
        activate=False,
    )
    assert record.status != "failed"
    row = get_configurable_channel_catalog()["required_schema"]
    assert row["availability"] == "disabled"
    assert "credential" not in row["defaults"]
    with pytest.raises(ValueError):
        validate_channel_config(description.descriptor.config_schema, {})
    assert "required_schema.driver" not in sys.modules
