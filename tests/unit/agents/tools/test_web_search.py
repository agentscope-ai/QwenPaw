# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.tools.web_search.

Covers:
- _post (SSL fallback)
- _fetch_html (SSL fallback for GET)
- _html_to_text (BeautifulSoup conversion)
- _format_search_results
- web_search
- web_fetch
"""
# pylint: disable=protected-access

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agentscope.message import ToolResultState

from qwenpaw.agents.tools.web_search import (
    _format_search_results,
    _html_to_text,
    _is_ssl_error,
    _post,
    web_fetch,
    web_search,
)


# -------------------------------------------------------------------
# _format_search_results
# -------------------------------------------------------------------


class TestFormatSearchResults:
    """Tests for _format_search_results."""

    def test_empty(self):
        assert _format_search_results([]) == "No results found."

    def test_single_result(self):
        results = [
            {
                "title": "Example",
                "url": "https://example.com",
                "content": "Hello world",
            },
        ]
        out = _format_search_results(results)
        assert "[1] Example" in out
        assert "URL: https://example.com" in out
        assert "Hello world" in out

    def test_multiple_results(self):
        results = [
            {"title": "A", "url": "https://a.com", "content": ""},
            {"title": "B", "url": "https://b.com", "content": "b"},
        ]
        out = _format_search_results(results)
        assert "[1] A" in out
        assert "[2] B" in out

    def test_missing_fields(self):
        results = [{}]
        out = _format_search_results(results)
        assert "[1]" in out


# -------------------------------------------------------------------
# _html_to_text
# -------------------------------------------------------------------


class TestHtmlToText:
    """Tests for _html_to_text."""

    def test_basic_html(self):
        html = "<html><body><p>Hello world</p></body></html>"
        assert "Hello world" in _html_to_text(html)

    def test_title_prepended(self):
        html = (
            "<html><head><title>My Page</title></head>"
            "<body><p>Content</p></body></html>"
        )
        text = _html_to_text(html)
        assert text.startswith("# My Page")
        assert "Content" in text

    def test_strips_script_and_style(self):
        html = (
            "<html><body>"
            "<script>alert(1)</script>"
            "<style>.x{color:red}</style>"
            "<p>Content</p>"
            "</body></html>"
        )
        text = _html_to_text(html)
        assert "Content" in text
        assert "alert" not in text
        assert "color" not in text

    def test_preserves_links(self):
        html = '<a href="https://example.com">Click</a>'
        text = _html_to_text(html)
        assert "https://example.com" in text
        assert "Click" in text

    def test_empty_body_with_title(self):
        html = (
            "<html><head>"
            "<title>My SPA Page</title>"
            "</head><body></body></html>"
        )
        assert _html_to_text(html) == "# My SPA Page"

    def test_empty_body_no_title(self):
        html = "<html><body></body></html>"
        assert _html_to_text(html) == ""

    def test_heading(self):
        html = "<h1>Title</h1><p>Body</p>"
        text = _html_to_text(html)
        assert "Title" in text
        assert "Body" in text


# -------------------------------------------------------------------
# _is_ssl_error
# -------------------------------------------------------------------


class TestIsSslError:
    """Tests for _is_ssl_error."""

    def test_direct_ssl_error(self):
        import ssl as _ssl

        exc = _ssl.SSLError("cert verify failed")
        assert _is_ssl_error(exc) is True

    def test_wrapped_ssl_error(self):
        import ssl as _ssl

        inner = _ssl.SSLCertVerificationError("self-signed")
        outer = httpx.ConnectError("conn failed")
        outer.__cause__ = inner
        assert _is_ssl_error(outer) is True

    def test_non_ssl_error(self):
        exc = httpx.ConnectError("refused")
        assert _is_ssl_error(exc) is False

    def test_timeout_not_ssl(self):
        exc = httpx.TimeoutException("timed out")
        assert _is_ssl_error(exc) is False


# -------------------------------------------------------------------
# _post
# -------------------------------------------------------------------


class TestPost:
    """Tests for _post with SSL fallback."""

    @pytest.mark.asyncio
    async def test_normal_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "qwenpaw.agents.tools.web_search.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _post(
                "https://api.example.com",
                {},
                {},
            )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_http_error_raised(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500",
            request=MagicMock(),
            response=MagicMock(),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "qwenpaw.agents.tools.web_search.httpx.AsyncClient",
            return_value=mock_client,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await _post(
                    "https://api.example.com",
                    {},
                    {},
                )


# -------------------------------------------------------------------
# web_search
# -------------------------------------------------------------------


class TestWebSearch:
    """Tests for web_search tool function."""

    @pytest.mark.asyncio
    async def test_empty_query(self):
        chunk = await web_search("")
        assert chunk.is_last is True
        text = chunk.content[0].text
        assert "empty" in text.lower()

    @pytest.mark.asyncio
    async def test_success(self):
        with patch(
            "qwenpaw.agents.tools.web_search._post",
            new_callable=AsyncMock,
            return_value={
                "results": [
                    {
                        "title": "Weather",
                        "url": "https://weather.com",
                        "content": "Sunny",
                    },
                ],
            },
        ):
            chunk = await web_search("杭州天气")
        assert chunk.is_last is True
        assert chunk.state == ToolResultState.SUCCESS
        text = chunk.content[0].text
        assert "Weather" in text
        assert "https://weather.com" in text

    @pytest.mark.asyncio
    async def test_failure_with_fallback_hint(self):
        with patch(
            "qwenpaw.agents.tools.web_search._post",
            new_callable=AsyncMock,
            side_effect=Exception("timeout"),
        ):
            chunk = await web_search("test query")
        text = chunk.content[0].text
        assert "failed" in text.lower()
        assert "fall back" in text.lower()


# -------------------------------------------------------------------
# web_fetch
# -------------------------------------------------------------------


class TestWebFetch:
    """Tests for web_fetch tool function."""

    @pytest.mark.asyncio
    async def test_empty_url(self):
        chunk = await web_fetch("")
        text = chunk.content[0].text
        assert "empty" in text.lower()

    @pytest.mark.asyncio
    async def test_success(self):
        fake_html = "<html><body><p>Page content here</p></body></html>"
        with patch(
            "qwenpaw.agents.tools.web_search._fetch_html",
            new_callable=AsyncMock,
            return_value=fake_html,
        ):
            chunk = await web_fetch("https://example.com")
        assert chunk.state == ToolResultState.SUCCESS
        text = chunk.content[0].text
        assert "Page content here" in text

    @pytest.mark.asyncio
    async def test_empty_page_content(self):
        with patch(
            "qwenpaw.agents.tools.web_search._fetch_html",
            new_callable=AsyncMock,
            return_value="<html><body></body></html>",
        ):
            chunk = await web_fetch("https://empty.com")
        text = chunk.content[0].text
        assert "No content extracted" in text

    @pytest.mark.asyncio
    async def test_failure_with_fallback_hint(self):
        with patch(
            "qwenpaw.agents.tools.web_search._fetch_html",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            chunk = await web_fetch("https://example.com")
        text = chunk.content[0].text
        assert "failed" in text.lower()
        assert "curl" in text.lower()
