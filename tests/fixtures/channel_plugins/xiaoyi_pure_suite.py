"""Original pure XiaoYi oracles at their new native function boundaries."""
import importlib
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "plugins/channel/xiaoyi"


@pytest.fixture
def native(monkeypatch):
    monkeypatch.syspath_prepend(str(SOURCE))
    modules = {}
    for name in ("codec", "utils", "platform", "auth", "connection"):
        module = importlib.import_module("qwenpaw_channel_xiaoyi." + name)
        assert Path(
            module.__file__
        ).resolve() == SOURCE / "qwenpaw_channel_xiaoyi" / (name + ".py")
        modules[name] = module
    return modules




def test_event_tool_text_precedes_media_matching_legacy_send_order(
    native, tmp_path
):
    """
    Legacy extractor collects text/media separately and sends all text
    first.
    """
    platform = native["platform"].XiaoYiPlatform(
        {"agent_id": "agent", "workspace_dir": str(tmp_path)},
        None,
        None,
    )
    route = {
        "session_id": "s",
        "task_id": "t",
        "message_id": "m",
        "server_name": "primary",
    }
    # Real renderer order is media before the rendered tool label/text.
    frames = platform._outbound_frames(
        route,
        [
            {
                "type": "image",
                "image_url": "https://example.com/tool.png",
                "role": "rendered",
            },
            {"type": "text", "text": "tool result", "role": "rendered"},
        ],
        "event",
    )
    results = [json.loads(frame["msgDetail"])["result"] for frame in frames]
    assert [result["artifact"]["parts"] for result in results] == [
        [{"kind": "text", "text": "tool result"}],
        [
            {
                "kind": "file",
                "file": {
                    "name": "image",
                    "mimeType": "image/png",
                    "uri": "https://example.com/tool.png",
                },
            }
        ],
    ]
    assert [result["final"] for result in results] == [False, True]


@pytest.mark.parametrize(
    "source,parts,expected",
    [
        (
            "event",
            [
                {"type": "text", "text": "thinking", "role": "reasoning"},
                {"type": "text", "text": "body", "role": "message"},
                {"type": "text", "text": "raw refusal", "role": "refusal"},
                {"type": "text", "text": "omit fallback", "role": "rendered"},
            ],
            [
                {"kind": "reasoningText", "reasoningText": "thinking\n"},
                {"kind": "text", "text": "\n\nbody"},
                {"kind": "text", "text": "raw refusal"},
            ],
        ),
        (
            "event",
            [{"type": "text", "text": "tool fallback", "role": "rendered"}],
            [{"kind": "text", "text": "tool fallback"}],
        ),
        (
            "event",
            [{"type": "text", "text": "\nbody", "role": "message"}],
            [{"kind": "text", "text": "\nbody"}],
        ),
        (
            "direct",
            [{"type": "text", "text": "direct body"}],
            [{"kind": "text", "text": "direct body"}],
        ),
    ],
)
def test_native_semantic_roles_fallback_and_direct_layout(
    native, tmp_path, source, parts, expected
):
    platform = native["platform"].XiaoYiPlatform(
        {"agent_id": "agent", "workspace_dir": str(tmp_path)}, None, None
    )
    frames = platform._outbound_frames(
        {"session_id": "s", "task_id": "t", "message_id": "m"}, parts, source
    )
    assert len(frames) == 1
    assert (
        json.loads(frames[0]["msgDetail"])["result"]["artifact"]["parts"]
        == expected
    )


def test_event_ignores_ordinary_media_but_explicit_parts_keep_placeholder_and_media(  # noqa: E501
    native, tmp_path
):
    platform = native["platform"].XiaoYiPlatform(
        {"agent_id": "agent", "workspace_dir": str(tmp_path)}, None, None
    )
    route = {"session_id": "s", "task_id": "t", "message_id": "m"}
    image = {"type": "image", "image_url": "https://example.com/image.png"}
    assert (
        platform._outbound_frames(
            route, [{**image, "role": "message"}], "event"
        )
        == []
    )
    explicit = platform._outbound_frames(route, [image], "content_parts")
    results = [json.loads(frame["msgDetail"])["result"] for frame in explicit]
    assert [row["artifact"]["parts"] for row in results] == [
        [{"kind": "text", "text": "[Image: https://example.com/image.png]"}],
        [
            {
                "kind": "file",
                "file": {
                    "name": "image",
                    "mimeType": "image/png",
                    "uri": "https://example.com/image.png",
                },
            }
        ],
    ]
    direct = platform._outbound_frames(route, [image], "media")
    assert [
        json.loads(frame["msgDetail"])["result"]["artifact"]["parts"]
        for frame in direct
    ] == [results[1]["artifact"]["parts"]]
