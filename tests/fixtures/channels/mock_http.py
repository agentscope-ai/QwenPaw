# -*- coding: utf-8 -*-
"""
HTTP Mock Utilities for Channel Testing

Provides tools for mocking HTTP requests in channel tests.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Dict, List, Optional


class MockAiohttpResponse:
    """Mock aiohttp ClientResponse."""

    def __init__(
        self,
        status: int = 200,
        json_data: Optional[Dict] = None,
        text_data: str = "",
        response_data: Optional[bytes] = None,
        headers: Optional[Dict] = None,
    ):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data
        self._response_data = response_data
        self.headers = headers or {}

    async def json(self, **_kwargs) -> Dict:
        """Return JSON data."""
        return self._json_data

    async def text(self) -> str:
        """Return text data."""
        return self._text_data

    async def read(self) -> bytes:
        """Return bytes data."""
        if self._response_data is not None:
            return self._response_data
        return self._text_data.encode()


class MockAiohttpSession:
    """
    Mock aiohttp ClientSession for testing HTTP-based channels.

    Usage:
        session = MockAiohttpSession()
        session.expect_post(
            "https://api.example.com/send",
            response_status=200,
            response_json={"errcode": 0}
        )

        channel._http = session
        await channel.send("user", "hello")

        assert session.call_count == 1
    """

    def __init__(self):
        self._expectations: List[Dict] = []
        self._requests: List[Dict] = []
        self.call_count = 0

    def expect_post(
        self,
        url: Optional[str] = None,
        response_status: int = 200,
        response_json: Optional[Dict] = None,
        response_text: str = "",
        match_json: Optional[Dict] = None,
    ) -> None:
        """
        Set up expected POST request.

        Args:
            url: Expected URL (can be partial match)
            response_status: HTTP status code to return
            response_json: JSON response body
            response_text: Text response body
            match_json: Expected request JSON payload (partial match)
        """
        self._expectations.append(
            {
                "method": "POST",
                "url": url,
                "response_status": response_status,
                "response_json": response_json,
                "response_text": response_text,
                "match_json": match_json,
            },
        )

    def expect_get(
        self,
        url: Optional[str] = None,
        response_status: int = 200,
        response_json: Optional[Dict] = None,
        response_text: str = "",
        response_data: Optional[bytes] = None,
        headers: Optional[Dict] = None,
    ) -> None:
        """Set up expected GET request."""
        self._expectations.append(
            {
                "method": "GET",
                "url": url,
                "response_status": response_status,
                "response_json": response_json,
                "response_text": response_text,
                "response_data": response_data,
                "headers": headers or {},
            },
        )

    def expect_put(
        self,
        url: Optional[str] = None,
        response_status: int = 200,
        response_json: Optional[Dict] = None,
        response_text: str = "",
    ) -> None:
        """Set up expected PUT request."""
        self._expectations.append(
            {
                "method": "PUT",
                "url": url,
                "response_status": response_status,
                "response_json": response_json,
                "response_text": response_text,
            },
        )

    @asynccontextmanager
    async def post(self, url: str, **kwargs):
        """Mock POST request."""
        self._requests.append({"method": "POST", "url": url, "kwargs": kwargs})
        self.call_count += 1

        # Find matching expectation
        expectation = None
        for exp in self._expectations:
            if exp["method"] != "POST":
                continue
            if exp["url"] and exp["url"] not in url:
                continue
            expectation = exp
            break

        if expectation is None:
            response = MockAiohttpResponse(status=404, text_data="Not Found")
        else:
            response = MockAiohttpResponse(
                status=expectation["response_status"],
                json_data=expectation.get("response_json"),
                text_data=expectation.get("response_text", ""),
            )

        yield response

    @asynccontextmanager
    async def get(self, url: str, **kwargs):
        """Mock GET request."""
        self._requests.append({"method": "GET", "url": url, "kwargs": kwargs})
        self.call_count += 1

        expectation = None
        for exp in self._expectations:
            if exp["method"] != "GET":
                continue
            if exp["url"] and exp["url"] not in url:
                continue
            expectation = exp
            break

        if expectation is None:
            response = MockAiohttpResponse(status=404, text_data="Not Found")
        else:
            response = MockAiohttpResponse(
                status=expectation["response_status"],
                json_data=expectation.get("response_json"),
                text_data=expectation.get("response_text", ""),
                response_data=expectation.get("response_data"),
                headers=expectation.get("headers", {}),
            )

        yield response

    @asynccontextmanager
    async def put(self, url: str, **kwargs):
        """Mock PUT request."""
        self._requests.append({"method": "PUT", "url": url, "kwargs": kwargs})
        self.call_count += 1

        expectation = None
        for exp in self._expectations:
            if exp["method"] != "PUT":
                continue
            if exp["url"] and exp["url"] not in url:
                continue
            expectation = exp
            break

        if expectation is None:
            response = MockAiohttpResponse(status=404, text_data="Not Found")
        else:
            response = MockAiohttpResponse(
                status=expectation["response_status"],
                json_data=expectation.get("response_json"),
                text_data=expectation.get("response_text", ""),
            )

        yield response

    async def close(self) -> None:
        """Mock close - no-op."""
        return None


def create_mock_aiohttp_session() -> MockAiohttpSession:
    """Factory function to create mock session."""
    return MockAiohttpSession()
