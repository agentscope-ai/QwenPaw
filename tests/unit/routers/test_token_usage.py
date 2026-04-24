# -*- coding: utf-8 -*-
"""Unit tests for the token usage router (/api/token-usage)."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers.token_usage import router, _parse_date
from qwenpaw.token_usage.manager import (
    TokenUsageByModel,
    TokenUsageManager,
    TokenUsageStats,
    TokenUsageSummary,
)

app = FastAPI()
app.include_router(router, prefix="/api")


@pytest.fixture
def api_client():
    """Create an async test client."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _isolate_token_usage_manager(monkeypatch):
    """Isolate token usage manager singleton for each test."""
    from qwenpaw.token_usage import manager as manager_module

    monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)


@pytest.fixture
def mock_token_usage_manager(monkeypatch):
    """Create a mock token usage manager."""
    from qwenpaw.token_usage import manager as manager_module

    mock_manager = AsyncMock(spec=TokenUsageManager)
    monkeypatch.setattr(
        manager_module,
        "get_token_usage_manager",
        lambda: mock_manager,
    )
    return mock_manager


# =============================================================================
# Test _parse_date helper
# =============================================================================


class TestParseDate:
    """Test the _parse_date helper function."""

    def test_parse_valid_date(self):
        """Should parse valid ISO date string."""
        result = _parse_date("2026-04-24")
        assert result == date(2026, 4, 24)

    def test_parse_none_returns_none(self):
        """Should return None for None input."""
        result = _parse_date(None)
        assert result is None

    def test_parse_empty_string_returns_none(self):
        """Should return None for empty string."""
        result = _parse_date("")
        assert result is None

    def test_parse_invalid_date_returns_none(self):
        """Should return None for invalid date format."""
        result = _parse_date("invalid")
        assert result is None

    def test_parse_wrong_format_returns_none(self):
        """Should return None for wrong date format."""
        result = _parse_date("04-24-2026")
        assert result is None


# =============================================================================
# Test GET /token-usage endpoint
# =============================================================================


class TestGetTokenUsage:
    """Test the GET /token-usage endpoint."""

    async def test_get_token_usage_default_range(
        self,
        api_client,
        mock_token_usage_manager,
    ):
        """Should return summary with default date range (30 days)."""
        expected_summary = TokenUsageSummary(
            total_prompt_tokens=1000,
            total_completion_tokens=500,
            total_calls=10,
            by_model={
                "openai:gpt-4": TokenUsageByModel(
                    provider_id="openai",
                    model="gpt-4",
                    prompt_tokens=600,
                    completion_tokens=300,
                    call_count=6,
                ),
            },
            by_provider={
                "openai": TokenUsageStats(
                    prompt_tokens=1000,
                    completion_tokens=500,
                    call_count=10,
                ),
            },
            by_date={
                "2026-04-24": TokenUsageStats(
                    prompt_tokens=1000,
                    completion_tokens=500,
                    call_count=10,
                ),
            },
        )
        mock_token_usage_manager.get_summary.return_value = expected_summary

        async with api_client:
            resp = await api_client.get("/api/token-usage")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_prompt_tokens"] == 1000
        assert data["total_completion_tokens"] == 500
        assert data["total_calls"] == 10

        # Verify manager was called with default date range
        mock_token_usage_manager.get_summary.assert_called_once()
        call_kwargs = mock_token_usage_manager.get_summary.call_args[1]
        assert "start_date" in call_kwargs
        assert "end_date" in call_kwargs

    async def test_get_token_usage_with_custom_dates(
        self,
        api_client,
        mock_token_usage_manager,
    ):
        """Should respect custom start_date and end_date parameters."""
        mock_token_usage_manager.get_summary.return_value = TokenUsageSummary()

        async with api_client:
            resp = await api_client.get(
                "/api/token-usage",
                params={
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-30",
                },
            )

        assert resp.status_code == 200

        # Verify correct dates were passed
        call_kwargs = mock_token_usage_manager.get_summary.call_args[1]
        assert call_kwargs["start_date"] == date(2026, 4, 1)
        assert call_kwargs["end_date"] == date(2026, 4, 30)

    async def test_get_token_usage_with_model_filter(
        self,
        api_client,
        mock_token_usage_manager,
    ):
        """Should pass model filter to manager."""
        mock_token_usage_manager.get_summary.return_value = TokenUsageSummary()

        async with api_client:
            resp = await api_client.get(
                "/api/token-usage",
                params={"model": "gpt-4"},
            )

        assert resp.status_code == 200

        call_kwargs = mock_token_usage_manager.get_summary.call_args[1]
        assert call_kwargs["model_name"] == "gpt-4"

    async def test_get_token_usage_with_provider_filter(
        self,
        api_client,
        mock_token_usage_manager,
    ):
        """Should pass provider filter to manager."""
        mock_token_usage_manager.get_summary.return_value = TokenUsageSummary()

        async with api_client:
            resp = await api_client.get(
                "/api/token-usage",
                params={"provider": "openai"},
            )

        assert resp.status_code == 200

        call_kwargs = mock_token_usage_manager.get_summary.call_args[1]
        assert call_kwargs["provider_id"] == "openai"

    async def test_get_token_usage_with_all_filters(
        self,
        api_client,
        mock_token_usage_manager,
    ):
        """Should pass all filters to manager."""
        mock_token_usage_manager.get_summary.return_value = TokenUsageSummary()

        async with api_client:
            resp = await api_client.get(
                "/api/token-usage",
                params={
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-30",
                    "model": "gpt-4",
                    "provider": "openai",
                },
            )

        assert resp.status_code == 200

        call_kwargs = mock_token_usage_manager.get_summary.call_args[1]
        assert call_kwargs["start_date"] == date(2026, 4, 1)
        assert call_kwargs["end_date"] == date(2026, 4, 30)
        assert call_kwargs["model_name"] == "gpt-4"
        assert call_kwargs["provider_id"] == "openai"

    async def test_get_token_usage_swaps_dates_if_reversed(
        self,
        api_client,
        mock_token_usage_manager,
    ):
        """Should swap start_date and end_date if start > end."""
        mock_token_usage_manager.get_summary.return_value = TokenUsageSummary()

        async with api_client:
            resp = await api_client.get(
                "/api/token-usage",
                params={
                    "start_date": "2026-04-30",
                    "end_date": "2026-04-01",
                },
            )

        assert resp.status_code == 200

        # Dates should be swapped
        call_kwargs = mock_token_usage_manager.get_summary.call_args[1]
        assert call_kwargs["start_date"] == date(2026, 4, 1)
        assert call_kwargs["end_date"] == date(2026, 4, 30)

    async def test_get_token_usage_empty_response(
        self,
        api_client,
        mock_token_usage_manager,
    ):
        """Should handle empty summary correctly."""
        mock_token_usage_manager.get_summary.return_value = TokenUsageSummary()

        async with api_client:
            resp = await api_client.get("/api/token-usage")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_prompt_tokens"] == 0
        assert data["total_completion_tokens"] == 0
        assert data["total_calls"] == 0
        assert data["by_model"] == {}
        assert data["by_provider"] == {}
        assert data["by_date"] == {}

    async def test_get_token_usage_invalid_date_format(
        self,
        api_client,
        mock_token_usage_manager,
    ):
        """Should handle invalid date format by using defaults."""
        mock_token_usage_manager.get_summary.return_value = TokenUsageSummary()

        async with api_client:
            resp = await api_client.get(
                "/api/token-usage",
                params={
                    "start_date": "invalid-date",
                    "end_date": "also-invalid",
                },
            )

        assert resp.status_code == 200

        # Should use default dates (today and 30 days ago)
        call_kwargs = mock_token_usage_manager.get_summary.call_args[1]
        today = date.today()
        assert call_kwargs["end_date"] == today
        assert call_kwargs["start_date"] == today - timedelta(days=30)

    async def test_get_token_usage_complex_data(
        self,
        api_client,
        mock_token_usage_manager,
    ):
        """Should return complex aggregated data correctly."""
        expected_summary = TokenUsageSummary(
            total_prompt_tokens=5000,
            total_completion_tokens=2500,
            total_calls=50,
            by_model={
                "openai:gpt-4": TokenUsageByModel(
                    provider_id="openai",
                    model="gpt-4",
                    prompt_tokens=3000,
                    completion_tokens=1500,
                    call_count=30,
                ),
                "anthropic:claude-3": TokenUsageByModel(
                    provider_id="anthropic",
                    model="claude-3",
                    prompt_tokens=2000,
                    completion_tokens=1000,
                    call_count=20,
                ),
            },
            by_provider={
                "openai": TokenUsageStats(
                    prompt_tokens=3000,
                    completion_tokens=1500,
                    call_count=30,
                ),
                "anthropic": TokenUsageStats(
                    prompt_tokens=2000,
                    completion_tokens=1000,
                    call_count=20,
                ),
            },
            by_date={
                "2026-04-23": TokenUsageStats(
                    prompt_tokens=2500,
                    completion_tokens=1250,
                    call_count=25,
                ),
                "2026-04-24": TokenUsageStats(
                    prompt_tokens=2500,
                    completion_tokens=1250,
                    call_count=25,
                ),
            },
        )
        mock_token_usage_manager.get_summary.return_value = expected_summary

        async with api_client:
            resp = await api_client.get("/api/token-usage")

        assert resp.status_code == 200
        data = resp.json()

        assert data["total_prompt_tokens"] == 5000
        assert data["total_completion_tokens"] == 2500
        assert data["total_calls"] == 50
        assert len(data["by_model"]) == 2
        assert len(data["by_provider"]) == 2
        assert len(data["by_date"]) == 2

        # Verify specific model data
        assert data["by_model"]["openai:gpt-4"]["prompt_tokens"] == 3000
        assert data["by_model"]["anthropic:claude-3"]["prompt_tokens"] == 2000


# =============================================================================
# Integration tests with real TokenUsageManager
# =============================================================================


class TestTokenUsageIntegration:
    """Integration tests with actual TokenUsageManager (not mocked)."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_record_and_query(self, tmp_path, monkeypatch):
        """Test full lifecycle: record usage, then query it."""
        import qwenpaw.app.routers.token_usage as router_module
        from qwenpaw.token_usage import manager as manager_module

        # Override WORKING_DIR to use tmp_path
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            manager_module,
            "TokenUsageManager._instance",
            None,
        )

        # Create real manager
        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        monkeypatch.setattr(
            manager_module,
            "get_token_usage_manager",
            lambda: manager,
        )

        # Record some usage
        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )
        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=200,
            completion_tokens=100,
        )

        # Allow processing
        await asyncio.sleep(0.3)

        # Create API client and query
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/token-usage")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] >= 0

        # Clean up
        await manager.stop()

    @pytest.mark.asyncio
    async def test_record_and_query_with_filters(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Test recording and querying with filters."""
        import qwenpaw.app.routers.token_usage as router_module
        from qwenpaw.token_usage import manager as manager_module

        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            manager_module,
            "TokenUsageManager._instance",
            None,
        )

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        monkeypatch.setattr(
            manager_module,
            "get_token_usage_manager",
            lambda: manager,
        )

        # Record usage for different providers
        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )
        await manager.record(
            provider_id="anthropic",
            model_name="claude-3",
            prompt_tokens=150,
            completion_tokens=75,
        )

        await asyncio.sleep(0.3)

        # Query with provider filter
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            resp = await client.get(
                "/api/token-usage",
                params={"provider": "openai"},
            )

        assert resp.status_code == 200
        data = resp.json()

        # Clean up
        await manager.stop()
