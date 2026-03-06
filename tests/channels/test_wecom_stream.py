# -*- coding: utf-8 -*-
import asyncio
import json
from types import SimpleNamespace
from urllib.parse import urlencode

from agentscope_runtime.engine.schemas.agent_schemas import (
    RunStatus,
    TextContent,
)

from copaw.app.channels.base import ContentType
from copaw.app.channels.wecom.channel import WeComChannel
from copaw.app.channels.wecom_common import (
    compute_msg_signature,
    decrypt_encrypted_message,
    encrypt_plaintext_message,
)


def _build_callback_request(
    *,
    token: str,
    encoding_aes_key: str,
    plaintext_json: dict,
    timestamp: str = "1772765475",
    nonce: str = "1772178227",
) -> tuple[str, str]:
    encrypt = encrypt_plaintext_message(
        encoding_aes_key=encoding_aes_key,
        plaintext=json.dumps(plaintext_json, ensure_ascii=False),
    )
    signature = compute_msg_signature(
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        encrypt=encrypt,
    )
    url = "http://test/wecom?" + urlencode(
        {
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
    )
    body = json.dumps({"encrypt": encrypt}, ensure_ascii=False)
    return url, body


def _decrypt_response_body(
    *,
    body: str,
    encoding_aes_key: str,
) -> dict:
    payload = json.loads(body)
    plaintext = decrypt_encrypted_message(
        encoding_aes_key=encoding_aes_key,
        encrypt=payload["encrypt"],
    )
    return json.loads(plaintext)


async def _process_returns_text(_request):
    yield SimpleNamespace(
        object="message",
        status=RunStatus.Completed,
        type=None,
        content=[],
    )
    yield SimpleNamespace(
        object="response",
        status=RunStatus.Completed,
        error=None,
    )


async def _process_without_output(_request):
    yield SimpleNamespace(
        object="response",
        status=RunStatus.Completed,
        error=None,
    )


def _build_channel(*, token: str, aes_key: str, process) -> WeComChannel:
    channel = WeComChannel(
        process=process,
        enabled=True,
        token=token,
        encoding_aes_key=aes_key,
        bot_prefix="[BOT] ",
    )

    def _message_to_content_parts(_event):
        return [
            TextContent(
                type=ContentType.TEXT,
                text="处理完成",
            ),
        ]

    setattr(channel, "_message_to_content_parts", _message_to_content_parts)
    return channel


def test_wecom_stream_reply_and_poll() -> None:
    token = "token123"
    aes_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    channel = _build_channel(
        token=token,
        aes_key=aes_key,
        process=_process_returns_text,
    )

    request_url, body = _build_callback_request(
        token=token,
        encoding_aes_key=aes_key,
        plaintext_json={
            "msgtype": "text",
            "text": {"content": "测试123"},
            "from": {"userid": "ZengXinMin"},
            "msgid": "msg-1",
        },
    )
    status, content_type, response_body = asyncio.run(
        channel.handle_callback(
            method="POST",
            request_url=request_url,
            body_text=body,
        ),
    )

    assert status == 200
    assert content_type == "text/plain; charset=utf-8"
    initial_reply = _decrypt_response_body(
        body=response_body,
        encoding_aes_key=aes_key,
    )
    assert initial_reply["msgtype"] == "stream"
    assert initial_reply["stream"]["finish"] is True
    assert initial_reply["stream"]["content"] == "[BOT] 处理完成"

    poll_url, poll_body = _build_callback_request(
        token=token,
        encoding_aes_key=aes_key,
        plaintext_json={
            "msgtype": "stream",
            "stream": {"id": initial_reply["stream"]["id"]},
            "from": {"userid": "ZengXinMin"},
        },
    )
    _, _, poll_response = asyncio.run(
        channel.handle_callback(
            method="POST",
            request_url=poll_url,
            body_text=poll_body,
        ),
    )
    poll_reply = _decrypt_response_body(
        body=poll_response,
        encoding_aes_key=aes_key,
    )
    assert poll_reply == initial_reply


def test_wecom_stream_deduplicates_same_msgid() -> None:
    token = "token123"
    aes_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    channel = _build_channel(
        token=token,
        aes_key=aes_key,
        process=_process_without_output,
    )

    request = {
        "msgtype": "text",
        "text": {"content": "重复消息"},
        "from": {"userid": "ZengXinMin"},
        "msgid": "dup-1",
    }
    request_url, body = _build_callback_request(
        token=token,
        encoding_aes_key=aes_key,
        plaintext_json=request,
    )
    _, _, first_response = asyncio.run(
        channel.handle_callback(
            method="POST",
            request_url=request_url,
            body_text=body,
        ),
    )
    _, _, second_response = asyncio.run(
        channel.handle_callback(
            method="POST",
            request_url=request_url,
            body_text=body,
        ),
    )

    first_reply = _decrypt_response_body(
        body=first_response,
        encoding_aes_key=aes_key,
    )
    second_reply = _decrypt_response_body(
        body=second_response,
        encoding_aes_key=aes_key,
    )
    assert first_reply["stream"]["id"] == second_reply["stream"]["id"]
    assert second_reply["stream"]["finish"] is True
    assert second_reply["stream"]["content"] == "[BOT] 我已收到。"
