"""Original QQ scalar error/format predicates, retained literal inputs."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/qq"))


class TestSanitizeQQText:
    """Tests for _sanitize_qq_text function."""

    def test_sanitize_removes_http_urls(self):
        """Should remove http URLs from text."""
        from qwenpaw_channel_qq.formatting import _sanitize_qq_text

        text = "Check out https://example.com for more info"
        result, had_url = _sanitize_qq_text(text)

        assert had_url is True
        assert "https://example.com" not in result
        assert "[链接已省略]" in result

    def test_sanitize_removes_www_urls(self):
        """Should remove www URLs from text."""
        from qwenpaw_channel_qq.formatting import _sanitize_qq_text

        text = "Visit www.example.com today"
        result, had_url = _sanitize_qq_text(text)

        assert had_url is True
        assert "www.example.com" not in result
        assert "[链接已省略]" in result

    def test_sanitize_empty_text(self):
        """Should handle empty text."""
        from qwenpaw_channel_qq.formatting import _sanitize_qq_text

        result, had_url = _sanitize_qq_text("")

        assert result == ""
        assert had_url is False

    def test_sanitize_no_urls(self):
        """Should not modify text without URLs."""
        from qwenpaw_channel_qq.formatting import _sanitize_qq_text

        text = "Hello, this is a normal message"
        result, had_url = _sanitize_qq_text(text)

        assert result == text
        assert had_url is False


class TestAggressiveSanitizeQQText:
    """Tests for _aggressive_sanitize_qq_text function."""

    def test_aggressive_sanitize_removes_bare_domains(self):
        """Should remove bare domain names."""
        from qwenpaw_channel_qq.formatting import (
            _aggressive_sanitize_qq_text,
        )

        text = "Visit google.com for search"
        result, had_url = _aggressive_sanitize_qq_text(text)

        assert had_url is True
        assert "google.com" not in result
        assert "[链接已省略]" in result

    def test_aggressive_sanitize_handles_cn_domains(self):
        """Should handle .cn domain names."""
        from qwenpaw_channel_qq.formatting import (
            _aggressive_sanitize_qq_text,
        )

        text = "Check 12306.cn for tickets"
        result, had_url = _aggressive_sanitize_qq_text(text)

        assert had_url is True
        assert "12306.cn" not in result


class TestAsBool:
    """Tests for _as_bool function."""

    def test_as_bool_true_values(self):
        """Should convert various true values to True."""
        from qwenpaw_channel_qq.formatting import _as_bool

        assert _as_bool(True) is True
        assert _as_bool("1") is True
        assert _as_bool("true") is True
        assert _as_bool("TRUE") is True
        assert _as_bool("yes") is True
        assert _as_bool("Yes") is True
        assert _as_bool("on") is True

    def test_as_bool_false_values(self):
        """Should convert various false values to False."""
        from qwenpaw_channel_qq.formatting import _as_bool

        assert _as_bool(False) is False
        assert _as_bool("0") is False
        assert _as_bool("false") is False
        assert _as_bool("no") is False
        assert _as_bool("off") is False
        assert _as_bool("") is False
        assert _as_bool(None) is False


class TestIsUrlContentError:
    """Tests for _is_url_content_error function."""

    def test_is_url_content_error_with_304003(self):
        """Should detect URL content error with code 304003."""
        from qwenpaw_channel_qq.formatting import (
            _is_url_content_error,
            QQApiError,
        )

        exc = QQApiError(
            path="/test",
            status=400,
            data={"code": "304003", "message": "error"},
        )
        assert _is_url_content_error(exc) is True

    def test_is_url_content_error_with_chinese_message(self):
        """Should detect URL content error with Chinese message."""
        from qwenpaw_channel_qq.formatting import (
            _is_url_content_error,
            QQApiError,
        )

        exc = QQApiError(
            path="/test", status=400, data={"message": "消息内容不允许包含url"}
        )
        assert _is_url_content_error(exc) is True

    def test_is_url_content_error_with_code_40034028(self):
        """Should detect URL content error with code 40034028."""
        from qwenpaw_channel_qq.formatting import (
            _is_url_content_error,
            QQApiError,
        )

        exc = QQApiError(
            path="/test", status=400, data={"err_code": "40034028"}
        )
        assert _is_url_content_error(exc) is True

    def test_is_url_content_error_non_qq_api_error(self):
        """Should return False for non-QQApiError exceptions."""
        from qwenpaw_channel_qq.formatting import _is_url_content_error

        assert _is_url_content_error(ValueError("test")) is False
        assert _is_url_content_error(RuntimeError("test")) is False


class TestShouldPlaintextFallbackFromMarkdown:
    """Tests for _should_plaintext_fallback_from_markdown function."""

    def test_fallback_for_markdown_in_payload(self):
        """Should fallback when markdown is in error message."""
        from qwenpaw_channel_qq.formatting import (
            _should_plaintext_fallback_from_markdown,
            QQApiError,
        )

        exc = QQApiError(
            path="/test", status=400, data={"message": "markdown not allowed"}
        )
        assert _should_plaintext_fallback_from_markdown(exc) is True

    def test_fallback_for_50056_code(self):
        """Should fallback for code 50056."""
        from qwenpaw_channel_qq.formatting import (
            _should_plaintext_fallback_from_markdown,
            QQApiError,
        )

        exc = QQApiError(path="/test", status=400, data={"err_code": "50056"})
        assert _should_plaintext_fallback_from_markdown(exc) is True

    def test_fallback_for_chinese_markdown_error(self):
        """Should fallback for Chinese markdown error message."""
        from qwenpaw_channel_qq.formatting import (
            _should_plaintext_fallback_from_markdown,
            QQApiError,
        )

        exc = QQApiError(
            path="/test", status=400, data={"message": "不允许发送原生 markdown"}
        )
        assert _should_plaintext_fallback_from_markdown(exc) is True

    def test_no_fallback_for_5xx_errors(self):
        """Should not fallback for server errors."""
        from qwenpaw_channel_qq.formatting import (
            _should_plaintext_fallback_from_markdown,
            QQApiError,
        )

        exc = QQApiError(
            path="/test", status=500, data={"message": "markdown not allowed"}
        )
        assert _should_plaintext_fallback_from_markdown(exc) is False

    def test_no_fallback_for_non_api_errors(self):
        """Should not fallback for non-API errors."""
        from qwenpaw_channel_qq.formatting import (
            _should_plaintext_fallback_from_markdown,
        )

        assert (
            _should_plaintext_fallback_from_markdown(ValueError("test"))
            is False
        )
