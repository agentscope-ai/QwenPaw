"""Original config/target duties on official factory and public protocol."""

from types import SimpleNamespace
import sys
from pathlib import Path

import pytest

pytest_plugins = ["wecom_contract_suite"]

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/wecom"))


@pytest.fixture(autouse=True)
def isolate_configuration(monkeypatch):
    from qwenpaw.config.config import Config

    monkeypatch.setattr("qwenpaw.app.channels.base.load_config", Config)


def test_original_basic_config_fields(official_wecom_proxy):
    channel = official_wecom_proxy(
        {
            "enabled": True,
            "bot_id": "bot_123",
            "secret": "secret_456",
            "bot_prefix": "[Bot] ",
            "welcome_text": "Welcome!",
            "dm_policy": "open",
            "group_policy": "allowlist",
        }
    )
    assert channel.enabled is True
    assert channel._launch_spec.config["bot_id"] == "bot_123"
    assert channel._launch_spec.config["secret"] == "secret_456"
    assert channel.bot_prefix == "[Bot] "
    assert channel._launch_spec.config["welcome_text"] == "Welcome!"
    assert channel.channel == "wecom"
    assert channel.dm_policy == "open"
    assert channel.group_policy == "allowlist"


def test_original_advanced_config_and_display(official_wecom_proxy):
    from qwenpaw.app.channels.renderer import ChannelDisplayConfig

    channel = official_wecom_proxy(
        {
            "enabled": False,
            "bot_id": "",
            "secret": "",
            "bot_prefix": "",
            "allow_from": ["user1", "user2"],
            "deny_message": "Access denied",
            "max_reconnect_attempts": 5,
        },
        display_config=ChannelDisplayConfig(
            show_thinking=False,
            show_tool_calls=False,
            show_tool_results=False,
        ),
    )
    assert channel.enabled is False
    assert channel._display_config.show_tool_details is True
    assert channel._display_config.show_tool_calls is False
    assert channel._display_config.show_tool_results is False
    assert not channel._display_config.show_thinking
    assert channel.allow_from == {"user1", "user2"}
    assert channel.deny_message == "Access denied"
    assert channel._launch_spec.config["max_reconnect_attempts"] == 5


def test_original_target_priority_and_reply_arguments(official_wecom_proxy):
    from qwenpaw.channel_protocol.targets import decode_reply_target
    from qwenpaw_channel_wecom.driver import WeComDriver

    channel = official_wecom_proxy({"enabled": False})
    for user, session, expected_chat in [
        ("user_123", "wecom:session_456", "session_456"),
        ("user_123", "", "user_123"),
    ]:
        handle = channel.to_handle_from_target(
            user_id=user, session_id=session
        )
        assert decode_reply_target(handle) == {
            "user_id": user,
            "session_id": session,
        }
        assert WeComDriver._target(handle, {})["wecom_chatid"] == expected_chat
    for session, user, expected_chat in [
        ("wecom:user_123", "user_456", "user_123"),
        ("", "user_456", "user_456"),
    ]:
        request = SimpleNamespace(session_id=session, user_id=user)
        handle = channel.get_to_handle_from_request(request)
        assert decode_reply_target(handle) == {
            "user_id": user,
            "session_id": session,
        }
        assert WeComDriver._target(handle, {})["wecom_chatid"] == expected_chat
    request = SimpleNamespace(
        user_id="user_123", session_id="wecom:session_456"
    )
    assert channel.get_on_reply_sent_args(request, "wecom:session_456") == (
        "user_123",
        "wecom:session_456",
    )


def test_original_request_defaults_and_closed_input_boundary(
    official_wecom_proxy,
):
    from qwenpaw.channel_protocol.models import InboundEvent
    from qwenpaw.plugins.execution.errors import ProtocolValidationError

    channel = official_wecom_proxy({"enabled": False})
    request = channel.build_agent_request_from_native({})
    assert request.channel == "wecom"
    assert hasattr(request, "session_id")
    # Old arbitrary non-dict private helper calls are no longer the ingress
    # interface: raw wire is rejected before the actual builder or Agent.
    with pytest.raises(ProtocolValidationError):
        InboundEvent.from_mapping("invalid")


async def test_disabled_start_stop_and_send_keep_zero_worker_effects(
    official_wecom_proxy, monkeypatch
):
    import asyncio
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.schemas import TextContent

    calls = []

    async def unexpected_spawn(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("disabled channel spawned a worker")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected_spawn)
    channel = official_wecom_proxy({"enabled": False})
    await channel.start()
    assert channel.channel_process.health_snapshot()["pid"] is None
    for operation in (
        channel.send("wecom:user_123", "Hello"),
        channel.send_content_parts(
            "wecom:user_123", [TextContent(text="Hello")]
        ),
    ):
        with pytest.raises(ChannelDeliveryError) as error:
            await operation
        assert error.value.reason_code == "CHANNEL_DISABLED"
    await channel.stop()
    assert calls == []
    assert channel.channel_process.health_snapshot()["pid"] is None
