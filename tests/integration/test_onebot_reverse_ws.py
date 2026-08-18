# -*- coding: utf-8 -*-
"""End-to-end OneBot v11 channel flow — the test acts as the client.

Eighth channel on the mock-IM strategy, and the most direct: OneBot
uses a *reverse* WebSocket (the channel hosts the server; NapCat/
go-cqhttp connect in). So no mock server is needed at all — the test
itself connects to the channel's WS endpoint, pushes OneBot v11
message events, and receives send_private_msg/send_group_msg actions
over the same connection.

Flow: enable channel (fixed ws_port) -> test connects ws://.../ws
-> push private message event -> agent (mock LLM) -> receive
send_private_msg action frame.

API endpoints:
  - PUT /api/config/channels/onebot
  - GET /api/config/channels/onebot
"""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import HTTPServer

import pytest
from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MOCK_LLM_RESPONSE,
    MockLLMHandler,
    default_http_timeout,
    register_mock_provider,
    unregister_mock_provider,
)
from websockets.sync.client import connect as ws_connect

_HTTP_TIMEOUT = default_http_timeout(15.0)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_WS_PORT = _free_port()


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server for deterministic replies."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


@pytest.fixture(scope="module")
def onebot_channel_up(app_server):
    """Enable the OneBot channel (reverse WS server on a fixed port)."""
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/onebot",
        json={
            "enabled": True,
            "ws_host": "127.0.0.1",
            "ws_port": _WS_PORT,
            "require_mention": True,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    # Wait for the reverse WS server to accept connections.
    deadline = time.time() + 60.0
    ready = False
    while time.time() < deadline and not ready:
        try:
            with socket.create_connection(
                ("127.0.0.1", _WS_PORT),
                timeout=1.0,
            ):
                ready = True
        except OSError:
            time.sleep(0.3)
    assert ready, (
        "onebot reverse WS port never opened: "
        + app_server.logs_tail()[-3000:]
    )
    yield _WS_PORT
    app_server.api_request(
        "PUT",
        "/api/config/channels/onebot",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


class _OneBotClient:
    """Minimal NapCat-like client for the reverse WS."""

    def __init__(self, port: int) -> None:
        # A config write from an earlier test can schedule an agent
        # reload, which restarts channels and briefly closes this
        # reverse-WS server.  Retry so a restart in flight is tolerated
        # instead of surfacing as ConnectionRefusedError.
        deadline = time.time() + 30.0
        conn = None
        last_exc: OSError | None = None
        while time.time() < deadline:
            try:
                conn = ws_connect(
                    f"ws://127.0.0.1:{port}/ws",
                    open_timeout=10,
                )
                break
            except OSError as exc:
                last_exc = exc
                time.sleep(0.5)
        if conn is None:
            raise AssertionError(
                f"onebot reverse WS never accepted a connection: {last_exc}",
            )
        self.conn = conn
        # Announce lifecycle so the channel learns self_id (needed for
        # at-segment mention detection in group messages).
        self.conn.send(
            json.dumps(
                {
                    "post_type": "meta_event",
                    "meta_event_type": "lifecycle",
                    "sub_type": "connect",
                    "self_id": 900000002,
                    "time": int(time.time()),
                },
            ),
        )
        self.actions: list[dict] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        try:
            for raw in self.conn:
                try:
                    frame = json.loads(raw)
                except ValueError:
                    continue
                if "action" in frame:
                    with self._lock:
                        self.actions.append(frame)
                    # Ack the RPC so _call_api futures resolve.
                    echo = frame.get("echo")
                    if echo:
                        self.conn.send(
                            json.dumps(
                                {
                                    "status": "ok",
                                    "retcode": 0,
                                    "data": {"message_id": 1},
                                    "echo": echo,
                                },
                            ),
                        )
        except Exception:  # noqa: BLE001 - connection closed
            pass

    def push_private_message(self, *, text: str, user_id: int) -> None:
        event = {
            "post_type": "message",
            "message_type": "private",
            "time": int(time.time()),
            "self_id": 900000002,
            "user_id": user_id,
            "message_id": int(time.time() * 1000) % 10**9,
            "message": [{"type": "text", "data": {"text": text}}],
            "raw_message": text,
            "sender": {"user_id": user_id, "nickname": "integ-ob-user"},
        }
        self.conn.send(json.dumps(event))

    def push_raw(self, event: dict) -> None:
        """Send an arbitrary OneBot event frame."""
        self.conn.send(json.dumps(event))

    def push_group_message(
        self,
        *,
        text: str,
        group_id: int,
        user_id: int,
        mention_bot: bool = False,
    ) -> None:
        segments: list[dict] = []
        if mention_bot:
            segments.append(
                {"type": "at", "data": {"qq": "900000002"}},
            )
        segments.append({"type": "text", "data": {"text": text}})
        event = {
            "post_type": "message",
            "message_type": "group",
            "time": int(time.time()),
            "self_id": 900000002,
            "group_id": group_id,
            "user_id": user_id,
            "message_id": int(time.time() * 1000) % 10**9,
            "message": segments,
            "raw_message": text,
            "sender": {"user_id": user_id, "nickname": "integ-ob-grouper"},
        }
        self.conn.send(json.dumps(event))

    def wait_for_action(
        self,
        predicate,
        *,
        timeout: float = 25.0,
    ):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for action in self.actions:
                    if predicate(action):
                        return action
            time.sleep(0.2)
        return None

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass


@pytest.mark.integration
@pytest.mark.p1
def test_onebot_reverse_ws_accepts_client(
    app_server,
    onebot_channel_up,  # pylint: disable=redefined-outer-name
):
    """The channel's reverse WS server accepts a NapCat-like client.

    Test purpose:
      - Cover _start_ws_server/_handle_ws_connection accept path.

    API endpoints:
      - GET /api/config/channels/onebot
    """
    client = _OneBotClient(onebot_channel_up)
    try:
        resp = app_server.api_request(
            "GET",
            "/api/config/channels/onebot",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        assert resp.json().get("enabled") is True
    finally:
        client.close()


@pytest.mark.integration
@pytest.mark.p0
def test_onebot_private_message_roundtrip(
    app_server,
    onebot_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A private message event yields a send_private_msg action.

    Test purpose:
      - Core OneBot loop: event -> _handle_event -> segments parse ->
        agent (mock LLM) -> send_private_msg action over the same WS.

    Test flow:
      1. Register mock LLM; connect as a NapCat-like client.
      2. Push a private message event (retrying across reloads).
      3. Wait for a send_private_msg action whose message contains
         the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        matched = None
        for attempt in range(4):
            client = _OneBotClient(onebot_channel_up)
            try:
                client.push_private_message(
                    text="hello from onebot client",
                    user_id=700100 + attempt,
                )

                def _is_reply(action: dict) -> bool:
                    if action.get("action") not in (
                        "send_private_msg",
                        "send_msg",
                    ):
                        return False
                    params = action.get("params") or {}
                    message = params.get("message")
                    return MOCK_LLM_RESPONSE.split()[0] in json.dumps(
                        message,
                        ensure_ascii=False,
                    )

                matched = client.wait_for_action(_is_reply, timeout=25.0)
            finally:
                client.close()
            if matched is not None:
                break
            time.sleep(1.0)
        assert matched is not None, (
            "no send_private_msg captured: " + app_server.logs_tail()[-3000:]
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_onebot_group_requires_mention(
    app_server,
    onebot_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Group messages need an @bot mention when require_mention is on.

    Test purpose:
      - Cover BaseChannel._check_group_mention: an un-mentioned group
        message is dropped, while one carrying an at-segment for the
        bot goes through to the agent.

    Test flow:
      1. Push a plain group message; expect no reply action.
      2. Push a group message with an ``at`` segment targeting the
         bot's self_id; expect a send_group_msg reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        client = _OneBotClient(onebot_channel_up)
        try:
            client.push_group_message(
                text="plain group chatter",
                group_id=880001,
                user_id=770201,
                mention_bot=False,
            )
            silent = client.wait_for_action(
                lambda a: a.get("action") in ("send_group_msg", "send_msg"),
                timeout=8.0,
            )
            assert (
                silent is None
            ), f"un-mentioned group message should be ignored: {silent}"
        finally:
            client.close()

        matched = None
        for attempt in range(4):
            client = _OneBotClient(onebot_channel_up)
            try:
                client.push_group_message(
                    text="hello group",
                    group_id=880002 + attempt,
                    user_id=770202,
                    mention_bot=True,
                )

                def _is_group_reply(action: dict) -> bool:
                    if action.get("action") not in (
                        "send_group_msg",
                        "send_msg",
                    ):
                        return False
                    params = action.get("params") or {}
                    return MOCK_LLM_RESPONSE.split()[0] in json.dumps(
                        params.get("message"),
                        ensure_ascii=False,
                    )

                matched = client.wait_for_action(
                    _is_group_reply,
                    timeout=25.0,
                )
            finally:
                client.close()
            if matched is not None:
                break
            time.sleep(1.0)
        assert matched is not None, (
            "mentioned group message got no reply: "
            + app_server.logs_tail()[-3000:]
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_onebot_guild_and_notice_events(
    app_server,
    onebot_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Notice/meta events are tolerated alongside message events.

    Test purpose:
      - Cover the non-message post_type branches of _handle_event
        (notice + heartbeat meta) and confirm the connection keeps
        serving message events afterwards.

    Test flow:
      1. Push a notice event and a heartbeat meta event.
      2. Push a private message and expect the usual reply action.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        matched = None
        for attempt in range(4):
            client = _OneBotClient(onebot_channel_up)
            try:
                client.push_raw(
                    {
                        "post_type": "notice",
                        "notice_type": "group_increase",
                        "time": int(time.time()),
                        "self_id": 900000002,
                        "group_id": 880900,
                        "user_id": 770900,
                    },
                )
                client.push_raw(
                    {
                        "post_type": "meta_event",
                        "meta_event_type": "heartbeat",
                        "time": int(time.time()),
                        "self_id": 900000002,
                        "status": {"online": True, "good": True},
                        "interval": 5000,
                    },
                )
                client.push_private_message(
                    text="after notice events",
                    user_id=770901 + attempt,
                )

                def _is_reply(action: dict) -> bool:
                    if action.get("action") not in (
                        "send_private_msg",
                        "send_msg",
                    ):
                        return False
                    params = action.get("params") or {}
                    return MOCK_LLM_RESPONSE.split()[0] in json.dumps(
                        params.get("message"),
                        ensure_ascii=False,
                    )

                matched = client.wait_for_action(_is_reply, timeout=25.0)
            finally:
                client.close()
            if matched is not None:
                break
            time.sleep(1.0)
        assert matched is not None, (
            "no reply after notice events: " + app_server.logs_tail()[-2500:]
        )
    finally:
        unregister_mock_provider(app_server, provider_id)
