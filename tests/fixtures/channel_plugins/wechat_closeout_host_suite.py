"""Remaining host responsibilities on the real bundled unstarted Proxy."""

from types import SimpleNamespace

import pytest

from qwenpaw.channel_protocol.targets import decode_reply_target
from qwenpaw.schemas import ImageContent, TextContent
from wechat_closeout_config_suite import official_factory
from wechat_w4_formal_support import wechat_host_import_guard

__all__ = ["official_factory", "wechat_host_import_guard"]


def test_official_config_render_access_control_and_no_child_custody(
    official_factory,
):
    channel = official_factory(
        {
            "enabled": True,
            "bot_token": "my_token_123",
            "bot_prefix": "[Bot] ",
            "base_url": "https://custom.api.com",
            "dm_policy": "open",
            "group_policy": "allowlist",
            "allow_from": ["user1", "user2"],
            "deny_message": "Access denied",
            "show_thinking": False,
            "show_tool_calls": False,
            "show_tool_results": False,
        }
    )
    assert channel.channel == "wechat" and channel.enabled is True
    assert channel._launch_spec.config["bot_token"] == "my_token_123"
    assert channel._launch_spec.config["base_url"] == "https://custom.api.com"
    assert channel.bot_prefix == "[Bot] "
    assert channel.dm_policy == "open" and channel.group_policy == "allowlist"
    assert channel.allow_from == {"user1", "user2"}
    assert channel.deny_message == "Access denied"
    assert channel._display_config.show_tool_details is True
    assert channel._display_config.show_thinking is False
    assert channel._display_config.show_tool_calls is False
    assert channel._display_config.show_tool_results is False
    assert channel.access_control_enabled is False
    assert channel.access_control_dm is channel.access_control_group is False
    channel.access_control_dm = True
    assert channel.access_control_enabled is True
    channel.access_control_dm = False
    channel.access_control_group = True
    assert channel.access_control_enabled is True
    assert channel.channel_process.health_snapshot()["pid"] is None


def test_official_route_request_and_native_merge_preserve_business_values(
    official_factory,
):
    channel = official_factory({"enabled": False})
    assert channel.resolve_session_id("user123") == "wechat:user123"
    assert (
        channel.resolve_session_id(
            "user123", {"session_id": "wechat:group:group456"}
        )
        == "wechat:group:group456"
    )
    for session in ("wechat:session_abc", ""):
        target = channel.to_handle_from_target(
            user_id="user123", session_id=session
        )
        decoded = decode_reply_target(target)
        assert decoded["user_id"] == "user123"
        assert decoded["session_id"] == session
    payload = {
        "channel_id": "wechat",
        "sender_id": "user123",
        "acl_sender_id": "user123",
        "user_id": "user123",
        "session_id": "wechat:session_abc",
        "content_parts": [TextContent(text="Hello")],
        "meta": {"wechat_group_id": "group123"},
    }
    request = channel.build_agent_request_from_native(payload)
    assert request.user_id == "user123" and request.channel == "wechat"
    assert request.session_id == "wechat:session_abc"
    assert request.channel_meta["wechat_group_id"] == "group123"
    assert channel.get_on_reply_sent_args(request, "ignored") == (
        "user123",
        "wechat:session_abc",
    )
    decoded = decode_reply_target(channel.get_to_handle_from_request(request))
    assert decoded["session_id"] == "wechat:session_abc"
    image = ImageContent(image_url="http://img.jpg")
    varied = channel.build_agent_request_from_native(
        {**payload, "session_id": "", "content_parts": [image]}
    )
    assert varied.user_id == "user123"
    assert varied.session_id == "wechat:user123"
    assert len(varied.input) == 1
    items = [
        {
            "channel_id": "wechat",
            "sender_id": "user1",
            "content_parts": [TextContent(text="Part1")],
            "meta": {"key1": "value1"},
        },
        {
            "content_parts": [TextContent(text="Part2")],
            "meta": {"key2": "value2"},
        },
    ]
    result = channel.merge_native_items(items)
    assert result["channel_id"] == "wechat"
    assert result["sender_id"] == "user1"
    assert len(result["content_parts"]) == 2
    assert result["meta"]["key2"] == "value2"
    assert channel.merge_native_items([]) is None
    assert channel.get_on_reply_sent_args(
        SimpleNamespace(user_id="user123", session_id="wechat:session_abc"),
        "wechat:session_abc",
    ) == ("user123", "wechat:session_abc")


@pytest.mark.asyncio
async def test_disabled_start_stop_and_empty_parts_never_launch_worker(
    official_factory,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    channel = official_factory({"enabled": False})
    await channel.start()
    for method, args in (
        (channel.send, ("wechat:user123", "Message")),
        (
            channel.send_content_parts,
            ("wechat:user123", [TextContent(text="Message")]),
        ),
    ):
        with pytest.raises(ChannelDeliveryError) as raised:
            await method(*args)
        assert raised.value.reason_code == "CHANNEL_DISABLED"
    receipt = await channel.stop()
    assert receipt.exited and receipt.residual == ()
    assert channel.channel_process.health_snapshot()["pid"] is None
    channel = official_factory({"enabled": True})
    assert (
        await channel.send_content_parts(
            "wechat:user123", [TextContent(text="")], {}
        )
        is None
    )
    assert channel.channel_process.health_snapshot()["pid"] is None
    receipt = await channel.stop()
    assert receipt.exited and receipt.residual == ()
