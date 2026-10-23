# -*- coding: utf-8 -*-
"""DingTalk static factory config and display preservation without SDKs."""

# pylint: disable=protected-access
import json
import sys
import pytest
from c6_artifacts import artifact_module, description, proxy
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.renderer import ChannelDisplayConfig
from qwenpaw.config.config import DingTalkConfig


def test_registration_and_construction_without_sdk_or_work(tmp_path):
    record = description("dingtalk")
    instance = proxy("dingtalk", {"enabled": True}, workspace_dir=tmp_path)
    assert isinstance(instance, BaseChannel) and instance.channel == "dingtalk"
    assert record.descriptor.entrypoint.module == "dingtalk.driver"
    assert not any(
        name.startswith(("dingtalk_stream", "alibabacloud_", "Tea."))
        for name in sys.modules
    )
    assert instance.channel_process.health_snapshot()["pid"] is None
    assert not (tmp_path / "media").exists()


@pytest.mark.parametrize("message_type", ["markdown", "card"])
def test_config_preserves_workspace_routing_and_host_arguments(
    tmp_path,
    monkeypatch,
    message_type,
):
    config = DingTalkConfig(
        enabled=True,
        client_id="robot-one",
        client_secret="secret-one",
        robot_code="robot-two",
        message_type=message_type,
        cron_message_type="text",
        card_template_id="template-one",
        card_template_key="answer",
        endpoint="https://gateway.test/",
        streaming_enabled=True,
        card_auto_layout=True,
        at_sender_on_reply=True,
        share_session_in_group=True,
        allow_from=["staff-one"],
        show_tool_calls=False,
    )
    original = config.model_dump()
    display = ChannelDisplayConfig(show_thinking=False)
    instance = proxy(
        "dingtalk",
        config,
        workspace_dir=tmp_path,
        display_config=display,
        no_text_debounce=False,
    )
    for key, value in original.items():
        if key != "no_text_debounce":
            assert instance._launch_spec.config[key] == value, key
    driver = artifact_module("dingtalk", "driver").DingTalkDriver()
    driver._config = dict(instance._launch_spec.config)
    monkeypatch.setattr(
        driver,
        "_route_attrs",
        lambda _handle: {
            "session_ctx": json.dumps(
                {"message_id": "message-one", "conversation_id": "room-one"},
            ),
        },
    )
    policy = driver.response_policy("response-one")
    assert policy.streaming is (message_type == "card")
    assert policy.prepare is True
    driver._config["streaming_enabled"] = False
    assert driver.response_policy("response-one").streaming is False
    assert instance.allow_from == {"staff-one"}
    assert (
        instance._display_config is display
        and instance._no_text_debounce is False
    )
    assert config.model_dump() == original
