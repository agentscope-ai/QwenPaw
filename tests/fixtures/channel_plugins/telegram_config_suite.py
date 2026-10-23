"""SDK-free legacy configuration and real Loader inherited contracts."""

import sys

import pytest

from extension_sample import ROOT
from telegram_support import fault_runtime, runtime, telegram, telegram_sdk

sys.path.insert(0, str(ROOT))




def test_environment_reads_exact_names_flags_raw_values_and_csv():
    from qwenpaw.config.channel_env import read_channel_env

    values = read_channel_env(
        "telegram",
        {
            "TELEGRAM_CHANNEL_ENABLED": "1",
            "TELEGRAM_BOT_TOKEN": " env-token ",
            "TELEGRAM_BASE_URL": " https://tg.test/ ",
            "TELEGRAM_HTTP_PROXY": " http://proxy:8080 ",
            "TELEGRAM_HTTP_PROXY_AUTH": " user:pass ",
            "TELEGRAM_BOT_PREFIX": "[Env] ",
            "TELEGRAM_SHOW_TYPING": "0",
            "TELEGRAM_DM_POLICY": "restricted",
            "TELEGRAM_GROUP_POLICY": "restricted",
            "TELEGRAM_ALLOW_FROM": " user1 , user2 ,, user3 ",
            "TELEGRAM_DENY_MESSAGE": " deny ",
            "TELEGRAM_REQUIRE_MENTION": "1",
        },
    )
    assert values is not None, "Telegram SDK-free environment reader absent"
    assert values == {
        "enabled": True,
        "bot_token": " env-token ",
        "base_url": " https://tg.test/ ",
        "http_proxy": " http://proxy:8080 ",
        "http_proxy_auth": " user:pass ",
        "bot_prefix": "[Env] ",
        "show_typing": False,
        "dm_policy": "restricted",
        "group_policy": "restricted",
        "allow_from": ["user1", "user2", "user3"],
        "deny_message": " deny ",
        "require_mention": True,
    }


def test_environment_defaults_and_literal_one_preserve_old_entry():
    from qwenpaw.config.channel_env import read_channel_env

    values = read_channel_env("telegram", {})
    assert values is not None, "Telegram SDK-free environment reader absent"
    assert values["enabled"] is False
    assert values["show_typing"] is True
    assert values["require_mention"] is False
    assert values["dm_policy"] == values["group_policy"] == "open"
    assert values["allow_from"] == []
    for raw in ("true", "True", "yes", "01", " 1", "1 ", "0", ""):
        assert (
            read_channel_env(
                "telegram",
                {
                    "TELEGRAM_CHANNEL_ENABLED": raw,
                    "TELEGRAM_SHOW_TYPING": raw,
                    "TELEGRAM_REQUIRE_MENTION": raw,
                },
            )["enabled"]
            is False
        )
        assert (
            read_channel_env("telegram", {"TELEGRAM_SHOW_TYPING": raw})[
                "show_typing"
            ]
            is False
        )
    assert "streaming_enabled" not in values
    assert "access_control_dm" not in values


def test_compat_config_trims_only_strings_preserves_default_typing():
    from qwenpaw.config.channel_config_compat import normalize_channel_config

    raw = {
        "enabled": 1,
        "bot_token": " token ",
        "base_url": " https://tg.test/// ",
        "http_proxy": " http://proxy ",
        "http_proxy_auth": " user:pass ",
        "bot_prefix": "[Config] ",
        "show_typing": None,
        "allow_from": None,
        "dm_policy": None,
        "group_policy": "",
        "deny_message": " deny ",
        "require_mention": 1,
    }
    values = normalize_channel_config("telegram", raw)
    assert values["bot_token"] == "token"
    assert values["base_url"] == "https://tg.test"
    assert values["http_proxy"] == "http://proxy"
    assert values["http_proxy_auth"] == "user:pass"
    assert values["bot_prefix"] == "[Config]"
    assert values["deny_message"] == " deny "
    assert values["show_typing"] is True
    assert values["allow_from"] == []
    assert values["dm_policy"] == values["group_policy"] == "open"
    assert values["enabled"] is True
    assert values["require_mention"] is True
    assert raw["bot_token"] == " token "


def test_model_config_none_defaults_and_compat_boolean_coercion():
    from qwenpaw.config.channel_config_compat import normalize_channel_config
    from qwenpaw.config.config import TelegramConfig

    assert TelegramConfig().show_typing is None
    raw = TelegramConfig(
        bot_token="obj_token", bot_prefix="[Obj] "
    ).model_dump()
    normalized = normalize_channel_config("telegram", raw, dictionary=False)
    assert normalized["bot_token"] == "obj_token"
    assert normalized["bot_prefix"] == "[Obj]"
    assert normalized["show_typing"] is True
    assert normalized["enabled"] is False
    normalized = normalize_channel_config(
        "telegram",
        {
            "bot_token": "token",
            "streaming_enabled": "0",
            "access_control_dm": "0",
            "access_control_group": None,
        },
    )
    assert normalized["streaming_enabled"] is True
    assert normalized["access_control_dm"] is True
    assert normalized["access_control_group"] is False


def test_real_proxy_factory_retains_legacy_config_and_policy_projection(
    tmp_path,
):
    import json
    from g2_legacy_configuration_suite import proxy_for
    from qwenpaw.config.config import TelegramConfig
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = ROOT / "plugins/channel/telegram"
    manifest = PluginManifest.model_validate(
        json.loads((source / "plugin.json").read_text())
    )
    proxy = proxy_for(
        describe_channel(source, manifest),
        TelegramConfig(
            enabled=False,
            bot_token="my_bot_token",
            http_proxy="http://proxy.example.com:8080",
            http_proxy_auth="user:pass",
            bot_prefix="[MyBot] ",
            show_typing=False,
            dm_policy="allowlist",
            group_policy="allowlist",
            allow_from=["user1", "user2"],
            deny_message="Access denied",
            require_mention=True,
        ),
        workspace_dir=tmp_path,
    )
    values = proxy._launch_spec.config
    assert proxy.channel == "telegram"
    assert proxy.enabled is False
    assert values["bot_token"] == "my_bot_token"
    assert values["base_url"] == ""
    assert values["http_proxy"] == "http://proxy.example.com:8080"
    assert values["http_proxy_auth"] == "user:pass"
    assert values["show_typing"] is False
    assert proxy.bot_prefix == "[MyBot]"
    assert proxy.dm_policy == proxy.group_policy == "allowlist"
    assert proxy.allow_from == {"user1", "user2"}
    assert proxy.deny_message == "Access denied"
    assert proxy.require_mention is True
    assert proxy.uses_manager_queue is True
    assert proxy.channel_process.health_snapshot()["pid"] is None


@pytest.mark.asyncio
async def test_http_config_get_returns_enabled_and_exact_custom_base_url(
    runtime, telegram_sdk, monkeypatch
):
    from telegram_business_suite import HostImportGuard

    monkeypatch.setattr(sys, "meta_path", [HostImportGuard(), *sys.meta_path])
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from qwenpaw.app.multi_agent_manager import MultiAgentManager
    from qwenpaw.app.routers import config as routes
    from qwenpaw.config.config import AgentProfileRef
    from qwenpaw.config.utils import load_config, save_config

    expected_url = "https://telegram-config-api.example.test"
    rt = await telegram(runtime, telegram_sdk, base_url=expected_url)
    config = load_config()
    config.agents.profiles[rt.ws.agent_id] = AgentProfileRef(
        id=rt.ws.agent_id, workspace_dir=str(rt.ws.workspace_dir)
    )
    config.agents.active_agent = rt.ws.agent_id
    config.channels.telegram = rt.ws.config.channels.telegram
    save_config(config)
    # Use the actual manager/resolver with an already running workspace.
    # This case scopes HTTP routing/config DTO; full Agent startup is separate.
    manager = MultiAgentManager()
    manager.agents[rt.ws.agent_id] = rt.ws
    app = FastAPI()
    app.state.multi_agent_manager = manager
    app.state.plugin_loader = rt.loader
    app.include_router(routes.router, prefix="/api")
    pid = rt.process.health_snapshot()["pid"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://in-process.test"
    ) as client:
        response = await client.get("/api/config/channels/telegram")
        assert response.status_code == 200
        body = response.json()
        assert body.get("enabled") is True
        assert body.get("base_url") == expected_url
        unknown = await client.get(
            "/api/config/channels/telegram",
            headers={"X-Agent-Id": "not-configured"},
        )
        assert unknown.status_code == 404
    assert load_config().channels.telegram.base_url == expected_url
    assert rt.process.health_snapshot()["pid"] == pid
    assert not any(
        name == "telegram" or name.startswith("telegram.")
        for name in sys.modules
    )
