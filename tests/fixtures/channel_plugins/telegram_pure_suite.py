"""Original pure algorithm assertions, with only ownership imports changed."""

import importlib
import sys
import pytest
from extension_sample import ROOT

sys.path.insert(0, str(ROOT / "plugins/channel/telegram"))
telegram_module = importlib.import_module("qwenpaw_channel_telegram.platform")
tg = importlib.import_module("qwenpaw_channel_telegram.cards.tool_guard")

CALLBACK_DATA_BUDGET = 64
_MARKDOWN_TABLE = "| A | B |\n|---|---|\n| 1 | 2 |"


class TestBuildApprovalKeyboard:
    def test_single_row_with_two_buttons(self):
        keyboard = tg.build_approval_keyboard("rid-1")

        rows = keyboard.inline_keyboard
        assert len(rows) == 1
        assert [button.text for button in rows[0]] == [
            "✅ Approve",
            "❌ Deny",
        ]

    def test_callback_data_carries_the_prefixed_request_id(self):
        keyboard = tg.build_approval_keyboard("rid-1")

        buttons = keyboard.inline_keyboard[0]
        assert buttons[0].callback_data == "tga:rid-1"
        assert buttons[1].callback_data == "tgd:rid-1"

    def test_callback_data_stays_inside_telegrams_byte_budget(self):
        """callback_data is hard-capped at 64 bytes by the Bot API."""
        # A uuid4 request_id is the longest value seen in production.
        request_id = "0" * 36
        keyboard = tg.build_approval_keyboard(request_id)

        for button in keyboard.inline_keyboard[0]:
            assert len(button.callback_data.encode("utf-8")) <= (
                CALLBACK_DATA_BUDGET
            )




class TestParseCallbackData:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("tga:rid-1", {"action": "approve", "request_id": "rid-1"}),
            ("tgd:rid-1", {"action": "deny", "request_id": "rid-1"}),
            ("tga:", {"action": "approve", "request_id": ""}),
        ],
    )
    def test_known_prefixes(self, raw, expected):
        assert tg._parse_callback_data(raw) == expected

    @pytest.mark.parametrize("raw", ["", "other:rid", "TGA:rid", "tg:rid"])
    def test_foreign_or_empty_data_is_ignored(self, raw):
        assert tg._parse_callback_data(raw) is None


class TestTelegramChunkText:
    """Tests for _chunk_text method."""

    def test_chunk_text_empty(self):
        """Empty text should return empty list."""
        result = telegram_module._chunk_text("")
        assert result == []

    def test_chunk_text_short(self):
        """Short text should return single chunk."""
        text = "Hello world"
        result = telegram_module._chunk_text(text)
        assert result == ["Hello world"]

    def test_chunk_text_exact_size(self):
        """Text at exactly chunk size should return single chunk."""
        text = "A" * 4000
        result = telegram_module._chunk_text(text)
        assert len(result) == 1
        assert len(result[0]) == 4000

    def test_chunk_text_long_splits(self):
        """Long text should be split into chunks."""
        text = "A" * 5000
        result = telegram_module._chunk_text(text)
        assert len(result) > 1
        assert all(len(chunk) <= 4000 for chunk in result)

    def test_chunk_text_respects_newlines(self):
        """Split should prefer newline boundaries."""
        text = "Line 1\n" * 1000  # Many lines
        result = telegram_module._chunk_text(text)
        # Each chunk should be at chunk size or less
        assert all(len(chunk) <= 4000 for chunk in result)

    def test_chunk_text_respects_spaces(self):
        """Split should fallback to space boundaries."""
        text = "word " * 2000  # Many words, no newlines
        result = telegram_module._chunk_text(text)
        assert all(len(chunk) <= 4000 for chunk in result)
        # First chunk should end with space
        assert result[0].endswith(" ")

    def test_chunk_text_no_good_boundary(self):
        """Long word without spaces should be hard split."""
        text = "A" * 5000  # Single long word
        result = telegram_module._chunk_text(text)
        assert len(result) > 1
        assert all(len(chunk) <= 4000 for chunk in result)




def test_telegram_base_urls_derive_api_and_file_prefixes():
    assert telegram_module._telegram_base_urls("") == ("", "")
    assert telegram_module._telegram_base_urls(
        " https://tg-api.example.com/ "
    ) == (
        "https://tg-api.example.com/bot",
        "https://tg-api.example.com/file/bot",
    )


@pytest.fixture
def cache():
    return tg.CardCache()


def test_two_instances_keep_cache_and_eviction_separate():
    first, second = tg.CardCache(), tg.CardCache()
    for number in range(501):
        first._cache_request_context(
            str(number), "shell", "high", "body", {"session_id": "A"}
        )
        first._mark_processed(str(number), "approve")
    assert len(first._request_context_cache) == 251
    assert len(first._processed_requests) == 251
    assert first._get_request_context("249") is None
    assert first._get_request_context("250")["session_ctx"] == {
        "session_id": "A"
    }
    assert first._get_request_context("500")["tool_name"] == "shell"
    assert second._get_request_context("500") is None
    assert second._processed_requests == {}


class TestRequestContextCache:
    def test_round_trip(self, cache):
        cache._cache_request_context(
            "rid-1",
            "shell",
            "high",
            "body",
            {"chat_id": "c1"},
        )

        assert cache._get_request_context("rid-1") == {
            "tool_name": "shell",
            "severity": "high",
            "body_text": "body",
            "session_ctx": {"chat_id": "c1"},
        }

    def test_unknown_request_returns_none(self, cache):
        assert cache._get_request_context("nope") is None

    def test_cache_at_limit_is_kept(self, monkeypatch, cache):
        monkeypatch.setattr(tg, "_CACHE_MAX_SIZE", 4)

        for index in range(4):
            cache._cache_request_context(f"rid-{index}", "t", "m", "", {})

        assert len(cache._request_context_cache) == 4


class TestMarkProcessed:
    def test_first_click_is_new_and_repeat_is_duplicate(self, cache):
        assert cache._mark_processed("rid-1", "approve") is False
        assert cache._mark_processed("rid-1", "approve") is True

    def test_recorded_action_is_stored(self, cache):
        cache._mark_processed("rid-1", "deny")

        assert cache._processed_requests["rid-1"] == "deny"


def test_native_update_without_message_has_no_message_metadata():
    from telegram import Update

    assert telegram_module._message_meta(Update(1)) == {}


def test_real_data_decoder_cancellation_propagates_without_upload_or_disk(
    tmp_path,
):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import httpx
    from telegram import Bot
    from telegram.request import HTTPXRequest

    calls = []

    def reject_external(request):
        calls.append(request)
        raise AssertionError("Decode cancellation must precede native upload")

    async def exercise():
        gate, entered = threading.Event(), threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        asyncio.get_running_loop().set_default_executor(executor)

        def occupy_decoder_thread():
            entered.set()
            gate.wait()

        executor.submit(occupy_decoder_thread)
        assert entered.wait(1)
        request = HTTPXRequest(
            httpx_kwargs={"transport": httpx.MockTransport(reject_external)}
        )
        bot = Bot("123:local-A", request=request, get_updates_request=request)
        queue = asyncio.Queue()
        platform = telegram_module.TelegramPlatform(
            {"bot_token": "123:local-A", "workspace_dir": str(tmp_path)},
            queue.put,
            queue.put,
            queue.put,
        )
        task = asyncio.create_task(
            platform._send_media_value(
                bot=bot,
                chat_id=12345,
                value="data:application/pdf;base64,cGRmLWRhdGE=",
                method_name="send_document",
                payload_name="document",
                message_thread_id=None,
            )
        )
        try:
            await asyncio.sleep(0)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled()
            assert calls == []
            assert not platform._media_dir.exists()
        finally:
            gate.set()
            await request.shutdown()

    asyncio.run(exercise())
