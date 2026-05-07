# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_process():
    async def mock_handler(*_args, **_kwargs):
        yield MagicMock()

    return AsyncMock(side_effect=mock_handler)


@pytest.fixture
def xiaoyi_channel(mock_process, tmp_path):
    from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

    return XiaoYiChannel(
        process=mock_process,
        enabled=True,
        ak="ak",
        sk="sk",
        agent_id="agent_123",
        ws_url="wss://test",
        media_dir=str(tmp_path / "media"),
    )


# =============================================================================
# Init
# =============================================================================


def test_init_basic(xiaoyi_channel):
    assert xiaoyi_channel.enabled is True
    assert xiaoyi_channel.agent_id == "agent_123"
    assert isinstance(xiaoyi_channel._session_task_map, dict)
    assert xiaoyi_channel._connected is False


# =============================================================================
# Lifecycle
# =============================================================================


@pytest.mark.asyncio
async def test_start_creates_connections(xiaoyi_channel):
    with patch(
        "qwenpaw.app.channels.xiaoyi.channel.XiaoYiConnection.connect",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await xiaoyi_channel.start()

    assert xiaoyi_channel._conn1 is not None
    assert xiaoyi_channel._conn2 is not None


@pytest.mark.asyncio
async def test_stop_disconnects_connections(xiaoyi_channel):
    mock_conn = MagicMock()
    mock_conn.disconnect = AsyncMock()

    xiaoyi_channel._conn1 = mock_conn
    xiaoyi_channel._conn2 = mock_conn
    xiaoyi_channel._connected = True

    await xiaoyi_channel.stop()

    assert xiaoyi_channel._connected is False
    assert mock_conn.disconnect.call_count == 2


# =============================================================================
# Message Handling
# =============================================================================


@pytest.mark.asyncio
async def test_handle_incoming_message_routes_a2a(xiaoyi_channel):
    msg = {
        "agentId": "agent_123",
        "method": "message/stream",
        "jsonrpc": "2.0",
        "id": "1",
        "params": {
            "id": "task1",
            "sessionId": "s1",
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hi"}],
            },
        },
    }

    with patch.object(
        xiaoyi_channel,
        "_handle_a2a_request",
        new_callable=AsyncMock,
    ) as mock_handler:
        await xiaoyi_channel._handle_incoming_message(msg, "server1")

    mock_handler.assert_called_once()


@pytest.mark.asyncio
async def test_handle_incoming_message_clear_context(xiaoyi_channel):
    msg = {
        "agentId": "agent_123",
        "method": "clearContext",
        "sessionId": "s1",
        "id": "req1",
    }

    with patch.object(
        xiaoyi_channel,
        "_handle_clear_context",
        new_callable=AsyncMock,
    ) as mock_handler:
        await xiaoyi_channel._handle_incoming_message(msg, "server1")

    mock_handler.assert_called_once()


# =============================================================================
# A2A Processing
# =============================================================================


@pytest.mark.asyncio
async def test_a2a_enqueue(xiaoyi_channel):
    msg = {
        "params": {
            "sessionId": "s1",
            "id": "task1",
            "message": {
                "parts": [{"kind": "text", "text": "hello"}],
            },
        },
    }

    mock_enqueue = MagicMock()
    xiaoyi_channel._enqueue = mock_enqueue

    await xiaoyi_channel._handle_a2a_request(msg)

    mock_enqueue.assert_called_once()
    assert xiaoyi_channel._session_task_map["s1"] == "task1"


# =============================================================================
# Sending
# =============================================================================


@pytest.mark.asyncio
async def test_send_routes_to_connection(xiaoyi_channel):
    mock_conn = MagicMock()
    mock_conn.state.connected = True
    mock_conn.send_json = AsyncMock(return_value=True)

    xiaoyi_channel._conn1 = mock_conn
    xiaoyi_channel._connected = True
    xiaoyi_channel._session_task_map["s1"] = "t1"

    await xiaoyi_channel.send("s1", "hello", meta={"session_id": "s1"})

    assert mock_conn.send_json.called


@pytest.mark.asyncio
async def test_send_skips_when_not_connected(xiaoyi_channel):
    xiaoyi_channel._connected = False

    await xiaoyi_channel.send("s1", "hello")


# =============================================================================
# Media
# =============================================================================


@pytest.mark.asyncio
async def test_send_media_image(xiaoyi_channel):
    from agentscope_runtime.engine.schemas.agent_schemas import (
        ImageContent,
        ContentType,
    )

    mock_conn = MagicMock()
    mock_conn.state.connected = True
    mock_conn.send_json = AsyncMock(return_value=True)

    xiaoyi_channel._conn1 = mock_conn
    xiaoyi_channel._connected = True
    xiaoyi_channel._session_task_map["s1"] = "t1"

    img = ImageContent(
        type=ContentType.IMAGE,
        image_url="http://x.png",
    )

    await xiaoyi_channel.send_media(
        "s1",
        img,
        meta={"session_id": "s1"},
    )

    assert mock_conn.send_json.called


# =============================================================================
# Response Helpers
# =============================================================================


@pytest.mark.asyncio
async def test_clear_context_response(xiaoyi_channel):
    mock_conn = MagicMock()
    mock_conn.state.connected = True
    mock_conn.send_json = AsyncMock(return_value=True)

    xiaoyi_channel._conn1 = mock_conn
    xiaoyi_channel._connected = True

    await xiaoyi_channel._send_simple_response(
        "s1",
        "r1",
        {"status": {"state": "cleared"}},
    )

    assert mock_conn.send_json.called
    msg = mock_conn.send_json.call_args[0][0]
    detail = json.loads(msg["msgDetail"])
    assert detail["result"]["status"]["state"] == "cleared"
