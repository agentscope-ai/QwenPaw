"""Retain original file display-name oracle through authentic worker sends."""

import pytest

from wechat_w4_formal_support import (
    native_ilink,
    official_wechat_zip,
    runtime,
    wechat_host_import_guard,
)

__all__ = ["native_ilink", "runtime", "wechat_host_import_guard"]


@pytest.mark.asyncio
@pytest.mark.parametrize("source_type", ["data", "path", "file_url"])
async def test_file_display_name_survives_formal_send_pipeline(
    runtime, native_ilink, tmp_path, source_type
):
    from qwenpaw.schemas import FileContent

    media = tmp_path / "temporary-media"
    media.mkdir()
    rt = await runtime(
        "wechat",
        source_factory=official_wechat_zip,
        bot_token="temporary-file-token",
        bot_token_file=str(tmp_path / "token"),
        media_dir=str(media),
        base_url=native_ilink.mock.base_url,
    )
    local_file = rt.ws.workspace_dir / "local.pdf"
    local_file.write_bytes(b"pdf-data")
    sources = {
        "data": "data:application/pdf;base64,cGRmLWRhdGE=",
        "path": str(local_file),
        "file_url": local_file.as_uri(),
    }
    await rt.channel.send_content_parts(
        "recipient",
        [FileContent(file_url=sources[source_type], filename="report.pdf")],
        {
            "wechat_from_user_id": "recipient",
            "wechat_context_token": "context",
        },
    )
    assert len(native_ilink.mock.sent_messages) == 1
    sent = native_ilink.mock.sent_messages[0]
    expected = "report.pdf" if source_type == "data" else "local.pdf"
    assert sent["item_list"][0]["file_item"]["file_name"] == expected
    assert local_file.read_bytes() == b"pdf-data"
    assert not list(media.iterdir())
    assert sent["to_user_id"] == "recipient"
    assert sent["context_token"] == "context"
    receipt = await rt.manager.stop_one("wechat")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert receipt.residual == ()
