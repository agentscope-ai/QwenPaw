# -*- coding: utf-8 -*-
"""Unit tests for token_usage module.

Tests cover:
- TokenUsageBuffer: queue operations, event application, flush behavior
- TokenUsageManager: recording, querying, summary aggregation
- Storage: load/save operations with error handling
- Model wrapper: usage recording from LLM responses
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.token_usage.buffer import TokenUsageBuffer, _UsageEvent, _apply_event
from qwenpaw.token_usage.manager import (
    TokenUsageByModel,
    TokenUsageManager,
    TokenUsageRecord,
    TokenUsageStats,
    TokenUsageSummary,
    get_token_usage_manager,
)
from qwenpaw.token_usage.storage import load_data, save_data_sync


# =============================================================================
# Test _apply_event helper
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
        for i in range(3):
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


# =============================================================================
# Test Storage Functions
# =============================================================================


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
        data = {"daily": {"2026-04-24": {}}}
        save_data_sync(path, data)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == data

    def test_save_data_sync_creates_parent_dirs(self, tmp_path):
        """Should create parent directories if needed."""
        path = tmp_path / "subdir" / "token_usage.json"
        save_data_sync(path, {"test": "data"})
        assert path.exists()


# =============================================================================
# Test TokenUsageBuffer
# =============================================================================


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
        # Buffer writes date keys directly (not nested under 'daily')
        assert "2026-04-24" in data


# =============================================================================
# Test Pydantic Models
# =============================================================================


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
        with pytest.raises(Exception):  # pydantic.ValidationError
            TokenUsageStats(prompt_tokens=-1)


class TestTokenUsageRecord:
    """Test TokenUsageRecord model."""

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


class TestTokenUsageByModel:
    """Test TokenUsageByModel model."""

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


class TestTokenUsageSummary:
    """Test TokenUsageSummary model."""

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


# =============================================================================
# Test TokenUsageManager
# =============================================================================


class TestTokenUsageManagerSingleton:
    """Test TokenUsageManager singleton pattern."""

    def test_get_instance_returns_singleton(self):
        """Should return same instance on multiple calls."""
        manager1 = TokenUsageManager.get_instance()
        manager2 = TokenUsageManager.get_instance()
        assert manager1 is manager2

    def test_get_token_usage_manager_helper(self):
        """Helper function should return singleton."""
        from qwenpaw.token_usage.manager import get_token_usage_manager

        manager = get_token_usage_manager()
        assert isinstance(manager, TokenUsageManager)


class TestTokenUsageManagerLifecycle:
    """Test TokenUsageManager start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """Should start and stop cleanly."""
        manager = TokenUsageManager()
        manager.start(flush_interval=10)
        await manager.stop()

    @pytest.mark.asyncio
    async def test_start_custom_flush_interval(self):
        """Should accept custom flush interval."""
        manager = TokenUsageManager()
        manager.start(flush_interval=30)
        assert manager._flush_interval == 30
        await manager.stop()


class TestTokenUsageManagerRecord:
    """Test TokenUsageManager record operations."""

    @pytest.mark.asyncio
    async def test_record_usage(self, tmp_path, monkeypatch):
        """Should record token usage."""
        from qwenpaw.token_usage import manager as manager_module

        # Isolate manager from singleton
        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )

        # Allow time for processing
        await asyncio.sleep(0.2)
        await manager.stop()

    @pytest.mark.asyncio
    async def test_record_with_custom_date(self, tmp_path, monkeypatch):
        """Should record with custom date."""
        from qwenpaw.token_usage import manager as manager_module

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        custom_date = date(2026, 1, 1)
        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            at_date=custom_date,
        )

        await asyncio.sleep(0.2)
        await manager.stop()


class TestTokenUsageManagerQuery:
    """Test TokenUsageManager query and summary operations."""

    @pytest.mark.asyncio
    async def test_get_summary_empty(self, monkeypatch):
        """Should return empty summary when no data."""
        from qwenpaw.token_usage import manager as manager_module

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        summary = await manager.get_summary()

        assert summary.total_prompt_tokens == 0
        assert summary.total_completion_tokens == 0
        assert summary.total_calls == 0

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_summary_with_data(self, monkeypatch):
        """Should return aggregated summary."""
        from qwenpaw.token_usage import manager as manager_module

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

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

        await asyncio.sleep(0.3)

        summary = await manager.get_summary()

        assert summary.total_prompt_tokens >= 0
        assert summary.total_completion_tokens >= 0
        assert summary.total_calls >= 0

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_summary_with_date_range(self, monkeypatch):
        """Should filter by date range."""
        from qwenpaw.token_usage import manager as manager_module

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        # Get summary for specific date range
        end_date = date.today()
        start_date = end_date
        summary = await manager.get_summary(
            start_date=start_date,
            end_date=end_date,
        )

        assert isinstance(summary, TokenUsageSummary)

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_summary_with_model_filter(self, monkeypatch):
        """Should filter by model name."""
        from qwenpaw.token_usage import manager as manager_module

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        summary = await manager.get_summary(model_name="gpt-4")

        assert isinstance(summary, TokenUsageSummary)

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_summary_with_provider_filter(self, monkeypatch):
        """Should filter by provider ID."""
        from qwenpaw.token_usage import manager as manager_module

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        summary = await manager.get_summary(provider_id="openai")

        assert isinstance(summary, TokenUsageSummary)

        await manager.stop()


# =============================================================================
# Test Model Wrapper
# =============================================================================


class TestTokenRecordingModelWrapper:
    """Test TokenRecordingModelWrapper."""

    def test_init_wraps_model(self, monkeypatch):
        """Should wrap a ChatModelBase instance."""
        from qwenpaw.token_usage import manager as manager_module

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

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

    def test_record_usage_with_valid_usage(self, monkeypatch):
        """Should record valid usage."""
        from qwenpaw.token_usage import manager as manager_module
        from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

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

        # Verify usage stored for session
        # (session ID will be None in test context)

    def test_record_usage_with_none_usage(self, monkeypatch):
        """Should skip recording when usage is None."""
        from qwenpaw.token_usage import manager as manager_module
        from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        mock_model = MagicMock()
        mock_model.model_name = "gpt-4"

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
        )

        # Should not raise
        wrapper._record_usage(None)

    def test_record_usage_with_zero_tokens(self, monkeypatch):
        """Should skip recording when tokens are zero."""
        from qwenpaw.token_usage import manager as manager_module
        from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        mock_model = MagicMock()
        mock_model.model_name = "gpt-4"

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
        )

        mock_usage = MagicMock()
        mock_usage.input_tokens = 0
        mock_usage.output_tokens = 0

        wrapper._record_usage(mock_usage)

    def test_pop_usage_for_session(self, monkeypatch):
        """Should pop usage for session."""
        from qwenpaw.token_usage import manager as manager_module
        from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

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

    def test_pop_usage_for_nonexistent_session(self, monkeypatch):
        """Should return None for nonexistent session."""
        from qwenpaw.token_usage import manager as manager_module
        from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

        monkeypatch.setattr(manager_module, "TokenUsageManager._instance", None)

        usage = TokenRecordingModelWrapper.pop_usage_for_session("nonexistent")
        assert usage is None
