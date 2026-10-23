"""Uncovered legacy responsibilities on the current factory/platform boundary.

The original complete tests are preserved in yuanbao-legacy-snapshot. Private
parsers now produce wire dictionaries; the Core converts them to content DTOs.
Only real local HTTP is used for downloads; no parser/Driver is substituted.
"""

import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock
from urllib.parse import unquote, urlparse

import pytest

pytest.register_assert_rewrite("yuanbao_native_support")
from yuanbao_native_support import YuanbaoPlatform, inbound  # noqa: E402

from qwenpaw_channel_yuanbao.errors import YuanbaoDeliveryError  # noqa: E402

pytest_plugins = ["yuanbao_native_support"]
ROOT = Path(__file__).resolve().parents[3]


def platform(config):
    return YuanbaoPlatform(config, AsyncMock(return_value=True), AsyncMock())


def test_initial_configuration_and_unstarted_resources(tmp_path):
    value = platform(
        {
            "enabled": True,
            "app_id": "key_abc",
            "app_secret": "secret_xyz",
            "api_domain": "custom.domain.com",
            "bot_prefix": "[Test] ",
            "workspace_dir": str(tmp_path),
        }
    )
    assert value.enabled is True
    assert value.app_id == "key_abc" and value.app_secret == "secret_xyz"
    assert value.api_domain == "custom.domain.com"
    assert value.config["bot_prefix"] == "[Test] "
    assert value._media_dir == tmp_path / "media"
    assert value._ws is value._session is value._media_session is None
    assert value._connected is False and value._reconnect_attempts == 0
    assert value._bot_id == "" and value._token_manager is None
    assert isinstance(value._session_map, dict)


async def test_unconnected_send_is_typed_zero_effect(tmp_path):
    value = platform({"enabled": False, "workspace_dir": str(tmp_path)})
    with pytest.raises(YuanbaoDeliveryError) as caught:
        await value.send_parts(
            {"chat_type": "c2c", "sender_id": "handle"},
            [{"type": "text", "text": "hello"}],
            "direct",
            "unconnected",
        )
    assert caught.value.reason_code == "YUANBAO_NOT_CONNECTED"
    assert caught.value.side_effect_possible is False
    assert value._ws is value._session is value._media_session is None
    assert not value._operations and not list(tmp_path.iterdir())


@pytest.mark.parametrize("typed", [False, True])
def test_formal_factory_preserves_config_and_session_routing(tmp_path, typed):
    from qwenpaw.config.config import YuanbaoConfig
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = ROOT / "plugins/channel/yuanbao"
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text())
        ),
    )
    config = {
        "enabled": True,
        "app_id": "dict_key" if not typed else "obj_key",
        "app_secret": "dict_secret" if not typed else "obj_secret",
        "api_domain": "dict.domain.com" if not typed else "obj.domain.com",
        "bot_prefix": "[Dict] " if not typed else "[Obj] ",
    }
    value = description.create_proxy(
        AsyncMock(),
        YuanbaoConfig(**config) if typed else config,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        workspace_dir=tmp_path,
        instance_id="original-factory-oracle",
        generation=1,
        qwenpaw_version="2.2.2b4",
    )
    assert value.enabled is True and value.channel == "yuanbao"
    for key, expected in config.items():
        assert value._launch_spec.config[key] == expected
    assert "user123" in value.resolve_session_id("user123")
    # Group session_id now arrives from the actual worker's normalized event;
    # its unchanged group456 oracle is asserted by the real host group test.


@pytest.mark.parametrize(
    "part,expected",
    [
        (
            {"type": "image", "image_url": "https://example.com/photo.jpg"},
            "https://example.com/photo.jpg",
        ),
        ({"type": "file", "file_url": "/tmp/report.pdf"}, "/tmp/report.pdf"),
        ({"type": "text", "text": "no media"}, ""),
    ],
)
def test_legacy_media_url_extraction(part, expected):
    assert YuanbaoPlatform._extract_media_url(part) == expected


@pytest.mark.parametrize("mention", [None, "native-bot", "other_user"])
async def test_plain_text_and_custom_mention_parser(native_platform, mention):
    value, _, _, _ = native_platform
    body = [{"msg_type": "TIMTextElem", "msg_content": {"text": "你好呀"}}]
    if mention:
        body.insert(
            0,
            {
                "msg_type": "TIMCustomElem",
                "msg_content": {
                    "data": json.dumps(
                        {"elem_type": 1002, "user_id": mention}
                    ),
                },
            },
        )
    parts, mentioned = await value._parse_msg_body(
        body, is_group=bool(mention)
    )
    assert parts == [{"type": "text", "text": "你好呀"}]
    assert mentioned is (mention == "native-bot")
    assert await value._parse_msg_body([]) == ([], False)


@pytest.mark.parametrize(
    "kind", ["image", "audio", "document", "unnamed", "failed"]
)
async def test_legacy_download_parser_types_names_and_failure(
    native_platform, kind
):
    value, _, _, external = native_platform
    image = kind in {"image", "failed"}
    url = external.base + (
        "/missing" if kind == "failed" else "/assets/image.jpg"
    )
    content = {"image_info_array": [{"url": url}]} if image else {"url": url}
    filename = {"audio": "test_副本.mp3", "document": "陈灵威.txt"}.get(kind)
    if filename:
        content["file_name"] = filename
    parts, _ = await value._parse_msg_body(
        [
            {
                "msg_type": "TIMImageElem" if image else "TIMFileElem",
                "msg_content": content,
            }
        ]
    )
    if kind == "failed":
        assert parts == [{"type": "text", "text": "[image: download failed]"}]
        return
    assert len(parts) == 1
    part = parts[0]
    assert part["type"] == (
        "image" if image else "audio" if kind == "audio" else "file"
    )
    locator = part[
        "image_url" if image else "data" if kind == "audio" else "file_url"
    ]
    assert locator.startswith("file://")
    local = Path(unquote(urlparse(locator).path))
    # The real retained downloader adds its MIME fallback .bin extension;
    # the original business assertion concerns the exposed filename "file".
    assert local.name == ("image.jpg" if image else filename or "file.bin")
    assert local.read_bytes() == b"native-image"
    if not image and kind != "audio":
        assert part["filename"] == (filename or "file")


@pytest.mark.parametrize(
    "kind,accept",
    [
        ("self-prefix", False),
        ("custom-prefix", False),
        ("structured", False),
        ("structured", True),
    ],
)
async def test_legacy_bot_filters_and_explicit_accept(
    native_platform, kind, accept
):
    value, events, _, _ = native_platform
    value.accept_bot_messages = accept
    message = inbound(msg_id="bot-filter", group="293831858")
    message["from_account"] = {
        "self-prefix": "bot_native-bot",
        "custom-prefix": "bot_3c71636ecdf9455783ab22d3bfa21fd2",
        "structured": "szUvRH8s4ekettawNjDREmAG4W7h",
    }[kind]
    if kind == "structured":
        message["msg_body"][0]["msg_content"]["data"] = json.dumps(
            {
                "elem_type": 1013,
                "text": "在呢～",
                "user_id": "",
                "content": "",
            }
        )
    await value._handle_chat_message(message)
    assert len(events) == int(accept)


@pytest.mark.parametrize("mentioned", [False, True])
async def test_legacy_group_mention_admission(native_platform, mentioned):
    value, events, _, _ = native_platform
    value.config["require_mention"] = True
    message = inbound(msg_id="group-mentioned", group="293831858")
    if mentioned:
        message["msg_body"].insert(
            0,
            {
                "msg_type": "TIMCustomElem",
                "msg_content": {
                    "data": json.dumps(
                        {"elem_type": 1002, "user_id": "native-bot"}
                    ),
                },
            },
        )
    await value._handle_chat_message(message)
    assert len(events) == int(mentioned)


@pytest.mark.parametrize("kind", ["text", "audio", "image"])
async def test_legacy_quote_injection_order_and_exact_text(
    native_platform, kind
):
    value, events, _, external = native_platform
    message = inbound(msg_id="quote-" + kind, text="11")
    desc = "test_副本.mp3" if kind == "audio" else "你好呀"
    message["cloud_custom_data"] = {
        "quote": {"type": 3 if kind == "audio" else 1, "desc": desc}
    }
    if kind == "image":
        message["msg_body"] = [
            {
                "msg_type": "TIMImageElem",
                "msg_content": {
                    "image_info_array": [
                        {"url": external.base + "/assets/image.jpg"}
                    ],
                },
            }
        ]
    await value._handle_chat_message(message)
    assert len(events) == 1
    parts = events[0]["content_parts"]
    expected = (
        "[quoted audio: test_副本.mp3]"
        if kind == "audio"
        else "[quoted message: 你好呀]"
    )
    assert parts[0] == {
        "type": "text",
        "text": expected + ("\n11" if kind != "image" else ""),
    }
    assert len(parts) == (2 if kind == "image" else 1)
    if kind == "image":
        assert parts[1]["image_url"].startswith("file://")


async def test_empty_send_and_real_media_session_cleanup(native_platform):
    value, _, _, external = native_platform
    session = await value._get_or_create_http_session()
    assert session is value._media_session and session is not value._session
    route = {
        "chat_type": "c2c",
        "sender_id": "u",
        "group_code": "",
        "msg_id": "h",
    }
    result = await value.send_parts(
        route, [{"type": "text", "text": ""}], "direct", "empty"
    )
    assert result["messages"] == "0" and external.sends == []
    await value._cleanup_session()
    assert session.closed and value._media_session is None
    await value._cleanup_session()
    assert value._media_session is None
    with pytest.raises(YuanbaoDeliveryError, match="OUTBOUND_TARGET_UNKNOWN"):
        value.resolve_target("", {})
