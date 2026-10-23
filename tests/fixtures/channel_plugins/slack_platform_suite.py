"""Real SlackPlatform algorithms and native SDK teardown at external
boundaries."""

import asyncio
import importlib
import sys
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from extension_sample import ROOT
from slack_support import (
    eventually,
    fault_runtime,
    push,
    rows,
    set_mode,
    slack_sdk,
)


@pytest_asyncio.fixture
async def platform(slack_sdk, tmp_path, monkeypatch):
    import aiohttp

    for method in ("request", "get", "post", "ws_connect", "close"):
        monkeypatch.setattr(
            aiohttp.ClientSession,
            method,
            getattr(aiohttp.ClientSession, method),
        )
    for name in tuple(sys.modules):
        if name.startswith(
            (
                "slack_bolt",
                "slack_sdk",
                "qwenpaw_channel_slack",
                "qwenpaw_slack_test_boundary",
            )
        ):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(slack_sdk.site))
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/slack"))
    module = importlib.import_module("qwenpaw_channel_slack.platform")
    accepted, states = [], []

    async def event(value):
        accepted.append(value)
        return True

    async def state(value):
        states.append(value)

    value = module.SlackPlatform(
        {
            "bot_token": "local-A",
            "app_token": "xapp-test-token",
            "workspace_dir": str(tmp_path / "workspace"),
            "bot_prefix": "[SlackBot] ",
            "streaming_enabled": True,
            "require_mention": True,
        },
        event,
        state,
    )
    try:
        yield value, accepted, states
    finally:
        set_mode(slack_sdk.work, "")
        await value.stop()


@pytest.mark.asyncio
async def test_original_lazy_client_app_config_and_native_stop(
    platform, slack_sdk
):
    value, accepted, states = platform
    assert value._client is None and value._app is None
    first = await value.get_client()
    assert first is not None and value._client is first
    assert await value.get_client() is first
    assert value._app is not None
    assert (
        value.bot_token == "local-A" and value.app_token == "xapp-test-token"
    )
    assert value.bot_prefix == "[SlackBot] "
    assert value.channel == "slack"
    assert isinstance(value._socket_reconnect_lock, asyncio.Lock)
    assert isinstance(value._thread_context_cache, dict)
    assert value._thread_context_cache_ttl == 60.0
    assert value._event_handler is None
    await value.start()
    await eventually(lambda: value.connected)
    assert value._running is True
    assert value.media_dir.exists()
    assert value._sender is not None and value._event_handler is not None
    handler, task = value._handler, value._socket_mode_task
    assert not task.done()
    assert await handler.client.is_connected() is True
    native = [
        handler.client.message_processor,
        handler.client.current_session_monitor,
        handler.client.message_receiver,
    ]
    assert all(not task.done() for task in native)
    sender_http = await value._sender._get_http_session()
    handler_http = await value._event_handler._get_http_session()
    await value.stop()
    assert task.done()
    assert all(task.done() for task in native)
    assert sender_http.closed and handler_http.closed
    assert all(task.cancelling() <= 1 for task in native)
    assert value._handler is None and value._socket_mode_task is None
    assert value._sender is None and value._event_handler is None
    assert value._client is None and not value._running
    assert {
        row["name"] for row in rows(slack_sdk.work, "native-task-exit")
    } == {"message_processor", "current_session_monitor", "message_receiver"}
    assert accepted == []


def test_original_thread_cache_hits_misses_expiry_and_insertion_order(
    platform,
):
    value, _, _ = platform
    value.set_cached_thread_context("C123", "123.456", "context text")
    assert value.get_cached_thread_context("C123", "123.456") == "context text"
    assert value.get_cached_thread_context("C123", "999.999") is None
    value._thread_context_cache_ttl = 0.0
    assert value.get_cached_thread_context("C123", "123.456") is None
    value._thread_context_cache_ttl = 60.0
    value._thread_context_cache_max = 2
    value.set_cached_thread_context("C1", "1", "one")
    value.set_cached_thread_context("C2", "2", "two")
    assert value.get_cached_thread_context("C1", "1") == "one"
    value.set_cached_thread_context("C3", "3", "three")
    assert value.get_cached_thread_context("C1", "1") is None
    assert value.get_cached_thread_context("C2", "2") == "two"


@pytest.mark.parametrize(
    "error,want",
    [
        ("invalid_auth", True),
        ("token_revoked", True),
        ("missing_scope", True),
        ("rate_limited", False),
        ("something else", False),
    ],
)
def test_original_nonrecoverable_slack_errors(platform, error, want):
    from qwenpaw_channel_slack.platform import _is_non_recoverable_slack_error

    assert _is_non_recoverable_slack_error(Exception(error)) is want


@pytest.mark.asyncio
async def test_native_sdk_disconnect_does_not_replay_effect(
    platform, monkeypatch
):
    (
        "Use real WebClient.api_call and its native retry l"
        "oop at HTTP request."
    )
    from aiohttp import ClientConnectionError
    from slack_sdk.web import async_client
    from slack_sdk.web.async_base_client import AsyncBaseClient
    from slack_sdk.web import async_internal_utils

    value, _, _ = platform
    client = await value.get_client()
    assert client.retry_handlers == []
    effects = []

    class Response:
        status, headers, content_type = 200, {}, "application/json"

        async def __aenter__(self):
            effects.append("remote message accepted")
            return self

        async def __aexit__(self, *_args):
            return None

        async def json(self):
            raise ClientConnectionError(
                "connection lost after remote acceptance"
            )

    class Session:
        closed = False

        def request(self, *_args, **_kwargs):
            return Response()

    client.session = Session()
    monkeypatch.setattr(
        async_client.AsyncWebClient, "api_call", AsyncBaseClient.api_call
    )
    with pytest.raises(ClientConnectionError):
        await client.chat_postMessage(channel="C123", text="one remote effect")
    assert effects == ["remote message accepted"]
    client.session = None


@pytest.mark.asyncio
async def test_stop_close_failure_retains_resources_and_retry_finishes(
    platform, slack_sdk
):
    value, _, _ = platform
    await value.start()
    await eventually(lambda: value.connected)
    handler = value._handler
    set_mode(slack_sdk.work, "ws-close-unknown")
    with pytest.raises(Exception):
        await value.stop()
    assert value._handler is handler
    assert value._stopping is True
    with pytest.raises(RuntimeError, match="SLACK_STOP_INCOMPLETE"):
        await value.start()
    set_mode(slack_sdk.work, "")
    await value.stop()
    assert value._handler is None and not value._running


@pytest.mark.asyncio
async def test_cancelled_stop_caller_can_retry_same_owned_close(
    platform, slack_sdk
):
    value, _, _ = platform
    await value.start()
    await eventually(lambda: value.connected)
    set_mode(slack_sdk.work, "ws-close-block")
    stop = asyncio.create_task(value.stop())
    await eventually(lambda: bool(rows(slack_sdk.work, "ws-close")))
    stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop
    assert value._handler is not None
    set_mode(slack_sdk.work, "")
    await value.stop()
    assert len(rows(slack_sdk.work, "ws-close")) == 1
    assert value._handler is None


@pytest.mark.asyncio
async def test_native_receiver_finally_is_not_cancelled_twice(
    platform, slack_sdk
):
    value, _, _ = platform
    await value.start()
    await eventually(lambda: value.connected)
    set_mode(slack_sdk.work, "receiver-cleanup-block")
    stop = asyncio.create_task(value.stop())
    try:
        await eventually(
            lambda: bool(rows(slack_sdk.work, "receiver-cleanup-start"))
        )
        assert rows(slack_sdk.work, "receiver-cleanup-interrupted") == []
        assert not stop.done()
        set_mode(slack_sdk.work, "")
        await stop
        assert len(rows(slack_sdk.work, "receiver-cleanup-complete")) == 1
        assert rows(slack_sdk.work, "receiver-cleanup-interrupted") == []
        assert value._handler is None
    finally:
        set_mode(slack_sdk.work, "")
        await asyncio.gather(stop, return_exceptions=True)


@pytest.mark.asyncio
async def test_native_reconnect_replaced_receiver_stays_owned_until_quiescent(
    platform, slack_sdk
):
    value, _, _ = platform
    await value.start()
    await eventually(lambda: value.connected)
    handler = value._handler
    client = handler.client
    owned = {client.message_processor}
    sockets = [client.current_session]
    release, entered = asyncio.Event(), asyncio.Event()
    cleanup, stop = [], None

    def remember_native_connection():
        owned.update((client.current_session_monitor, client.message_receiver))
        sockets.append(client.current_session)

    remember_native_connection()
    try:
        # Native connect replaces both fields; only external receive is gated.
        await client.connect()
        remember_native_connection()
        intermediate = client.message_receiver
        socket = client.current_session
        receive = socket.receive

        async def held_external_receive():
            try:
                return await receive()
            except asyncio.CancelledError:
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cleanup.append("interrupted")
                    raise
                cleanup.append("complete")
                raise

        socket.receive = held_external_receive
        await asyncio.sleep(0)
        await client.connect()
        remember_native_connection()
        await entered.wait()
        assert intermediate is not client.message_receiver
        assert len(rows(slack_sdk.work, "ws-connect")) == 3
        stop = asyncio.create_task(value.stop())
        await asyncio.wait({stop}, timeout=1)
        print(
            {
                "stop_completed": stop.done(),
                "intermediate_done": intermediate.done(),
                "handler_retained": value._handler is handler,
                "cleanup": cleanup,
            }
        )
        assert not stop.done(), "STOP_SUCCEEDED_WITH_HELD_NATIVE_CLEANUP"
        assert not intermediate.done()
        assert value._handler is handler
        assert cleanup == []
        release.set()
        await stop
        assert cleanup == ["complete"]
        assert all(task.done() for task in owned)
        assert all(socket.closed for socket in sockets)
        assert client.aiohttp_client_session.closed
        assert value._handler is None and value._socket_mode_task is None
        assert value._sdk_tasks == set()
    finally:
        release.set()
        await asyncio.gather(*owned, return_exceptions=True)
        if stop is not None:
            await asyncio.gather(stop, return_exceptions=True)


@pytest.mark.asyncio
async def test_original_auth_id_success_three_attempt_retry_and_exhaustion(
    platform, slack_sdk
):
    value, _, _ = platform
    await value._fetch_bot_user_id()
    assert value.bot_user_id == "U999"
    set_mode(slack_sdk.work, "auth.test-transient-twice")
    (slack_sdk.work / "local-A/auth.json").write_text('{"user_id":"Uretry"}')
    await value._fetch_bot_user_id()
    assert value.bot_user_id == "Uretry"
    assert len(rows(slack_sdk.work, "auth.test")) == 4
    set_mode(slack_sdk.work, "auth.test-unknown")
    with pytest.raises(RuntimeError, match="Failed to fetch bot user_id"):
        await value._fetch_bot_user_id()
    assert len(rows(slack_sdk.work, "auth.test")) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled,running", [(True, True), (False, False)])
async def test_original_cancelled_or_inactive_socket_callback_no_restart(
    platform, cancelled, running
):
    value, _, states = platform
    task = asyncio.create_task(asyncio.sleep(0))
    if cancelled:
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    value._socket_mode_task, value._running = task, running
    value._on_socket_mode_task_done(task)
    await asyncio.sleep(0)
    assert value._background_tasks == set()
    assert states == []


@pytest.mark.asyncio
async def test_original_nonrecoverable_callback_and_max_attempts_stop(
    platform,
):
    value, _, states = platform

    async def failed_socket():
        raise ValueError("invalid_auth")

    task = asyncio.create_task(failed_socket())
    await asyncio.gather(task, return_exceptions=True)
    value._socket_mode_task, value._running = task, True
    value._on_socket_mode_task_done(task)
    await eventually(lambda: value._running is False)
    assert states == ["failed"]
    value._running, value._socket_reconnect_attempt = True, 12
    await value._restart_socket_mode("test")
    assert value._running is False


@pytest.mark.asyncio
async def test_original_normal_socket_exit_restarts_after_positive_delay(
    platform, slack_sdk
):
    value, _, _ = platform
    await value._on_init()
    task = asyncio.create_task(asyncio.sleep(0))
    await task
    value._socket_mode_task, value._running = task, True
    before = asyncio.get_running_loop().time()
    value._on_socket_mode_task_done(task)
    await eventually(lambda: value.connected)
    assert asyncio.get_running_loop().time() - before > 0
    assert value._socket_reconnect_attempt == 0
    assert value._running is True
    assert len(rows(slack_sdk.work, "ws-connect")) == 1


@pytest.mark.asyncio
async def test_original_start_preserves_attempt_and_restart_success_resets(
    platform, slack_sdk
):
    value, _, _ = platform
    value._socket_reconnect_attempt = 5
    await value.start()
    await eventually(lambda: value.connected)
    assert value._socket_reconnect_attempt == 5
    value._socket_reconnect_attempt = 3
    await value._restart_socket_mode("test")
    await eventually(
        lambda: len(rows(slack_sdk.work, "ws-connect")) == 2
        and value.connected
    )
    assert value._socket_reconnect_attempt == 0
    assert value._running is True
    assert len(rows(slack_sdk.work, "ws-connect")) == 2


@pytest.mark.asyncio
async def test_original_start_init_failure_does_not_set_running(
    platform, slack_sdk
):
    value, _, _ = platform
    set_mode(slack_sdk.work, "auth.test-unknown")
    with pytest.raises(RuntimeError, match="Failed to fetch bot user_id"):
        await value.start()
    assert value._running is False
    assert rows(slack_sdk.work, "ws-connect") == []


@pytest.mark.asyncio
async def test_original_nonrecoverable_sdk_start_failure_stops(
    platform, monkeypatch
):
    value, _, states = platform
    module = importlib.import_module("qwenpaw_channel_slack.platform")

    class FailedSDK:
        def __init__(self, *_args, **_kwargs):
            raise ValueError("invalid_auth")

    monkeypatch.setattr(module, "AsyncSocketModeHandler", FailedSDK)
    value._running = True
    await value._restart_socket_mode("test")
    assert value._running is False
    assert states == ["failed"]


def test_original_media_workspace_and_explicit_path_precedence(
    platform, tmp_path
):
    value, _, _ = platform
    assert value.media_dir == tmp_path / "workspace/media"
    custom = tmp_path / "custom_media"
    module = importlib.import_module("qwenpaw_channel_slack.platform")
    explicit = module.SlackPlatform(
        {"workspace_dir": str(tmp_path / "other"), "media_dir": str(custom)},
        value.on_event,
        value.on_state,
    )
    assert explicit.media_dir == custom
