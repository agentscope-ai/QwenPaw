"""Original upload cancellation matrix and explicit stream uncertainty."""

import asyncio
from pathlib import Path
import threading
from unittest.mock import patch

import pytest

pytest.register_assert_rewrite("wecom_native_support")
from wecom_native_support import ingress, send, text_frame  # noqa: E402

pytest_plugins = ["wecom_native_support"]


@pytest.mark.parametrize("media_type", ["file", "image"])
@pytest.mark.parametrize("read_fails", [False, True])
async def test_cancelled_upload_waits_for_open_file(
    wecom_native, media_type, read_fails
):
    """Keep all original cancellation/file ownership assertions and budgets."""
    driver, peer, identity, server = wecom_native
    platform = driver._platform
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    locked = set()
    paths = []
    denied_deletes = []
    original_unlink = Path.unlink
    original_read = Path.read_bytes

    def slow_read(path):
        if not path.is_relative_to(platform._media_dir):
            return original_read(path)
        try:
            with path.open("rb") as handle:
                locked.add(str(path))
                paths.append(path)
                loop.call_soon_threadsafe(started.set)
                assert release.wait(timeout=5)
                if read_fails:
                    raise OSError("Read failed")
                return handle.read()
        finally:
            locked.discard(str(path))
            loop.call_soon_threadsafe(finished.set)

    def windows_unlink(path, *args, **kwargs):
        if str(path) in locked:
            denied_deletes.append(path)
            raise PermissionError("File is still open")
        return original_unlink(path, *args, **kwargs)

    with (
        patch.object(Path, "read_bytes", slow_read),
        patch.object(Path, "unlink", windows_unlink),
    ):
        task = asyncio.create_task(
            platform._upload_media(
                "data:image/png;base64,cG5nLWRhdGE=", media_type
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
            task.cancel()
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
            assert paths[0].is_file()
            assert platform._file_tasks
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.wait_for(finished.wait(), timeout=2)

    assert task.cancelled()
    assert not denied_deletes
    assert not paths[0].exists()
    assert server.rows("aibot_upload_media_init") == []
    assert server.rows("aibot_upload_media_chunk") == []
    assert server.rows("aibot_upload_media_finish") == []
    assert platform._file_tasks == platform._delivery_tasks == set()
    assert platform._upload_ack_futures == {}
    assert locked == set()


async def test_old_swallowed_stream_failure_is_typed_unknown_and_not_replayed(
    wecom_native, monkeypatch
):
    from qwenpaw_channel_wecom.errors import WeComDeliveryError

    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native, text_frame("detail-failure"))
    platform = driver._platform
    calls = []

    async def sdk_failure(frame, *, stream_id, content, finish):
        # External SDK call fails before producing any successful wire effect,
        # as in the old RuntimeError('down') fixture. Outcome is now explicit.
        calls.append((frame, stream_id, content, finish))
        raise RuntimeError("down")

    monkeypatch.setattr(platform._client, "reply_stream", sdk_failure)
    with pytest.raises(WeComDeliveryError) as error:
        await platform.send_stream_detail(
            driver._route_attrs(event["response_handle"]), "body"
        )
    assert error.value.reason_code == "PLATFORM_RESULT_UNKNOWN"
    assert error.value.side_effect_possible is True
    assert error.value.retryable is False
    assert len(calls) == 1 and calls[0][2:] == ("body", True)
    assert server.rows("aibot_respond_msg") == []

    # A distinct logical request proves the actual shared delivery journal,
    # without replaying the unjournaled direct platform call above.
    event = await ingress(wecom_native, text_frame("journal-failure"))
    first = await send(
        wecom_native,
        event["response_handle"],
        delivery="unknown-stream",
        operation="stream.start",
        stream_type="message",
        sequence=0,
        accumulated_text="body",
    )
    assert first == {
        "delivery_id": "unknown-stream",
        "state": "unknown",
        "reason_code": "PLATFORM_RESULT_UNKNOWN",
        "retryable": False,
    }
    second = await send(
        wecom_native,
        event["response_handle"],
        delivery="unknown-stream",
        operation="stream.start",
        stream_type="message",
        sequence=0,
        accumulated_text="body",
    )
    assert second == first
    assert len(calls) == 2
    assert server.rows("aibot_respond_msg") == []
