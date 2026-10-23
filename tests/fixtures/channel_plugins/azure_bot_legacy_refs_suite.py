"""C6 observations and owner controls; unowned legacy auto-adoption is forbidden."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from azure_bot_native_support import APP, SERVICE, activity, post, azure, connector, rsa_material, state_module

pytestmark = pytest.mark.asyncio
TARGET = "azure_msteams#ABCDEFGHIJ:Ada#123456"
ROOT = Path(__file__).resolve().parents[3]


def legacy_class():
    name = "azure_c6_original_fixture"
    if name not in sys.modules:
        directory = ROOT / "tests/fixtures/channel_plugins/legacy_azure_bot"
        spec = importlib.util.spec_from_file_location(name, directory / "__init__.py", submodule_search_locations=[str(directory)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name].AzureBotChannel


async def unused_process(_request):
    raise AssertionError("Reference-only characterization must not execute an Agent")
    yield


def old_channel(workspace):
    return legacy_class()(process=unused_process, enabled=True, app_id=APP, app_password="dummy-secret", tenant_id="test-tenant", workspace_dir=workspace)


async def open_target(driver, target=TARGET):
    return await driver._open({**driver._context.identity.to_mapping(), "to_handle": target, "meta": {}}, None)


async def test_actual_original_refs_file_has_no_owner_and_current_refuses_before_new_ingress(azure, connector, tmp_path):
    workspace = tmp_path / "old-workspace"
    workspace.mkdir()
    previous = old_channel(workspace)
    resumed = None
    try:
        # Execute the unchanged old serialization methods: no invented owner
        # fields. This calls the old reference writer, not its JWT ingress.
        previous._store_conversation_reference(activity())
        await asyncio.gather(*list(previous._save_tasks))
        source = workspace / "azure_bot_refs.json"
        before = source.read_bytes()
        refs = json.loads(before)
        assert set(refs) == {TARGET}
        assert refs[TARGET] == {
            "service_url": SERVICE, "conversation_id": "conversation-ABCDEFGHIJ",
            "azure_channel_id": "msteams", "bot_channel_id": "native-bot", "is_group": False,
        }
        resumed = old_channel(workspace)
        resumed._load_refs_from_disk()
        assert resumed._find_ref(TARGET) == refs[TARGET]
        await resumed.send(TARGET, "legacy proactive text")
        assert connector.requests == [
            ("/v3/conversations/conversation-ABCDEFGHIJ/activities",
             {"type": "message", "from": {"id": "native-bot"}, "text": "legacy proactive text"},
             "Bearer access-1")
        ]
        connector.requests.clear()
        async with azure(workspace_dir=str(workspace)) as (driver, peer):
            assert peer.events == []
            with pytest.raises(ValueError, match="AZURE_ROUTE_UNAVAILABLE"):
                await open_target(driver)
            assert driver._platform.store.refs == {}
            assert driver._platform.store.legacy == refs
            assert connector.requests == [] and peer.events == []
        assert source.read_bytes() == before
    finally:
        await previous.stop()
        if resumed is not None: await resumed.stop()


async def learn_owned(azure, connector, workspace):
    async with azure(workspace_dir=str(workspace)) as (driver, peer):
        assert (await post(driver, connector, activity()))[0] == 200
        assert len(peer.events) == 1
        path = driver._platform.store.directory / "refs.json"
        before = path.read_bytes()
        envelope = json.loads(before)
        assert envelope["owner"] == {"app_id": APP, "tenant_id": "test-tenant", "workspace_dir": str(workspace.resolve())}
        assert TARGET in envelope["refs"]
    return path, before


async def test_owned_same_app_same_workspace_sends_without_new_ingress(azure, connector, tmp_path):
    from qwenpaw.channel_protocol.models import SendParams

    workspace = tmp_path / "owned-workspace"
    path, before = await learn_owned(azure, connector, workspace)
    assert connector.requests == []
    async with azure(workspace_dir=str(workspace)) as (driver, peer):
        assert peer.events == []
        opened = await open_target(driver)
        params = SendParams.from_mapping({
            **driver._context.identity.to_mapping(), "delivery_id": "owned-proactive-once",
            "to_handle": opened["response_handle"], "operation": "message.create",
            "content_parts": [{"type": "text", "text": "owned proactive text"}], "content_source": "direct",
        })
        result = await driver._send(params, None)
        assert result["state"] == "acknowledged"
        assert connector.requests == [
            ("/v3/conversations/conversation-ABCDEFGHIJ/activities",
             {"type": "message", "from": {"id": "native-bot"}, "text": "owned proactive text"},
             "Bearer access-1")
        ]
        assert peer.events == []
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["app", "workspace"])
async def test_owned_refs_cannot_cross_app_or_workspace_even_if_file_copied(azure, connector, tmp_path, change):
    workspace = tmp_path / "original-workspace"
    source, original = await learn_owned(azure, connector, workspace)
    target_workspace = workspace if change == "app" else tmp_path / "other-workspace"
    config = {"workspace_dir": str(target_workspace), "app_id": "another-app" if change == "app" else APP, "tenant_id": "test-tenant"}
    async with azure(**config) as (driver, peer):
        with pytest.raises(ValueError, match="AZURE_ROUTE_UNAVAILABLE"):
            await open_target(driver)
        assert driver._platform.store.refs == {} and peer.events == []
        destination = driver._platform.store.directory / "refs.json"
    assert destination != source
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(original)
    with pytest.raises(ValueError, match="AZURE_STATE_OWNER_CONFLICT"):
        async with azure(**config):
            pytest.fail("Copied foreign owner envelope was accepted")
    assert source.read_bytes() == destination.read_bytes() == original
    assert connector.requests == []


async def test_captured_original_global_refs_send_via_official_factory_before_new_ingress(azure, connector, tmp_path, monkeypatch):
    # This import is the first implementation gate. Until it exists, this is
    # an interface-missing RED, not evidence that downstream migration ran.
    from qwenpaw.plugins.azure_legacy import capture_azure_legacy
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.channel_protocol.models import SendParams
    from qwenpaw.__version__ import __version__
    from azure_bot_native_support import free_port
    import qwenpaw.constant as constants

    legacy_root = tmp_path / "legacy-root"
    working = tmp_path / "working"
    workspace = legacy_root / "workspaces" / "default"
    legacy_root.mkdir()
    working.mkdir()
    workspace.mkdir(parents=True)
    config = {"enabled": True, "app_id": APP, "app_password": "capture-secret-must-not-persist", "tenant_id": "test-tenant", "http_host": "127.0.0.1", "http_port": free_port()}
    config_path = legacy_root / "config.json"
    # Actual old single-workspace configuration: no invented owner/profiles.
    config_path.write_text(json.dumps({"channels": {"azure_bot": config}}))
    previous = old_channel(legacy_root)
    try:
        previous._store_conversation_reference(activity())
        await asyncio.gather(*list(previous._save_tasks))
        refs_path = legacy_root / "azure_bot_refs.json"
        original = refs_path.read_bytes()
        original_config = config_path.read_bytes()
        capture = capture_azure_legacy(config_path=config_path, legacy_state_dir=legacy_root, working_dir=working)
        assert "capture-secret-must-not-persist" not in json.dumps(capture)
        monkeypatch.setattr(constants, "WORKING_DIR", legacy_root)
        monkeypatch.chdir(working)
        source = ROOT / "plugins/channel/azure_bot"
        description = describe_channel(source, PluginManifest.from_dict(json.loads((source / "plugin.json").read_text())))
        proxy = description.create_proxy(unused_process, config, python_executable=sys.executable, support_root=ROOT / "src", instance_id="azure-c6-captured", generation=1, qwenpaw_version=__version__, workspace_dir=workspace, legacy_references=capture)
        projected = dict(proxy._launch_spec.config)
        authorization = projected["legacy_reference_owner"]
        assert set(authorization) == {"schema_version", "capture_id", "owner", "refs_sha256"}
        assert authorization["owner"] == {"workspace_dir": str(workspace.resolve()), "app_id": APP, "tenant_id": "test-tenant"}
        assert "refs" not in authorization
        async with azure(**projected) as (driver, peer):
            assert peer.events == []
            opened = await open_target(driver)
            result = await driver._send(SendParams.from_mapping({
                **driver._context.identity.to_mapping(), "delivery_id": "captured-proactive-once",
                "to_handle": opened["response_handle"], "operation": "message.create",
                "content_parts": [{"type": "text", "text": "captured proactive text"}], "content_source": "direct",
            }), None)
            assert result["state"] == "acknowledged"
            assert connector.requests == [("/v3/conversations/conversation-ABCDEFGHIJ/activities", {"type": "message", "from": {"id": "native-bot"}, "text": "captured proactive text"}, "Bearer access-1")]
            assert peer.events == []
        assert refs_path.read_bytes() == original
        assert config_path.read_bytes() == original_config
    finally:
        await previous.stop()
