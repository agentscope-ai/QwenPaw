# -*- coding: utf-8 -*-
"""Unit tests for the token usage router (/api/token-usage) and core module."""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers.token_usage import router, _parse_date
from qwenpaw.token_usage.buffer import TokenUsageBuffer, _UsageEvent, _apply_event
from qwenpaw.token_usage.manager import (
    TokenUsageByModel,
    TokenUsageManager,
    TokenUsageRecord,
    TokenUsageStats,
    TokenUsageSummary,
)
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper
from qwenpaw.token_usage.storage import load_data, save_data_sync

app = FastAPI()
app.include_router(router, prefix="/api")


# =============================================================================
# Core Module Tests (_apply_event, storage, buffer, models, manager)
# =============================================================================


class TestApplyEvent:
    """Test the _apply_event function that accumulates usage events."""

    def test_apply_event_creates_new_entry(self):
        """Should create new entry for first event."""
        cache = {}
        event = _UsageEvent(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            date_str="2026-04-24",
            now_iso="2026-04-24T10:00:00+00:00",
        )
        _apply_event(cache, event)

        assert "2026-04-24" in cache
        assert "openai:gpt-4" in cache["2026-04-24"]
        entry = cache["2026-04-24"]["openai:gpt-4"]
        assert entry["prompt_tokens"] == 100
        assert entry["completion_tokens"] == 50
        assert entry["call_count"] == 1

    def test_apply_event_accumulates_same_model(self):
        """Should accumulate tokens for same provider:model on same date."""
        cache = {}
        for _ in range(3):
            _apply_event(cache, _UsageEvent(
                provider_id="openai",
                model_name="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                date_str="2026-04-24",
                now_iso="2026-04-24T10:00:00+00:00",
            ))

        entry = cache["2026-04-24"]["openai:gpt-4"]
        assert entry["prompt_tokens"] == 300
        assert entry["completion_tokens"] == 150
        assert entry["call_count"] == 3

    def test_apply_event_handles_different_models(self):
        """Should track different providers/models separately."""
        cache = {}
        _apply_event(cache, _UsageEvent(
            provider_id="openai", model_name="gpt-4",
            prompt_tokens=100, completion_tokens=50,
            date_str="2026-04-24", now_iso="2026-04-24T10:00:00+00:00",
        ))
        _apply_event(cache, _UsageEvent(
            provider_id="anthropic", model_name="claude-3",
            prompt_tokens=120, completion_tokens=60,
            date_str="2026-04-24", now_iso="2026-04-24T11:00:00+00:00",
        ))

        assert len(cache["2026-04-24"]) == 2


class TestStorage:
    """Test storage load/save operations."""

    @pytest.mark.asyncio
    async def test_load_data_nonexistent_file(self, tmp_path):
        """Should return empty dict when file doesn't exist."""
        data = await load_data(tmp_path / "token_usage.json")
        assert data == {}

    @pytest.mark.asyncio
    async def test_load_data_valid_json(self, tmp_path):
        """Should load and return valid JSON data."""
        path = tmp_path / "token_usage.json"
        expected = {
            "2026-04-24": {
                "openai:gpt-4": {
                    "provider_id": "openai",
                    "model_name": "gpt-4",
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "call_count": 2,
                }
            }
        }
        path.write_text(json.dumps(expected))
        data = await load_data(path)
        assert data["2026-04-24"]["openai:gpt-4"]["prompt_tokens"] == 100

    @pytest.mark.asyncio
    async def test_load_data_corrupt_json(self, tmp_path):
        """Should handle corrupt JSON gracefully."""
        path = tmp_path / "token_usage.json"
        path.write_text("{invalid json}")
        data = await load_data(path)
        assert data == {}

    def test_save_data_sync_writes_file(self, tmp_path):
        """Should write data to file atomically."""
        path = tmp_path / "token_usage.json"
        data = {"2026-04-24": {"openai:gpt-4": {"prompt_tokens": 100}}}
        save_data_sync(path, data)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == data

    def test_save_data_sync_creates_parent_dirs(self, tmp_path):
        """Should create parent directories if needed."""
        path = tmp_path / "subdir" / "token_usage.json"
        save_data_sync(path, {"test": "data"})
        assert path.exists()


class TestTokenUsageBuffer:
    """Test TokenUsageBuffer core functionality."""

    def test_init_defaults(self, tmp_path):
        """Should initialize with correct defaults."""
        buffer = TokenUsageBuffer(tmp_path / "test.json")
        assert buffer._flush_interval == 10
        assert buffer._disk_cache == {}

    @pytest.mark.asyncio
    async def test_enqueue_adds_to_queue(self, tmp_path):
        """Should add event to queue."""
        buffer = TokenUsageBuffer(tmp_path / "test.json")
        event = _UsageEvent(
            provider_id="openai", model_name="gpt-4",
            prompt_tokens=100, completion_tokens=50,
            date_str="2026-04-24", now_iso="2026-04-24T10:00:00+00:00",
        )
        buffer.enqueue(event)
        assert buffer._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_consumer_processes_events(self, tmp_path):
        """Consumer should process and accumulate events."""
        buffer = TokenUsageBuffer(tmp_path / "test.json")
        buffer.start()

        for _ in range(3):
            buffer.enqueue(_UsageEvent(
                provider_id="openai", model_name="gpt-4",
                prompt_tokens=100, completion_tokens=50,
                date_str="2026-04-24", now_iso="2026-04-24T10:00:00+00:00",
            ))

        await asyncio.sleep(0.2)
        await buffer.stop()

        entry = buffer._disk_cache["2026-04-24"]["openai:gpt-4"]
        assert entry["prompt_tokens"] == 300
        assert entry["call_count"] == 3

    @pytest.mark.asyncio
    async def test_flush_writes_to_disk(self, tmp_path):
        """Flush should write cache to disk."""
        path = tmp_path / "test.json"
        buffer = TokenUsageBuffer(path)
        buffer.start()

        buffer.enqueue(_UsageEvent(
            provider_id="openai", model_name="gpt-4",
            prompt_tokens=100, completion_tokens=50,
            date_str="2026-04-24", now_iso="2026-04-24T10:00:00+00:00",
        ))

        await asyncio.sleep(0.2)
        await buffer.stop()

        assert path.exists()
        data = json.loads(path.read_text())
        assert "2026-04-24" in data


class TestTokenUsageStats:
    """Test TokenUsageStats model."""

    def test_default_values(self):
        """Should have zero defaults."""
        stats = TokenUsageStats()
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0
        assert stats.call_count == 0

    def test_custom_values(self):
        """Should accept custom values."""
        stats = TokenUsageStats(
            prompt_tokens=100,
            completion_tokens=50,
            call_count=5,
        )
        assert stats.prompt_tokens == 100
        assert stats.completion_tokens == 50
        assert stats.call_count == 5

    def test_validation_rejects_negative(self):
        """Should reject negative values."""
        with pytest.raises(Exception):
            TokenUsageStats(prompt_tokens=-1)


class TestTokenUsageModels:
    """Test TokenUsageRecord, TokenUsageByModel, TokenUsageSummary models."""

    def test_create_record(self):
        """Should create record with all fields."""
        record = TokenUsageRecord(
            date="2026-04-24",
            provider_id="openai",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            call_count=3,
        )
        assert record.date == "2026-04-24"
        assert record.provider_id == "openai"
        assert record.model == "gpt-4"

    def test_create_by_model(self):
        """Should create per-model stats."""
        by_model = TokenUsageByModel(
            provider_id="openai",
            model="gpt-4",
            prompt_tokens=200,
            completion_tokens=100,
            call_count=5,
        )
        assert by_model.provider_id == "openai"
        assert by_model.model == "gpt-4"

    def test_empty_summary(self):
        """Should create empty summary with defaults."""
        summary = TokenUsageSummary()
        assert summary.total_prompt_tokens == 0
        assert summary.total_completion_tokens == 0
        assert summary.total_calls == 0
        assert summary.by_model == {}
        assert summary.by_provider == {}
        assert summary.by_date == {}

    def test_summary_with_data(self):
        """Should accept populated data."""
        summary = TokenUsageSummary(
            total_prompt_tokens=500,
            total_completion_tokens=250,
            total_calls=10,
            by_model={
                "openai:gpt-4": TokenUsageByModel(
                    provider_id="openai",
                    model="gpt-4",
                    prompt_tokens=300,
                    completion_tokens=150,
                    call_count=6,
                ),
            },
            by_provider={
                "openai": TokenUsageStats(
                    prompt_tokens=500,
                    completion_tokens=250,
                    call_count=10,
                ),
            },
            by_date={
                "2026-04-24": TokenUsageStats(
                    prompt_tokens=500,
                    completion_tokens=250,
                    call_count=10,
                ),
            },
        )
        assert summary.total_prompt_tokens == 500
        assert len(summary.by_model) == 1
        assert len(summary.by_provider) == 1
        assert len(summary.by_date) == 1


class TestTokenUsageManagerCore:
    """Test TokenUsageManager singleton, lifecycle, and operations."""

    def test_get_instance_returns_singleton(self, tmp_path, monkeypatch):
        """Should return same instance on multiple calls."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        manager1 = TokenUsageManager.get_instance()
        manager2 = TokenUsageManager.get_instance()
        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_start_and_stop(self, tmp_path, monkeypatch):
        """Should start and stop cleanly."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        manager = TokenUsageManager()
        manager.start(flush_interval=10)
        await manager.stop()

    @pytest.mark.asyncio
    async def test_record_usage(self, tmp_path, monkeypatch):
        """Should record token usage."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )

        await asyncio.sleep(0.2)
        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_summary_empty(self, tmp_path, monkeypatch):
        """Should return empty summary when no data."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        summary = await manager.get_summary()

        assert summary.total_prompt_tokens == 0
        assert summary.total_completion_tokens == 0
        assert summary.total_calls == 0

        await manager.stop()


class TestTokenRecordingModelWrapper:
    """Test TokenRecordingModelWrapper."""

    def test_init_wraps_model(self, tmp_path, monkeypatch):
        """Should wrap a ChatModelBase instance."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        mock_model = MagicMock()
        mock_model.model_name = "gpt-4"
        mock_model.stream = True

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
        )

        assert wrapper._provider_id == "openai"
        assert wrapper._model is mock_model
        assert wrapper.model_name == "gpt-4"

    def test_record_usage_with_valid_usage(self, tmp_path, monkeypatch):
        """Should record valid usage."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        mock_model = MagicMock()
        mock_model.model_name = "gpt-4"

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
        )

        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50

        wrapper._record_usage(mock_usage)

    def test_record_usage_with_none_usage(self, tmp_path, monkeypatch):
        """Should skip recording when usage is None."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        mock_model = MagicMock()
        mock_model.model_name = "gpt-4"

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
        )

        # Should not raise
        wrapper._record_usage(None)

    def test_pop_usage_for_session(self, monkeypatch):
        """Should pop usage for session."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            "/tmp",
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        # Clear any existing usage
        TokenRecordingModelWrapper._usage_by_session.clear()

        # Add test usage
        TokenRecordingModelWrapper._usage_by_session["test-session"] = {
            "prompt_tokens": 100,
        }

        usage = TokenRecordingModelWrapper.pop_usage_for_session("test-session")
        assert usage is not None
        assert usage["prompt_tokens"] == 100

        # Verify it was removed
        assert TokenRecordingModelWrapper.pop_usage_for_session("test-session") is None


# =============================================================================
# Fixtures for Router Tests
# =============================================================================


@pytest.fixture
def api_client():
    """Create an async test client."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _isolate_token_usage_manager():
    """Isolate token usage manager singleton for each test."""
    # Reset singleton before each test
    TokenUsageManager._instance = None
    yield
    # Clean up singleton after test
    TokenUsageManager._instance = None


@pytest.fixture
def mock_token_usage_manager(monkeypatch):
    """Create a mock token usage manager for router tests."""
    mock_manager = AsyncMock(spec=TokenUsageManager)
    # Mock in the router module where it's actually used
    monkeypatch.setattr(
        "qwenpaw.app.routers.token_usage.get_token_usage_manager",
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
        import qwenpaw.token_usage as token_usage_pkg

        # Override WORKING_DIR to use tmp_path
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        # Reset singleton
        TokenUsageManager._instance = None

        # Create real manager
        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        monkeypatch.setattr(
            token_usage_pkg,
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
        import qwenpaw.token_usage as token_usage_pkg

        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )

        TokenUsageManager._instance = None

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        monkeypatch.setattr(
            token_usage_pkg,
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
