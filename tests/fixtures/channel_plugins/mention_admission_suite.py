"""Real WeCom SDK and worker preserve trusted mention and ACL boundaries."""

import shutil
from pathlib import Path

import pytest

from wecom_closeout_suite import eventually, trust_directory
from wecom_native_support import WeComExternal, text_frame

pytest_plugins = ["extension_process_suite"]
ROOT = Path(__file__).resolve().parents[3]


def current_wecom_source(directory, key, **_):
    target = directory / key
    shutil.copytree(ROOT / "plugins/channel/wecom", target)
    return target


@pytest.mark.asyncio
async def test_wecom_directed_callbacks_pass_mentions_but_keep_acl(
    runtime, tmp_path
):
    directory = tmp_path / "gateway"
    directory.mkdir()
    server = WeComExternal(directory).start()
    try:
        rt = await runtime(
            "wecom",
            source_factory=current_wecom_source,
            dependency_paths=(trust_directory(tmp_path, server),),
            capture_ingress=True,
            bot_id="formal-bot",
            secret="formal-secret",
            ws_url=server.url,
            require_mention=True,
            access_control_group=True,
        )
        await eventually(
            lambda: rt.process.health_snapshot().get("platform_state")
            == "connected"
        )
        store = rt.channel._get_acl_store()
        store.add_to_whitelist("wecom", "sender-A")
        for number, bot in enumerate(["other-bot", "", None]):
            frame = text_frame("wrong-bot-" + str(number), group=True)
            frame["body"].update(aibotid=bot)
            frame["body"]["text"]["content"] = "@Bot hello"
            server.push(frame)
        frame = text_frame("wrong-command", group=True)
        frame["cmd"] = "untrusted_callback"
        frame["body"]["aibotid"] = "formal-bot"
        frame["body"]["text"]["content"] = "@Bot hello"
        server.push(frame)

        # An authenticated group delivery remains subject to Host ACL.
        frame = text_frame("denied", group=True, actor="denied-actor")
        frame["body"]["aibotid"] = "formal-bot"
        server.push(frame)
        await eventually(lambda: store.get_all_pending())
        assert rt.ws.received == []
        assert [row["user_id"] for row in store.get_all_pending()] == [
            "denied-actor"
        ]

        for number, (mid, group, bot) in enumerate(
            [
                ("text", True, "formal-bot"),
                ("mixed", True, "formal-bot"),
                ("no-body-bot-id", True, None),
                ("dm", False, "formal-bot"),
            ],
            start=1,
        ):
            frame = text_frame(mid, group=group)
            if bot is not None:
                frame["body"]["aibotid"] = bot
            frame["body"]["text"]["content"] = "@Bot hello"
            if mid == "mixed":
                frame["body"].update(
                    msgtype="mixed",
                    mixed={
                        "msg_item": [
                            {"msgtype": "text", "text": {"content": "hello"}},
                            {"msgtype": "file", "file": {}},
                        ]
                    },
                )
            server.push(frame)
            await eventually(lambda: len(rt.ws.received) == number)
            payload = rt.ws.received[-1]
            assert payload["meta"]["bot_mentioned"] is group
            assert payload["acl_sender_id"] == "sender-A"
            expected = (
                "hello\n[file: no url]" if mid == "mixed" else "@Bot hello"
            )
            assert [part.text for part in payload["content_parts"]] == [
                expected
            ]
        assert len(rt.ws.received) == 4
        assert rt.ws.requests == []
    finally:
        server.stop()
