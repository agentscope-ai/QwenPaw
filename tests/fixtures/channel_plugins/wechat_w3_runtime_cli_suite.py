"""SDK-free W3 path, claim-release and CLI management responsibilities.

Claim-release tests use a genuine generic proxy plus real WeChat auth claims.
They are manager/ownership units; they do not register a fake official WeChat.
"""

from copy import deepcopy
from importlib import import_module
from pathlib import Path

import pytest

from management_process_suite import (
    KEY,
    management_runtime,
    local_management_http,
    management_sample_source,
    active_management,
)
from wechat_w2_config_support import write_profiles
from wechat_w2_session_suite import narrow_legacy_test_guard


def test_absolute_execution_paths_detaches_and_preserves_logical_parent(
    tmp_path, monkeypatch
):
    from qwenpaw.config.channel_config_compat import absolute_execution_paths

    physical = tmp_path / "physical"
    physical.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(physical, target_is_directory=True)
    token = alias / "token"
    token.symlink_to(physical / "elsewhere-token")
    values = {
        "bot_token_file": "alias/../alias/token",
        "media_dir": "downloads/../media",
        "nested": {"value": [1]},
    }
    before = deepcopy(values)
    execution = absolute_execution_paths(
        values,
        path_fields=("bot_token_file", "media_dir"),
        working_dir=tmp_path,
    )
    assert execution["bot_token_file"] == str(
        tmp_path / "alias/../alias/token"
    )
    assert execution["media_dir"] == str(tmp_path / "downloads/../media")
    assert (
        Path(execution["bot_token_file"]).parent == tmp_path / "alias/../alias"
    )
    execution["nested"]["value"].append(2)
    assert values == before and token.is_symlink()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cleanup", ["unstarted", "stopped", "failed-then-stopped"]
)
async def test_real_manager_releases_auth_claims_only_after_exact_receipt(
    management_runtime, tmp_path, monkeypatch, cleanup
):
    from qwenpaw.app.channels.manager import (
        ChannelManager,
        instantiate_channel,
    )
    from qwenpaw.app.channels.process_supervisor import StopResult
    from qwenpaw.app.channels.wechat_auth_custody import reserve_wechat_auth
    from qwenpaw.config.config import load_agent_config
    from qwenpaw.plugins.ownership import RuntimeKey

    rt = await management_runtime()
    _, paths = write_profiles(
        tmp_path,
        monkeypatch,
        KEY,
        {"enabled": True, "host": "127.0.0.1", "port": 9},
    )
    channel = instantiate_channel(
        KEY, load_agent_config("A"), process=None, workspace_dir=paths["A"]
    )
    manager = ChannelManager([channel])
    claims = reserve_wechat_auth(
        rt.loader.registry,
        owner=channel._runtime_lease,
        workspace_id="A",
        workspace_dir=paths["A"],
        config={"bot_token_file": str(tmp_path / "auth-A" / "token")},
    )
    channel._wechat_auth_claims = claims
    unrelated = rt.owners.reserve(
        KEY,
        RuntimeKey("channel", KEY, "B"),
        rt.record.source_path,
        instance_id="other-runtime",
    )
    try:
        assert claims and set(claims).issubset(rt.owners.leases())
        assert channel.channel_process.health_snapshot()["pid"] is None
        if cleanup == "unstarted":
            manager._release_unstarted(channel)
        else:
            if cleanup == "failed-then-stopped":

                async def failed_stop():
                    return StopResult(
                        exited=False,
                        returncode=None,
                        forced=False,
                        residual=("unit-unreaped-child",),
                    )

                with monkeypatch.context() as patch:
                    patch.setattr(channel.channel_process, "stop", failed_stop)
                    result = await manager.stop_one(KEY)
                assert not result.stopped
                assert set(claims).issubset(rt.owners.leases())
                assert channel._runtime_lease in rt.owners.leases()
                assert await manager.get_channel(KEY) is channel
            result = await manager.stop_one(KEY)
            assert result.stopped and result.exited
        assert set(claims).isdisjoint(rt.owners.leases())
        assert channel._runtime_lease not in rt.owners.leases()
        assert channel._wechat_auth_claims == ()
        assert unrelated in rt.owners.leases()
    finally:
        from qwenpaw.plugins.ownership import RuntimeStopReceipt

        rt.owners.release(
            unrelated, RuntimeStopReceipt(True, "unit never spawned")
        )
        if channel._runtime_lease in rt.owners.leases():
            await manager.stop_one(KEY)


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["success", "reader-failure"])
async def test_doctor_uses_actual_managed_worker_and_finally_closes_owned_service(
    management_runtime, local_management_http, tmp_path, monkeypatch, boundary
):
    from qwenpaw.app.channels.management import ChannelManagementService
    from qwenpaw.config.utils import load_config, save_config

    rt = await management_runtime()
    config, _ = write_profiles(
        tmp_path,
        monkeypatch,
        KEY,
        {
            "enabled": True,
            "host": local_management_http.host,
            "port": local_management_http.port,
        },
    )
    config.plugins[KEY] = {"enabled": True}
    save_config(config)
    # Doctor runs as its own CLI owner, so retire the provisioning Loader's
    # registration before the real doctor Loader discovers that installation.
    retired = await rt.loader.unload_plugin(KEY)
    assert retired.quiescent, retired.errors
    doctor = import_module("qwenpaw.cli.doctor_connectivity")
    opened, closed = [], []
    original_init, original_close = (
        ChannelManagementService.__init__,
        ChannelManagementService.aclose,
    )

    def construct(service, loader):
        original_init(service, loader)
        opened.append(service)

    async def close(service):
        result = await original_close(service)
        closed.append(service)
        return result

    monkeypatch.setattr(ChannelManagementService, "__init__", construct)
    monkeypatch.setattr(ChannelManagementService, "aclose", close)
    if boundary == "reader-failure":

        def fail(*args):
            raise OSError("isolated profile reader failure")

        monkeypatch.setattr(doctor, "_read_workspace_agent_json", fail)
        with pytest.raises(OSError, match="isolated profile reader failure"):
            await doctor._managed_connectivity_notes(load_config(), 5)
        assert not local_management_http.requests
    else:
        handled, notes = await doctor._managed_connectivity_notes(
            load_config(), 5
        )
        assert handled == {
            (agent_id, KEY) for agent_id in ("A", "B", "default")
        }
        assert notes == []
        assert len(local_management_http.requests) == 3
        assert all(
            req["operation"] == "connection.verify"
            and req["level"] == "reachability"
            for req in local_management_http.requests
        )
    assert len(opened) == 1 and closed == opened
    assert not active_management(rt)
    unloaded = await opened[0]._loader.unload_plugin(KEY)
    assert unloaded.quiescent, unloaded.errors


def test_cli_registration_is_nonactivating_and_disabled_descriptor_remains_configurable(
    tmp_path, monkeypatch
):
    import asyncio
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry

    monkeypatch.setattr(PluginRegistry, "_instance", None)
    sample = management_sample_source(tmp_path / "installed")
    write_profiles(tmp_path, monkeypatch, KEY, {"enabled": False})
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir", lambda: sample.source.parent
    )
    cli = import_module("qwenpaw.cli.channels_cmd")
    monkeypatch.setattr(cli, "get_plugins_dir", lambda: sample.source.parent)
    monkeypatch.setattr(cli, "_CLI_CHANNEL_PLUGINS_LOADED", False)
    calls, loaders = [], []
    original_init, original_load = (
        PluginLoader.__init__,
        PluginLoader.load_all_plugins,
    )

    def construct(loader, *args, **kwargs):
        original_init(loader, *args, **kwargs)
        loaders.append(loader)

    async def load(loader, *args, **kwargs):
        calls.append(kwargs)
        return await original_load(loader, *args, **kwargs)

    monkeypatch.setattr(PluginLoader, "__init__", construct)
    monkeypatch.setattr(PluginLoader, "load_all_plugins", load)
    cli._load_channel_plugins_for_cli()
    assert len(calls) == 1 and calls[0]["activate"] is False
    assert not sample.marker.exists()
    assert cli._get_channel_names()[KEY] == "Management Sample"
    assert KEY in cli.get_channel_configurators()
    assert not PluginRegistry().runtime_owners.leases()
    asyncio.run(loaders[0].unload_plugin(KEY))


def test_configure_wechat_stays_manual_and_does_not_touch_auth_files(
    monkeypatch, tmp_path
):
    from qwenpaw.config.config import WeChatConfig

    cli = import_module("qwenpaw.cli.channels_cmd")
    prompts = []
    monkeypatch.setattr(cli, "prompt_confirm", lambda *args, **kwargs: True)
    values = iter(
        (
            str(tmp_path / "token"),
            "https://fixture.invalid",
            str(tmp_path / "media"),
        )
    )

    def prompt(label, **kwargs):
        prompts.append(label)
        return next(values)

    monkeypatch.setattr(cli.click, "prompt", prompt)
    config = WeChatConfig(bot_token="keep-existing-credential")
    result = cli.configure_wechat(config)
    assert result is config and result.enabled
    assert result.bot_token == "keep-existing-credential"
    assert result.bot_token_file == str(tmp_path / "token")
    assert prompts == [
        "bot_token file path",
        "iLink API base URL (leave empty for default)",
        "Local media download directory (leave empty to disable)",
    ]
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["modified", "missing"])
async def test_public_management_checks_installed_bytes_before_owner_and_network(
    management_runtime, local_management_http, mutation
):
    from qwenpaw.app.channels.management import ManagementError
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt

    rt = await management_runtime()
    parameters = {
        "config": {
            "enabled": False,
            "host": local_management_http.host,
            "port": local_management_http.port,
        },
        "level": "reachability",
    }
    result = await rt.service.execute(
        "A", KEY, "connection.verify", parameters, timeout=5
    )
    assert result.outcome == "ok" and result.result["verdict"] == "passed"
    assert len(local_management_http.requests) == 1 and not active_management(
        rt
    )
    other = rt.owners.reserve(
        KEY,
        RuntimeKey("channel", KEY, "B"),
        rt.record.source_path,
        instance_id="unrelated-unstarted-owner",
    )
    before = rt.owners.leases()
    driver = rt.record.source_path / KEY / "driver.py"
    if mutation == "modified":
        driver.write_text(driver.read_text() + "\n# installed bytes changed\n")
    else:
        driver.unlink()
    try:
        with pytest.raises(ManagementError) as rejected:
            await rt.service.execute(
                "A", KEY, "connection.verify", parameters, timeout=5
            )
        assert rejected.value.reason_code == "SOURCE_REVISION_MISMATCH"
        assert str(rejected.value) == "SOURCE_REVISION_MISMATCH"
        assert str(driver) not in str(rejected.value)
        assert rt.owners.leases() == before and other in rt.owners.leases()
        assert len(local_management_http.requests) == 1
    finally:
        rt.owners.release(
            other, RuntimeStopReceipt(True, "unit never spawned")
        )
