"""Original pure/HTTP business assertions on the real migrated platform.

Only httpx's external transport is controlled. Worker ownership and host
routing are separately exercised by the official process suites.
"""

from pathlib import Path
from collections import OrderedDict
import asyncio
import sys

import httpx
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/mattermost"))
from qwenpaw_channel_mattermost.platform import MattermostPlatform


class HTTPBoundary(httpx.AsyncClient):
    def __init__(self):
        self.responses = {}
        self._requests = []
        super().__init__(transport=httpx.MockTransport(self.respond))

    async def post(self, url, **kwargs):
        self._requests.append({"url": url, "kwargs": kwargs})
        return await super().post(url, **kwargs)

    def respond(self, request):
        return self.responses.get(
            (request.method, request.url.path), httpx.Response(404)
        )

    def expect(
        self,
        method,
        url,
        response_status=200,
        response_json=None,
        response_text="",
    ):
        self.responses[method, url] = httpx.Response(
            response_status,
            **(
                {"json": response_json}
                if response_json is not None
                else {"text": response_text}
            ),
        )

    def expect_get(self, **kwargs):
        self.expect("GET", **kwargs)

    def expect_post(self, **kwargs):
        self.expect("POST", **kwargs)


@pytest_asyncio.fixture
async def mock_http_client():
    async with HTTPBoundary() as client:
        yield client


async def unused_callback(_value):
    raise AssertionError("Pure platform test unexpectedly invoked an event")


@pytest.fixture
def mattermost_channel(tmp_path):
    return MattermostPlatform(
        {
            "url": "https://mattermost.example.com",
            "bot_token": "test_token",
            "workspace_dir": str(tmp_path),
            "media_dir": str(tmp_path / "media"),
        },
        unused_callback,
        unused_callback,
    )


def test_original_constructor_values_and_bounded_owned_structures(tmp_path):
    config = {
        "enabled": True,
        "url": "https://mm.example.com/",
        "bot_token": "my_token_123",
        "bot_prefix": "[Bot] ",
        "media_dir": str(tmp_path / "custom_media"),
        "show_typing": False,
        "thread_follow_without_mention": True,
    }
    platform = MattermostPlatform(config, unused_callback, unused_callback)
    assert platform._url == "https://mm.example.com"
    assert platform._bot_token == "my_token_123"
    assert platform.config["bot_prefix"] == "[Bot] "
    assert platform._media_dir == tmp_path / "custom_media"
    assert (
        platform._thread_follow is True
        and platform.config["show_typing"] is False
    )
    assert isinstance(platform._typing_tasks, dict)
    assert isinstance(platform._participated_threads, OrderedDict)
    assert isinstance(platform._seen_sessions, OrderedDict)
    assert platform._bot_id == platform._bot_username == ""
    assert (
        platform._http is None
    ), "SDK connection belongs to worker start, not static construction"


def test_original_default_media_directory_is_retained():
    from qwenpaw.constant import WORKING_DIR

    platform = MattermostPlatform({}, unused_callback, unused_callback)
    assert platform._media_dir == WORKING_DIR / "media" / "mattermost"


@pytest.mark.asyncio
async def test_original_partial_bot_identity_values_remain_available(tmp_path):
    sys.path.insert(0, str(ROOT / "tests/integration"))
    from mock_mattermost import MockMattermost

    service = MockMattermost()
    service.responses["/api/v4/users/me"] = (200, {"id": "user_123"})
    service.start()
    states = []

    async def state(value):
        states.append(value)

    platform = MattermostPlatform(
        {
            "url": service.url,
            "bot_token": "local-token",
            "workspace_dir": str(tmp_path),
        },
        unused_callback,
        state,
    )
    try:
        await platform.start()
        async with asyncio.timeout(8):
            while "connected" not in states:
                await asyncio.sleep(0.01)
        assert platform._bot_id == "user_123" and platform._bot_username == ""
        assert platform.connected
    finally:
        await platform.stop()
        service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("source_type", ["data", "path", "file_url"])
async def test_file_upload_uses_display_name(
    mattermost_channel, mock_http_client, tmp_path, source_type
):
    local = tmp_path / "local.pdf"
    local.write_bytes(b"pdf-data")
    sources = {
        "data": "data:application/pdf;base64,cGRmLWRhdGE=",
        "path": str(local),
        "file_url": local.as_uri(),
    }
    mock_http_client.expect_post(
        url="/api/v4/files",
        response_status=201,
        response_json={"file_infos": [{"id": "file-id"}]},
    )
    mock_http_client.expect_post(
        url="/api/v4/posts",
        response_status=201,
        response_json={"id": "post-id"},
    )
    mattermost_channel._http = mock_http_client
    await mattermost_channel.send_parts(
        "recipient",
        "",
        [
            {
                "type": "file",
                "file_url": sources[source_type],
                "filename": "report.pdf",
            }
        ],
    )
    upload = mock_http_client._requests[0]["kwargs"]["files"]["files"]
    assert upload[0] == (
        "report.pdf" if source_type == "data" else "local.pdf"
    )
    assert upload[1].closed
    assert mock_http_client._requests[1]["kwargs"]["json"] == {
        "channel_id": "recipient",
        "message": "",
        "root_id": "",
        "file_ids": ["file-id"],
    }
    assert local.read_bytes() == b"pdf-data"
    if source_type == "data":
        assert not list(mattermost_channel._media_dir.iterdir())
    else:
        assert not mattermost_channel._media_dir.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("retry", [False, True])
async def test_actual_websocket_close_error_propagates_and_keeps_failed_resource(
    tmp_path, monkeypatch, retry
):
    sys.path.insert(0, str(ROOT / "tests/integration"))
    from mock_mattermost import MockMattermost

    service = MockMattermost()
    service.responses["/api/v4/users/me"] = (
        200,
        {"id": "bot_user_123", "username": "testbot"},
    )
    service.start()
    states = []

    async def state(value):
        states.append(value)

    platform = MattermostPlatform(
        {
            "url": service.url,
            "bot_token": "local-token",
            "workspace_dir": str(tmp_path),
        },
        unused_callback,
        state,
    )
    socket = None
    try:
        await platform.start()
        async with asyncio.timeout(8):
            while "connected" not in states:
                await asyncio.sleep(0.01)
        socket, task = platform._ws, platform._task
        assert (
            platform._bot_id == "bot_user_123"
            and platform._bot_username == "testbot"
        )
        original_close = type(socket).close
        entered = tmp_path / "actual-sdk-close-entered"
        fault = tmp_path / "sdk-close-fault"
        fault.touch()
        attempts = []

        async def close_failure(connection, *args, **kwargs):
            if connection is socket:
                entered.write_text(str(id(connection)))
                attempts.append(id(connection))
                if fault.exists():
                    raise OSError("controlled actual SDK close failure")
            return await original_close(connection, *args, **kwargs)

        with monkeypatch.context() as sdk:
            sdk.setattr(type(socket), "close", close_failure)
            with pytest.raises(
                OSError, match="controlled actual SDK close failure"
            ):
                await platform.stop()
            assert entered.read_text() == str(id(socket))
            assert platform._ws is socket and platform._task is task
            assert task.done() and isinstance(task.exception(), OSError)
            if retry:
                # Persistent failure must still propagate on another attempt.
                with pytest.raises(
                    OSError, match="controlled actual SDK close failure"
                ):
                    await platform.stop()
                assert attempts == [id(socket), id(socket)]
                assert platform._ws is socket and platform._task is task
                fault.unlink()
                await platform.stop()
                assert attempts == [id(socket), id(socket), id(socket)]
                assert (
                    platform._ws is None
                    and platform._task is None
                    and platform._http is None
                )
                assert not platform.connected
                assert not service.has_connection
    finally:
        if socket is not None:
            await original_close(socket)
        if platform._http is not None:
            await platform._http.aclose()
        if platform._task is not None:
            platform._task.cancel()
            await asyncio.gather(platform._task, return_exceptions=True)
        service.stop()


class TestMattermostFetchHistory:
    """Tests for history fetching methods."""


    @pytest.mark.asyncio
    async def test_fetch_thread_history_api_error(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should return empty string on API error."""
        mock_http_client.expect_get(
            url="/api/v4/posts/root_123/thread",
            response_status=404,
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._fetch_thread_history(
            root_id="root_123",
        )

        assert result == ""


    @pytest.mark.asyncio
    async def test_fetch_channel_history_api_error(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should return empty string on API error."""
        mock_http_client.expect_get(
            url="/api/v4/channels/channel_123/posts",
            response_status=403,
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._fetch_channel_history(
            mm_channel_id="channel_123",
        )

        assert result == ""
