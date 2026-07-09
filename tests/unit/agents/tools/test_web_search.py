# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.tools.web_search.

Covers:
- _post (SSL fallback)
- _format_search_results
- _format_extract_results
- web_search
- web_fetch
"""
# pylint: disable=protected-access

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agentscope.message import ToolResultState

from qwenpaw.agents.tools.web_search import (
    _format_extract_results,
    _format_search_results,
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
# _format_extract_results
# -------------------------------------------------------------------


class TestFormatExtractResults:
    """Tests for _format_extract_results."""

    def test_empty(self):
        assert _format_extract_results([]) == "No content extracted."

    def test_single(self):
        results = [
            {
                "url": "https://example.com",
                "raw_content": "page text",
            },
        ]
        out = _format_extract_results(results)
        assert "https://example.com" in out
        assert "page text" in out

    def test_multiple_joined(self):
        results = [
            {"url": "https://a.com", "raw_content": "aaa"},
            {"url": "https://b.com", "raw_content": "bbb"},
        ]
        out = _format_extract_results(results)
        assert "---" in out
        assert "aaa" in out
        assert "bbb" in out


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
        with patch(
            "qwenpaw.agents.tools.web_search._post",
            new_callable=AsyncMock,
            return_value={
                "results": [
                    {
                        "url": "https://example.com",
                        "raw_content": "Page content here",
                    },
                ],
            },
        ):
            chunk = await web_fetch("https://example.com")
        assert chunk.state == ToolResultState.SUCCESS
        text = chunk.content[0].text
        assert "Page content here" in text

    @pytest.mark.asyncio
    async def test_failure_with_fallback_hint(self):
        with patch(
            "qwenpaw.agents.tools.web_search._post",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            chunk = await web_fetch("https://example.com")
        text = chunk.content[0].text
        assert "failed" in text.lower()
        assert "fall back" in text.lower()
