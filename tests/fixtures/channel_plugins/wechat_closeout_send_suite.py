"""Original parts send semantics through authentic ZIP/Proxy/worker/iLink."""

import pytest

from wechat_w4_formal_support import (
    native_ilink,
    official_wechat_zip,
    runtime,
    wechat_host_import_guard,
)

__all__ = ["native_ilink", "runtime", "wechat_host_import_guard"]


@pytest.mark.asyncio
async def test_formal_parts_join_once_and_send_media_before_accumulated_text(
    runtime, native_ilink, tmp_path
):
    from qwenpaw.schemas import FileContent, TextContent

    media = tmp_path / "media"
    media.mkdir()
    file = media / "business.txt"
    file.write_text("temporary media")
    rt = await runtime(
        "wechat",
        source_factory=official_wechat_zip,
        bot_token="temporary-file-token",
        bot_token_file=str(tmp_path / "token"),
        media_dir=str(media),
        base_url=native_ilink.mock.base_url,
        bot_prefix="[Prefix]",
        message_merge_enabled=False,
    )
    target = "user123"
    meta = {
        "wechat_from_user_id": target,
        "wechat_context_token": "ctx_token",
    }
    await rt.channel.send_content_parts(
        "wechat:" + target,
        [TextContent(text="Hello"), TextContent(text="World")],
        dict(meta),
    )
    assert len(native_ilink.mock.sent_messages) == 1
    sent = native_ilink.mock.sent_messages[0]
    assert sent["to_user_id"] == target
    assert sent["context_token"] == "ctx_token"
    assert sent["item_list"] == [
        {"type": 1, "text_item": {"text": "[Prefix]  Hello\nWorld"}}
    ]
    await rt.channel.send_content_parts(
        "wechat:" + target,
        [
            TextContent(text="before media"),
            FileContent(file_url=file.as_uri(), filename=file.name),
            TextContent(text="after media"),
        ],
        dict(meta),
    )
    messages = native_ilink.mock.sent_messages[1:]
    assert len(messages) == 2
    assert [row["item_list"][0]["type"] for row in messages] == [4, 1]
    assert messages[0]["item_list"][0]["file_item"]["file_name"] == file.name
    assert messages[1]["item_list"] == [
        {
            "type": 1,
            "text_item": {"text": "[Prefix]  before media\nafter media"},
        }
    ]
    assert all(row["to_user_id"] == target for row in messages)
    assert all(row["context_token"] == "ctx_token" for row in messages)
    receipt = await rt.manager.stop_one("wechat")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert receipt.residual == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("delay_ms", [0, 1000])
async def test_formal_response_merge_keeps_media_ahead_of_buffered_text(
    runtime, native_ilink, tmp_path, delay_ms
):
    from extension_process_suite import eventually
    from qwenpaw.schemas import FileContent, TextContent

    media = tmp_path / "media"
    media.mkdir()
    file = media / "merge.txt"
    file.write_text("temporary merge media")
    rt = await runtime(
        "wechat",
        source_factory=official_wechat_zip,
        bot_token="temporary-file-token",
        bot_token_file=str(tmp_path / "token"),
        media_dir=str(media),
        base_url=native_ilink.mock.base_url,
        message_merge_enabled=True,
        message_merge_delay_ms=delay_ms,
    )
    meta = {
        "wechat_from_user_id": "user123",
        "wechat_context_token": "ctx_token",
    }
    async with rt.channel._response_scope(meta):
        await rt.channel.send_content_parts(
            "wechat:user123", [TextContent(text="A")], meta
        )
        assert native_ilink.mock.sent_messages == []
        await rt.channel.send_content_parts(
            "wechat:user123",
            [
                TextContent(text="B"),
                FileContent(file_url=file.as_uri(), filename=file.name),
                TextContent(text="C"),
            ],
            meta,
        )
        sent = native_ilink.mock.sent_messages
        assert [row["item_list"][0]["type"] for row in sent] == [4]
        assert sent[0]["item_list"][0]["file_item"]["file_name"] == file.name
        if delay_ms:
            await eventually(lambda: len(native_ilink.mock.sent_messages) == 2)
    sent = native_ilink.mock.sent_messages
    assert [row["item_list"][0]["type"] for row in sent] == [4, 1]
    assert sent[1]["item_list"] == [
        {"type": 1, "text_item": {"text": "A\n\n\nB\nC"}}
    ]
    assert all(row["to_user_id"] == "user123" for row in sent)
    assert all(row["context_token"] == "ctx_token" for row in sent)
    receipt = await rt.manager.stop_one("wechat")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert receipt.residual == ()


@pytest.mark.asyncio
async def test_formal_merge_strips_final_body_and_applies_latest_prefix_once(
    runtime, native_ilink, tmp_path
):
    from qwenpaw.schemas import TextContent

    rt = await runtime(
        "wechat",
        source_factory=official_wechat_zip,
        bot_token="temporary-file-token",
        bot_token_file=str(tmp_path / "token"),
        media_dir=str(tmp_path / "media"),
        base_url=native_ilink.mock.base_url,
        bot_prefix="[Configured]",
        message_merge_enabled=True,
        message_merge_delay_ms=0,
    )
    for number, override in enumerate(("", "[Metadata]"), 1):
        meta = {
            "wechat_from_user_id": "user123",
            "wechat_context_token": "ctx_token",
            "bot_prefix": "[First]",
        }
        async with rt.channel._response_scope(meta):
            await rt.channel.send_content_parts(
                "wechat:user123", [TextContent(text="  A  ")], meta
            )
            meta["bot_prefix"] = override
            await rt.channel.send_content_parts(
                "wechat:user123",
                [TextContent(text=" B "), TextContent(text=" C  ")],
                meta,
            )
            assert len(native_ilink.mock.sent_messages) == number - 1
        assert len(native_ilink.mock.sent_messages) == number
        sent = native_ilink.mock.sent_messages[-1]
        prefix = override or "[Configured]"
        assert sent["item_list"] == [
            {
                "type": 1,
                "text_item": {"text": prefix + "  A  \n\n\n B \n C"},
            }
        ]
        assert sent["to_user_id"] == "user123"
        assert sent["context_token"] == "ctx_token"
    receipt = await rt.manager.stop_one("wechat")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert receipt.residual == ()
