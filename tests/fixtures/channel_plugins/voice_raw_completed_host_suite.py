"""Missing neutral raw-completed seam, observed through actual Proxy/worker."""

import ast
import json
import os
from pathlib import Path
from typing import Any

import pytest
from raw_actor_test_support import raw_source

pytest_plugins = ["extension_process_suite"]


def legacy_extract(event):
    from qwenpaw.schemas import ContentType

    path = (
        Path(__file__).resolve().parents[3]
        / "tests/fixtures/channel_plugins/legacy_voice_conversation_relay.py"
    )
    tree = ast.parse(path.read_text())
    (fn,) = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_extract_text_from_event"
    ]
    fn.decorator_list = []
    ns = {"Any": Any, "ContentType": ContentType}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), ns)
    return ns[fn.name](event)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["message", "reasoning", "plugin_call_output"])
async def test_original_completed_text_survives_real_proxy_worker_for_legacy_speech(
    runtime, kind
):
    from qwenpaw.schemas import Message, TextContent, RefusalContent

    rt = await runtime(source_factory=raw_source)
    channel = rt.channel
    request = channel.build_agent_request_from_native(
        {
            "sender_id": "member",
            "session_id": "room-A",
            "content_parts": [{"type": "text", "text": "question"}],
            "meta": {},
        }
    )
    event = Message(
        object="message",
        type=kind,
        role="tool" if kind == "plugin_call_output" else "assistant",
        status="completed",
        content=[
            TextContent(text="  alpha\n⟦ original source headline ⟧  "),
            TextContent(text="   "),
            RefusalContent(refusal="  refused  "),
            TextContent(text="  omega  "),
        ],
    )
    original = [
        event.content[0].text,
        event.content[1].text,
        event.content[2].refusal,
        event.content[3].text,
    ]
    expected_speech = legacy_extract(event)
    assert expected_speech == "alpha\n⟦ original source headline ⟧  refused omega"
    assert (
        channel._display_config.show_thinking
        and channel._display_config.show_tool_results
    )
    target = channel.get_to_handle_from_request(request)
    meta = {}
    async with channel._response_scope(meta):
        await channel.on_event_message_completed(request, target, event, meta)
    state = await rt.process.call("fixture.inspect", {})
    effects = [row for row in state["effects"] if row["operation"] == "message.create"]
    assert len(effects) == 1
    assert (
        effects[0]["pid"]
        == state["pid"]
        == rt.process.health_snapshot()["pid"]
        != os.getpid()
    )
    assert effects[0]["content_source"] == "event"
    assert len(state["finish_calls"]) == 1
    observed = [p["text"] for p in effects[0]["content_parts"] if p["type"] == "text"]
    print(
        json.dumps(
            {
                "kind": kind,
                "pid": state["pid"],
                "original": original,
                "received": effects[0]["content_parts"],
                "legacy_speech": expected_speech,
                "received_speech": " ".join(v.strip() for v in observed),
                "finish_calls": state["finish_calls"],
            },
            ensure_ascii=False,
        )
    )
    # This asserts a missing legacy transport property on existing actual wire;
    # it does not call or pretend an unimplemented opt-in constructor exists.
    assert (
        observed == original
    ), "Existing semantic capability is a presentation projection, not lossless completed text"
    assert " ".join(v.strip() for v in observed) == expected_speech
