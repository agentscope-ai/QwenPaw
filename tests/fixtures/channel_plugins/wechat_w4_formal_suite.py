"""Authentic released WeChat ZIP through Core/Agent and native HTTP effects."""

import hashlib
import json
import os
from pathlib import Path

import psutil
import pytest

from extension_process_suite import eventually
from real_host_runtime import LocalModel, bind_real_runtime
from wechat_w4_formal_support import (
    native_ilink,
    official_wechat_zip,
    runtime,
    wechat_host_import_guard,
)

__all__ = ["runtime", "native_ilink", "wechat_host_import_guard"]


@pytest.mark.asyncio
async def test_formal_zip_actual_agent_merge_native_target_and_host_paths(
    runtime, native_ilink, monkeypatch, tmp_path
):
    from agentscope.model._model_response import ChatResponse
    from agentscope.message import TextBlock
    from qwenpaw.agents import model_factory
    from qwenpaw.runtime._state_utils import StateProxy
    from qwenpaw.schemas import FileContent

    external = native_ilink
    cwd = tmp_path / "captured-host-cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    auth = cwd / "relative-auth/bot-token"
    auth.parent.mkdir()
    auth.write_text("temporary-file-token")
    context = auth.parent / "wechat_context_tokens.json"
    context.write_text(json.dumps({"old-user": "preserve-old-context"}))
    media = cwd / "relative-media"
    media.mkdir()
    payload = b"temporary host media bytes"
    file = media / "business.txt"
    file.write_bytes(payload)
    rt = await runtime(
        "wechat",
        source_factory=official_wechat_zip,
        bot_token="",
        bot_token_file="relative-auth/bot-token",
        media_dir="relative-media",
        base_url=external.mock.base_url,
        bot_prefix="[微信]",
        message_merge_enabled=True,
        message_merge_delay_ms=0,
    )
    # Observe the original helper's initial worker poll before it is stopped
    # and rebound to the real Agent. No obsolete mock long poll may steal the
    # subsequent genuine event after its client has disconnected.
    await eventually(lambda: bool(external.active_polls))
    initial_polls = set(external.active_polls)
    host = await bind_real_runtime(rt, monkeypatch)
    await eventually(lambda: initial_polls.isdisjoint(external.active_polls))
    calls = []

    class TwoTextModel(LocalModel):
        async def __call__(self, *args, **kwargs):
            calls.append(
                {"pid": os.getpid(), "messages": kwargs.get("messages")}
            )
            return ChatResponse(
                content=[
                    TextBlock(text="first agent line\n"),
                    TextBlock(text="second agent line"),
                ],
                is_last=True,
            )

    model = TwoTextModel(calls, "unused")
    monkeypatch.setattr(
        model_factory,
        "create_model_and_formatter",
        lambda **_: (model, model.formatter),
    )
    pid = rt.process.health_snapshot()["pid"]
    assert pid != os.getpid()
    assert Path(psutil.Process(pid).cwd()) != cwd
    config = rt.channel._launch_spec.config
    assert config["bot_token"] == ""
    assert config["bot_token_file"] == str(auth)
    assert config["media_dir"] == str(media)
    assert rt.channel._launch_spec.plugin_id == "wechat"
    target = "formal-user@im.wechat"
    native_context = "formal-native-context"
    external.mock.push_text_message(
        text="formal native inbound",
        from_user_id=target,
        context_token=native_context,
    )
    await eventually(lambda: len(external.mock.sent_messages) == 1)
    await eventually(
        lambda: any(
            isinstance(event, dict)
            and event.get("object") == "response"
            and event.get("status") == "completed"
            for event in host.events
        )
    )
    (tmp_path / "host-completed-event-shapes.json").write_text(
        json.dumps(
            [
                {
                    key: event.get(key)
                    for key in ("object", "status", "content")
                }
                for event in host.events
                if isinstance(event, dict)
                and event.get("object") == "message"
                and event.get("status") == "completed"
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
    assert len(calls) == 1 and calls[0]["pid"] == os.getpid()
    assert len(host.builds) == 1 and host.builds[0]["agent"] == "QwenPawAgent"
    assert host.builds[0]["session_id"] == "wechat:" + target
    assert len(rt.ws.requests) == 1
    request = rt.ws.requests[0]
    assert request.channel == "wechat" and request.user_id == target
    assert request.session_id == "wechat:" + target
    assert request.channel_meta["wechat_from_user_id"] == target
    sent = external.mock.sent_messages[0]
    assert sent["to_user_id"] == target
    assert sent["context_token"] == native_context
    assert sent["message_type"] == sent["message_state"] == 2
    assert sent["item_list"] == [
        {
            "type": 1,
            "text_item": {
                "text": "[微信]  first agent line\nsecond agent line",
            },
        }
    ]
    snapshot = StateProxy()
    await host.session.load_session_state(
        session_id="wechat:" + target,
        user_id=target,
        channel="wechat",
        agent=snapshot,
    )
    stored = json.dumps(snapshot.data, ensure_ascii=False)
    assert all(
        text in stored
        for text in (
            "formal native inbound",
            "first agent line",
            "second agent line",
        )
    )
    assert json.loads(context.read_text()) == {
        "old-user": "preserve-old-context",
        target: native_context,
    }
    assert auth.read_text() == "temporary-file-token"
    assert not (rt.source / "relative-auth").exists()
    meta = {
        "wechat_from_user_id": target,
        "wechat_context_token": native_context,
    }
    await rt.channel.send_content_parts(
        target,
        [FileContent(file_url=file.as_uri(), filename="business.txt")],
        meta,
    )
    assert len(external.mock.sent_messages) == 2
    assert len({row["client_id"] for row in external.mock.sent_messages}) == 2
    upload = next(
        row
        for row in external.requests
        if row["path"].endswith("/getuploadurl")
    )
    assert upload["body"]["to_user_id"] == target
    assert upload["body"]["rawsize"] == len(payload)
    assert upload["body"]["rawfilemd5"] == hashlib.md5(payload).hexdigest()
    assert len(external.uploads) == 1
    assert (
        external.uploads[0] != payload and len(external.uploads[0]) % 16 == 0
    )
    sent_file = external.mock.sent_messages[-1]
    assert sent_file["to_user_id"] == target
    assert sent_file["context_token"] == native_context
    assert sent_file["item_list"][0]["type"] == 4
    assert (
        sent_file["item_list"][0]["file_item"]["file_name"] == "business.txt"
    )
    assert all(row["authenticated"] for row in external.requests)
    assert file.read_bytes() == payload
    receipt = await rt.manager.stop_one("wechat")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert receipt.residual == () and not psutil.pid_exists(pid)
