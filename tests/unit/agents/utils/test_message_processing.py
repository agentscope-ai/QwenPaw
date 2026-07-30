# -*- coding: utf-8 -*-
"""Tests for message_processing utils.

Covers:
- is_first_user_interaction
- prepend_to_message_content
"""
# pylint: disable=redefined-outer-name
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from agentscope.message import DataBlock, Msg, TextBlock, URLSource

from qwenpaw.agents.utils.message_processing import (
    _sanitize_display_filename,
    is_first_user_interaction,
    prepend_to_message_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(role: str, content="content"):
    m = MagicMock()
    m.role = role
    m.content = content
    return m


# ---------------------------------------------------------------------------
# is_first_user_interaction
# ---------------------------------------------------------------------------


class TestIsFirstUserInteraction:
    """P0: first user interaction detection."""

    def test_empty_messages_returns_false(self):
        assert is_first_user_interaction([]) is False

    def test_single_user_no_assistant_is_first(self):
        msgs = [_msg("user")]
        assert is_first_user_interaction(msgs) is True

    def test_user_with_assistant_is_not_first(self):
        msgs = [_msg("user"), _msg("assistant")]
        assert is_first_user_interaction(msgs) is False

    def test_multiple_users_is_not_first(self):
        msgs = [_msg("user"), _msg("user")]
        assert is_first_user_interaction(msgs) is False

    def test_system_then_user_is_first(self):
        """System messages before the user message are skipped."""
        msgs = [_msg("system"), _msg("user")]
        assert is_first_user_interaction(msgs) is True

    def test_multiple_system_then_user_is_first(self):
        msgs = [_msg("system"), _msg("system"), _msg("user")]
        assert is_first_user_interaction(msgs) is True

    def test_system_user_assistant_is_not_first(self):
        msgs = [_msg("system"), _msg("user"), _msg("assistant")]
        assert is_first_user_interaction(msgs) is False

    def test_only_system_messages_returns_false(self):
        msgs = [_msg("system"), _msg("system")]
        assert is_first_user_interaction(msgs) is False

    def test_only_assistant_returns_false(self):
        msgs = [_msg("assistant")]
        assert is_first_user_interaction(msgs) is False


# ---------------------------------------------------------------------------
# prepend_to_message_content
# ---------------------------------------------------------------------------


class TestPrependToMessageContent:
    """P0: guidance text is prepended to the message."""

    def test_prepend_to_string_content(self):
        msg = _msg("user", content="hello")
        prepend_to_message_content(msg, "guidance")
        assert msg.content == "guidance\n\nhello"

    def test_prepend_to_string_content_empty_string(self):
        msg = _msg("user", content="")
        prepend_to_message_content(msg, "guidance")
        assert msg.content == "guidance\n\n"

    def test_prepend_to_list_with_text_block(self):
        """Prepends into the first text block dict."""
        msg = _msg(
            "user",
            content=[
                {"type": "text", "text": "original"},
            ],
        )
        prepend_to_message_content(msg, "guidance")
        assert msg.content[0]["text"] == "guidance\n\noriginal"

    def test_prepend_inserts_block_when_no_text_block(self):
        """No text block → inserts new block at start."""
        msg = _msg(
            "user",
            content=[
                {"type": "image", "url": "http://img"},
            ],
        )
        prepend_to_message_content(msg, "guidance")
        first = msg.content[0]
        assert getattr(first, "type", None) == "text"
        assert getattr(first, "text", None) == "guidance"

    def test_prepend_to_non_list_non_str_content_noop(self):
        """Non-string, non-list content is left untouched."""
        msg = _msg("user", content=42)
        prepend_to_message_content(msg, "guidance")
        assert msg.content == 42

    def test_prepend_modifies_first_text_block_only(self):
        """Only the first text block is modified."""
        msg = _msg(
            "user",
            content=[
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
        )
        prepend_to_message_content(msg, "guidance")
        assert msg.content[0]["text"] == "guidance\n\nfirst"
        assert msg.content[1]["text"] == "second"

    def test_prepend_preserves_other_blocks(self):
        """Non-text blocks after the text block are preserved."""
        msg = _msg(
            "user",
            content=[
                {"type": "text", "text": "text"},
                {"type": "image", "url": "http://img"},
            ],
        )
        prepend_to_message_content(msg, "guidance")
        assert len(msg.content) == 2
        assert msg.content[1]["type"] == "image"


# ---------------------------------------------------------------------------
# _sanitize_display_filename — Issue #6453 CJK filename helper
# ---------------------------------------------------------------------------


class TestSanitizeDisplayFilename:
    """Sanity + regression tests for display-name sanitizer.

    The sanitizer is the security boundary between untrusted user-provided
    ``DataBlock.name`` / legacy-dict ``"name"`` values and the LLM prompt.
    Anything that can break prompt layout or mislead the model is removed
    before the display name is ever concatenated into a prompt sentence.
    """

    LOCAL_PATH = "/w/media/abc_file.docx"

    def test_none_falls_back_to_basename(self):
        assert (
            _sanitize_display_filename(None, self.LOCAL_PATH)
            == "abc_file.docx"
        )

    def test_empty_string_falls_back_to_basename(self):
        assert (
            _sanitize_display_filename("", self.LOCAL_PATH) == "abc_file.docx"
        )

    def test_non_str_input_falls_back_to_basename(self):
        assert (
            _sanitize_display_filename(12345, self.LOCAL_PATH)
            == "abc_file.docx"
        )

    def test_plain_ascii_passthrough(self):
        assert (
            _sanitize_display_filename("report.pdf", self.LOCAL_PATH)
            == "report.pdf"
        )

    def test_chinese_cjk_passthrough(self):
        """The original Issue #6453 driver: CJK names survive sanitization."""
        assert (
            _sanitize_display_filename(
                "项目立项审批表.docx",
                self.LOCAL_PATH,
            )
            == "项目立项审批表.docx"
        )

    def test_url_encoded_cjk_is_unquoted(self):
        """Some browsers pre-escape CJK; the prompt must show the glyphs."""
        escaped = "%E9%A1%B9%E7%9B%AE%E7%AB%8B%E9%A1%B9.docx"
        assert (
            _sanitize_display_filename(escaped, self.LOCAL_PATH) == "项目立项.docx"
        )

    def test_invalid_percent_encoding_passthrough_safely(self):
        # Not a valid UTF-8 percent sequence → original chars kept.
        raw = "%ZZ%ZZ-broken.pdf"
        result = _sanitize_display_filename(raw, self.LOCAL_PATH)
        assert "broken.pdf" in result

    def test_control_chars_and_newlines_stripped(self):
        result = _sanitize_display_filename(
            "bad\x00\x01\r\n\t\x0b\x0cfile.pdf",
            self.LOCAL_PATH,
        )
        # Whitespace collapses to a single SP.
        assert "\n" not in result
        assert "\r" not in result
        assert "\t" not in result
        assert "\x00" not in result
        assert "file.pdf" in result

    def test_bidi_override_stripped(self):
        # RLO + executable-suffix that would otherwise be rendered backwards.
        payload = "hello\u202etxt.exe"
        result = _sanitize_display_filename(payload, self.LOCAL_PATH)
        assert "\u202e" not in result

    def test_bom_and_replacement_char_stripped(self):
        payload = "\ufeffreport\ufffd.pdf"
        cleaned = _sanitize_display_filename(payload, self.LOCAL_PATH)
        assert "\ufeff" not in cleaned
        assert "\ufffd" not in cleaned
        assert cleaned == "report.pdf"

    def test_excessively_long_name_is_ellipsized(self):
        # 5 chars + 200 chars of filler — total 205, capped to 120 with …
        name = "A" + "B" * 200 + ".zip"
        cleaned = _sanitize_display_filename(name, self.LOCAL_PATH)
        assert len(cleaned) <= 122  # 112 + 1 ellip + 8 suffix = 121, rounded
        assert "…" in cleaned

    def test_whitespace_collapses(self):
        cleaned = _sanitize_display_filename(
            "  my   file  name.pdf  ", self.LOCAL_PATH
        )
        assert cleaned == "my file name.pdf"

    def test_all_controls_returns_basename(self):
        # Entire name is unprintable → fallback to basename.
        assert (
            _sanitize_display_filename("\x00\x01\x02", self.LOCAL_PATH)
            == "abc_file.docx"
        )


# ---------------------------------------------------------------------------
# process_file_and_media_blocks_in_message — filename-in-hint injection
# ---------------------------------------------------------------------------


class TestProcessFileBlocksInjectsDisplayName:
    """Issue #6453 regression: display name is included in file hint.

    Covers both the 2.0 Pydantic ``DataBlock`` path and the 1.x legacy dict
    path.
    """

    @staticmethod
    def _fake_load_config(language: str):
        cfg = MagicMock()
        cfg.agents.language = language
        return cfg

    def _msg_with(self, blocks):
        msg = Msg(name="user", role="user", content=[])
        msg.content = list(blocks)
        return msg

    def test_datablock_with_cjk_name_shown_in_zh_hint(self):
        path = "/ws/media/abc_code.docx"
        db = DataBlock(
            source=URLSource(
                url=f"file://{path}", media_type="application/msword"
            ),
            name="特斯拉财报Q2分析.docx",
        )
        msg = self._msg_with([db])

        with patch(
            "qwenpaw.agents.utils.message_processing.load_config",
            return_value=self._fake_load_config("zh"),
        ):
            import asyncio
            from qwenpaw.agents.utils.message_processing import (
                process_file_and_media_blocks_in_message,
            )

            asyncio.run(process_file_and_media_blocks_in_message(msg))

        # The injected sibling TextBlock now contains the original CJK
        # display name and the local path.
        texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
        assert any("特斯拉财报Q2分析.docx" in t for t in texts)
        assert any(path in t for t in texts)

    def test_datablock_with_cjk_name_shown_in_en_hint(self):
        path = "/ws/media/abc_plan.pdf"
        db = DataBlock(
            source=URLSource(
                url=f"file://{path}", media_type="application/pdf"
            ),
            name="年度财务计划-2026.pdf",
        )
        msg = self._msg_with([db])

        with patch(
            "qwenpaw.agents.utils.message_processing.load_config",
            return_value=self._fake_load_config("en"),
        ):
            import asyncio
            from qwenpaw.agents.utils.message_processing import (
                process_file_and_media_blocks_in_message,
            )

            asyncio.run(process_file_and_media_blocks_in_message(msg))

        texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
        hint = next(t for t in texts if "downloaded to" in t)
        assert "年度财务计划-2026.pdf" in hint
        assert path in hint

    def test_datablack_no_name_falls_back_to_basename_in_zh(self):
        """When DataBlock.name is None, only the local path is shown."""
        path = "/ws/media/a1b2c3d_report.xlsx"
        db = DataBlock(
            source=URLSource(
                url=f"file://{path}", media_type="application/vnd"
            ),
            name=None,
        )
        msg = self._msg_with([db])

        with patch(
            "qwenpaw.agents.utils.message_processing.load_config",
            return_value=self._fake_load_config("zh"),
        ):
            import asyncio
            from qwenpaw.agents.utils.message_processing import (
                process_file_and_media_blocks_in_message,
            )

            asyncio.run(process_file_and_media_blocks_in_message(msg))

        texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
        assert any(path in t for t in texts)
        # Without display name, no quote is introduced
        assert not any("“" in t for t in texts)

    def test_legacy_dict_block_preserves_name_field(self):
        """1.x dict shape carries a name; it must surface in the hint."""
        block = {
            "type": "file",
            "source": {"type": "url", "url": "file:///tmp/m/d7a_log.txt"},
            "name": "服务器日志-7月28日.txt",
        }
        msg = self._msg_with([block])

        async def _fake_process_single_block(*_a, **_kw):
            return "/tmp/m/d7a_log.txt"

        with patch(
            "qwenpaw.agents.utils.message_processing.load_config",
            return_value=self._fake_load_config("en"),
        ), patch(
            "qwenpaw.agents.utils.message_processing._process_single_block",
            _fake_process_single_block,
        ):
            import asyncio
            from qwenpaw.agents.utils.message_processing import (
                process_file_and_media_blocks_in_message,
            )

            asyncio.run(process_file_and_media_blocks_in_message(msg))

        # Dict path reconstructs the array so find whatever was inserted as
        # a sibling TextBlock (inside msg.content it's dict-shaped).
        text_entries = [
            b.get("text", "")
            for b in msg.content
            if isinstance(b, dict) and b.get("type") == "text"
        ] + [b.text for b in msg.content if isinstance(b, TextBlock)]
        hint = next(t for t in text_entries if "downloaded" in t)
        assert "服务器日志-7月28日.txt" in hint
        assert "/tmp/m/d7a_log.txt" in hint

    def test_urlencoded_filename_in_name_is_decoded_before_display(self):
        path = "/ws/media/a_x.pdf"
        db = DataBlock(
            source=URLSource(
                url=f"file://{path}", media_type="application/pdf"
            ),
            name="%E5%AE%A1%E8%AE%A1%E6%8A%A5%E5%91%8A.pdf",
        )
        msg = self._msg_with([db])

        with patch(
            "qwenpaw.agents.utils.message_processing.load_config",
            return_value=self._fake_load_config("zh"),
        ):
            import asyncio
            from qwenpaw.agents.utils.message_processing import (
                process_file_and_media_blocks_in_message,
            )

            asyncio.run(process_file_and_media_blocks_in_message(msg))

        texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
        combined = " ".join(texts)
        # Decoded → raw CJK shown; raw percent-sequence never shown raw.
        assert "审计报告.pdf" in combined
        assert "%E5%AE%A1" not in combined
