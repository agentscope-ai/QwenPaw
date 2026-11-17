# -*- coding: utf-8 -*-
"""iLink send receipts that report success with only message_id."""
import asyncio
import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

_HOME = Path(tempfile.mkdtemp(prefix="qwenpaw-wechat-send-"))
os.environ.setdefault("QWENPAW_WORKING_DIR", str(_HOME))
os.environ.setdefault("QWENPAW_SECRET_DIR", str(_HOME / "secret"))

_PLUGIN = (
    Path(__file__).resolve().parents[3] / "plugins" / "channel" / "wechat"
)
if str(_PLUGIN) not in sys.path:
    sys.path.insert(0, str(_PLUGIN))

_platform = importlib.import_module("qwenpaw_channel_wechat.platform")
_errors = importlib.import_module("qwenpaw_channel_wechat.errors")
WeChatPlatform = _platform.WeChatPlatform
WeChatDeliveryError = _errors.WeChatDeliveryError


def _check(response, sent=False):
    WeChatPlatform._check_result(response, sent)


def _reason(response, sent=False):
    with pytest.raises(WeChatDeliveryError) as caught:
        _check(response, sent)
    return caught.value


def test_message_id_only_is_a_successful_send():
    _check({"message_id": "test-123"})
    _check({"message_id": 1001})


def test_ret_and_errcode_success_is_unchanged():
    _check({"ret": 0})
    _check({"errcode": 0})
    _check({"ret": 0, "errcode": 0, "message_id": "test-123"})


def test_status_errors_still_win_when_message_id_is_present():
    failed = _reason({"message_id": "test-123", "ret": 1}, sent=False)
    assert failed.reason_code == "PLATFORM_SEND_FAILED"
    assert failed.side_effect_possible is False
    failed = _reason({"message_id": "test-123", "errcode": 4}, sent=True)
    assert failed.reason_code == "PLATFORM_SEND_FAILED"
    assert failed.side_effect_possible is True
    invalid = _reason({"message_id": "test-123", "ret": -2})
    assert invalid.reason_code == "CONTEXT_TOKEN_INVALID"
    assert invalid.side_effect_possible is False


def test_missing_status_without_message_id_stays_unknown():
    samples = (
        None,
        [],
        {},
        {"message_id": ""},
        {"message_id": None},
        {"message_id": "test-123", "ret": "0"},
    )
    for response in samples:
        unknown = _reason(response)
        assert unknown.reason_code == "PLATFORM_RESULT_UNKNOWN"
        assert unknown.side_effect_possible is True


class _TextClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.sent = []

    async def send_text(self, user, text, context):
        self.sent.append((user, text, context))
        return self._responses.pop(0)


def test_message_id_receipt_does_not_drop_the_next_part(tmp_path):
    platform = WeChatPlatform(
        {
            "bot_token": "token",
            "workspace_dir": str(tmp_path),
            "bot_token_file": str(tmp_path / "token"),
        },
        None,
        None,
    )
    client = _TextClient(
        [{"message_id": "test-123"}, {"message_id": "test-456"}],
    )
    platform._client = client
    asyncio.run(
        platform.send_parts(
            {
                "wechat_from_user_id": "user-A",
                "wechat_context_token": "ctx-1",
            },
            [
                {"type": "text", "text": "one"},
                {"type": "text", "text": "two"},
            ],
        ),
    )
    assert client.sent == [
        ("user-A", "one", "ctx-1"),
        ("user-A", "two", "ctx-1"),
    ]
