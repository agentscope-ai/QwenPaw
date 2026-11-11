# -*- coding: utf-8 -*-
"""Per-channel tool-call format configuration and rendering."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.app.channels.renderer import (
    ChannelDisplayConfig,
    MessageRenderer,
    RenderStyle,
)
from qwenpaw.config.config import BaseChannelConfig, ConsoleConfig
from qwenpaw.plugins.channel_config import validate_channel_config
from qwenpaw.schemas import DataContent, Message, MessageType


CALL_TYPES = [
    MessageType.FUNCTION_CALL,
    MessageType.PLUGIN_CALL,
    MessageType.MCP_TOOL_CALL,
    MessageType.MESSAGE,
]


def call_message(message_type, arguments="secret"):
    return Message(
        type=message_type,
        role="assistant",
        content=[DataContent(data={"name": "search", "arguments": arguments})],
    )


@pytest.mark.parametrize("message_type", CALL_TYPES)
@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize("format_mode", ["name_only", "compact"])
@pytest.mark.parametrize(
    "markdown,emoji",
    [(True, True), (True, False), (False, True), (False, False)],
)
def test_single_line_formats(
    message_type,
    semantic,
    format_mode,
    markdown,
    emoji,
):
    renderer = MessageRenderer(
        RenderStyle(
            display_config=ChannelDisplayConfig.from_config(
                {"tool_call_format": format_mode},
            ),
            supports_markdown=markdown,
            supports_code_fence=True,
            use_emoji=emoji,
        ),
    )
    message = call_message(message_type, "first\nsecond\r\nthird\tfourth")
    if semantic:
        parts = [
            item.part for item in renderer.message_to_semantic_parts(message)
        ]
    else:
        parts = renderer.message_to_parts(message)
    label = "**search**" if markdown else "search"
    if emoji:
        label = "🔧 " + label
    expected = (
        label
        if format_mode == "name_only"
        else label + ": first second third fourth"
    )
    assert [part.text for part in parts] == [expected]


@pytest.mark.parametrize("message_type", CALL_TYPES)
@pytest.mark.parametrize(
    "limit,expected_length",
    [(0, 80), (200, 80), (79, 79), (5, 5)],
)
def test_compact_respects_both_preview_limits(
    message_type,
    limit,
    expected_length,
):
    renderer = MessageRenderer(
        RenderStyle(
            display_config=ChannelDisplayConfig.from_config(
                {
                    "tool_call_format": "compact",
                    "tool_call_max_length": limit,
                },
            ),
        ),
    )
    assert renderer.message_to_parts(call_message(message_type, "x" * 300))[
        0
    ].text == ("🔧 **search**: " + "x" * expected_length + "...")


@pytest.mark.parametrize("message_type", CALL_TYPES)
@pytest.mark.parametrize("format_mode", ["full", "name_only", "compact"])
def test_visibility_controls_take_priority(message_type, format_mode):
    display = ChannelDisplayConfig.from_config(
        {"tool_call_format": format_mode},
        show_tool_details=False,
    )
    renderer = MessageRenderer(RenderStyle(display_config=display))
    text = renderer.message_to_parts(call_message(message_type))[0].text
    assert "search" in text
    assert "secret" not in text
    if format_mode == "compact":
        assert text == "🔧 **search**: ..."
    display.show_tool_calls = False
    assert renderer.message_to_parts(call_message(message_type)) == []
    assert renderer.message_to_semantic_parts(call_message(message_type)) == []


@pytest.mark.parametrize("message_type", CALL_TYPES)
@pytest.mark.parametrize(
    "markdown,emoji,fence",
    [
        (True, True, True),
        (True, False, True),
        (False, False, True),
        (False, False, False),
    ],
)
def test_full_output_is_unchanged(message_type, markdown, emoji, fence):
    renderer = MessageRenderer(
        RenderStyle(
            supports_markdown=markdown,
            supports_code_fence=fence,
            use_emoji=emoji,
        ),
    )
    label = "**search**" if markdown else "search"
    if message_type == MessageType.MESSAGE:
        if emoji:
            label = "✅ " + label
        expected = (
            label + ":" + ("\n```\nsecret\n```" if fence else "\nsecret")
        )
    elif markdown or fence:
        if emoji and markdown:
            label = "🔧 " + label
        expected = label + "\n```\nsecret\n```"
    else:
        expected = "search: secret"
    message = call_message(message_type)
    assert renderer.message_to_parts(message)[0].text == expected
    assert renderer.message_to_semantic_parts(message)[0].part.text == expected


@pytest.mark.parametrize("format_mode", ["full", "name_only", "compact"])
def test_config_round_trip_channel_and_clone(tmp_path, format_mode):
    config = ConsoleConfig.model_validate_json(
        json.dumps(
            {
                "enabled": True,
                "media_dir": str(tmp_path),
                "tool_call_format": format_mode,
            },
        ),
    )
    assert config.model_dump()["tool_call_format"] == format_mode
    channel = ConsoleChannel.from_config(process=None, config=config)
    text = channel._renderer.message_to_parts(
        call_message(MessageType.PLUGIN_CALL),
    )[0].text
    assert ("secret" in text) == (format_mode != "name_only")
    assert ("\n" in text) == (format_mode == "full")
    cloned = channel.clone(
        config.model_copy(update={"tool_call_format": "name_only"}),
    )
    assert (
        cloned._renderer.message_to_parts(
            call_message(MessageType.PLUGIN_CALL),
        )[0].text
        == "🔧 **search**"
    )


@pytest.mark.parametrize("invalid", ["verbose", "", None, 3, []])
def test_invalid_config_rejected_and_untyped_config_falls_back(invalid):
    with pytest.raises(ValidationError):
        BaseChannelConfig(tool_call_format=invalid)
    assert (
        ChannelDisplayConfig.from_config(
            {"tool_call_format": invalid},
        ).tool_call_format
        == "full"
    )


def test_official_channel_schemas_support_format():
    root = Path(__file__).resolve().parents[4]
    for path in (root / "plugins" / "channel").glob("*/channel.json"):
        manifest = json.loads(path.read_text())
        schema = manifest["config_schema"]
        assert "tool_call_format" in manifest["config_fields"], path
        defaults = BaseChannelConfig().model_dump()
        assert schema["properties"]["tool_call_format"]["enum"] == [
            "full",
            "name_only",
            "compact",
        ]
        for format_mode in ("full", "name_only", "compact"):
            config = validate_channel_config(
                schema,
                {**defaults, "tool_call_format": format_mode},
            )
            assert config["tool_call_format"] == format_mode, path
        assert (
            validate_channel_config(schema, defaults)["tool_call_format"]
            == "full"
        ), path
        with pytest.raises(ValueError):
            validate_channel_config(
                schema,
                {**defaults, "tool_call_format": "verbose"},
            )


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ("x" * 80, "x" * 80),
        ({"query": "hello"}, "{'query': 'hello'}"),
        ("", "{}"),
    ],
)
def test_compact_short_arguments(arguments, expected):
    renderer = MessageRenderer(
        RenderStyle(
            display_config=ChannelDisplayConfig(tool_call_format="compact"),
        ),
    )
    assert (
        renderer.message_to_parts(
            call_message(MessageType.PLUGIN_CALL, arguments),
        )[0].text
        == "🔧 **search**: " + expected
    )


@pytest.mark.parametrize(
    "message_type",
    [MessageType.PLUGIN_CALL_OUTPUT, MessageType.MESSAGE],
)
def test_tool_results_are_unaffected(message_type):
    message = Message(
        type=message_type,
        role="assistant",
        content=[DataContent(data={"name": "search", "output": "found"})],
    )
    expected = MessageRenderer().message_to_parts(message)
    for format_mode in ("name_only", "compact"):
        renderer = MessageRenderer(
            RenderStyle(
                display_config=ChannelDisplayConfig(
                    tool_call_format=format_mode,
                ),
            ),
        )
        assert renderer.message_to_parts(message) == expected


@pytest.mark.parametrize("format_mode", ["name_only", "compact"])
def test_single_line_format_handles_non_string_tool_name(format_mode):
    renderer = MessageRenderer(
        RenderStyle(
            display_config=ChannelDisplayConfig(tool_call_format=format_mode),
        ),
    )
    message = Message(
        type=MessageType.MESSAGE,
        role="assistant",
        content=[DataContent(data={"name": 123, "arguments": "value"})],
    )
    text = renderer.message_to_parts(message)[0].text
    assert text == (
        "🔧 **123**" if format_mode == "name_only" else "🔧 **123**: value"
    )
