# -*- coding: utf-8 -*-
"""Unit tests for the token usage core module."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from unittest.mock import MagicMock

import pytest

from qwenpaw.token_usage.buffer import (
    TokenUsageBuffer,
    _UsageEvent,
    _apply_event,
)
from qwenpaw.app.agent_context import _current_agent_id
from qwenpaw.token_usage.manager import (
    TokenUsageByDateModel,
    TokenUsageByModel,
    TokenUsageManager,
    TokenUsageRecord,
    TokenUsageStats,
    TokenUsageSummary,
    _TURN_USAGE_META_KEY,
    _count_tool_calls_in_message,
    _usage_totals,
    collect_daily_tool_calls_sync,
    migrate_historical_agent_ids_sync,
)
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper
from qwenpaw.token_usage.storage import load_data, save_data_sync
from qwenpaw.token_usage.turn_usage import TURN_USAGE_META_KEY


def test_meta_key_sync():
    """manager and turn_usage must share the same metadata key string."""
    assert _TURN_USAGE_META_KEY == TURN_USAGE_META_KEY


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _isolate_token_usage_manager():
    """Isolate token usage manager singleton for each test."""
    # pylint: disable=protected-access
    TokenUsageManager._instance = None
    yield
    TokenUsageManager._instance = None


# =============================================================================
# Test _apply_event
# =============================================================================


class TestApplyEvent:
    """Test the _apply_event function that accumulates usage events."""

    # pylint: disable=protected-access

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
        assert "|openai:gpt-4" in cache["2026-04-24"]
        entry = cache["2026-04-24"]["|openai:gpt-4"]
        assert entry["agent_id"] == ""
        assert entry["prompt_tokens"] == 100
        assert entry["completion_tokens"] == 50
        assert entry["call_count"] == 1

    def test_apply_event_accumulates_same_model(self):
        """Should accumulate tokens for same provider:model on same date."""
        cache = {}
        for _ in range(3):
            _apply_event(
                cache,
                _UsageEvent(
                    provider_id="openai",
                    model_name="gpt-4",
                    prompt_tokens=100,
                    completion_tokens=50,
                    date_str="2026-04-24",
                    now_iso="2026-04-24T10:00:00+00:00",
                ),
            )

        entry = cache["2026-04-24"]["|openai:gpt-4"]
        assert entry["prompt_tokens"] == 300
        assert entry["call_count"] == 3

    def test_apply_event_separates_by_agent(self):
        """Same model under different agents should not merge."""
        cache = {}
        _apply_event(
            cache,
            _UsageEvent(
                provider_id="openai",
                model_name="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                date_str="2026-04-24",
                now_iso="2026-04-24T10:00:00+00:00",
                agent_id="agent-a",
            ),
        )
        _apply_event(
            cache,
            _UsageEvent(
                provider_id="openai",
                model_name="gpt-4",
                prompt_tokens=200,
                completion_tokens=80,
                date_str="2026-04-24",
                now_iso="2026-04-24T10:00:01+00:00",
                agent_id="agent-b",
            ),
        )

        assert "agent-a|openai:gpt-4" in cache["2026-04-24"]
        assert "agent-b|openai:gpt-4" in cache["2026-04-24"]
        assert (
            cache["2026-04-24"]["agent-a|openai:gpt-4"]["prompt_tokens"] == 100
        )
        assert (
            cache["2026-04-24"]["agent-b|openai:gpt-4"]["prompt_tokens"] == 200
        )


# =============================================================================
# Test Storage
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
                },
            },
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

    def test_save_data_sync_returns_false_on_oserror(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Transient atomic-write failure must report False."""
        path = tmp_path / "token_usage.json"

        def _boom(*_args, **_kwargs):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(
            "qwenpaw.token_usage.storage.os.replace",
            _boom,
        )
        assert save_data_sync(path, {"test": "data"}) is False
        assert not path.exists()


# =============================================================================
# Test TokenUsageBuffer
# =============================================================================


class TestTokenUsageBuffer:
    """Test TokenUsageBuffer core functionality."""

    # pylint: disable=protected-access

    def test_init_defaults(self, tmp_path):
        """Should initialize with correct defaults."""
        buffer = TokenUsageBuffer(tmp_path / "test.json")
        assert buffer._flush_interval == 10

    @pytest.mark.asyncio
    async def test_enqueue_adds_to_queue(self, tmp_path):
        """Should add event to queue."""
        buffer = TokenUsageBuffer(tmp_path / "test.json")
        event = _UsageEvent(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            date_str="2026-04-24",
            now_iso="2026-04-24T10:00:00+00:00",
        )
        buffer.enqueue(event)
        assert buffer._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_consumer_processes_events(self, tmp_path):
        """Consumer should process and accumulate events."""
        buffer = TokenUsageBuffer(tmp_path / "test.json")
        buffer.start()

        for _ in range(3):
            buffer.enqueue(
                _UsageEvent(
                    provider_id="openai",
                    model_name="gpt-4",
                    prompt_tokens=100,
                    completion_tokens=50,
                    date_str="2026-04-24",
                    now_iso="2026-04-24T10:00:00+00:00",
                ),
            )

        await asyncio.sleep(0.2)
        await buffer.stop()

        entry = buffer._disk_cache["2026-04-24"]["|openai:gpt-4"]
        assert entry["prompt_tokens"] == 300
        assert entry["call_count"] == 3

    @pytest.mark.asyncio
    async def test_stop_does_not_wipe_history_when_seed_interrupted(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A stop() that races cache seeding must not clobber the file."""
        path = tmp_path / "test.json"
        existing = {
            "2026-04-24": {
                "openai:gpt-4": {
                    "provider_id": "openai",
                    "model_name": "gpt-4",
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "call_count": 1,
                },
            },
        }
        path.write_text(json.dumps(existing), encoding="utf-8")

        seeding = asyncio.Event()

        async def _never_returns(_path):
            # Park the consumer inside the seed so stop() runs while
            # ``_disk_cache`` is still the initial empty dict.
            seeding.set()
            await asyncio.Event().wait()
            return {}

        monkeypatch.setattr(
            "qwenpaw.token_usage.buffer.load_data",
            _never_returns,
        )

        buffer = TokenUsageBuffer(path, flush_interval=3600)
        buffer.start()
        await asyncio.wait_for(seeding.wait(), timeout=1)
        await buffer.stop()

        assert json.loads(path.read_text(encoding="utf-8")) == existing

    @pytest.mark.asyncio
    async def test_stop_flushes_after_seed_completes(self, tmp_path):
        """Normal shutdown still merges new events into stored history."""
        path = tmp_path / "test.json"
        path.write_text(
            json.dumps(
                {
                    "2026-04-23": {
                        "openai:gpt-4": {
                            "provider_id": "openai",
                            "model_name": "gpt-4",
                            "prompt_tokens": 7,
                            "completion_tokens": 3,
                            "call_count": 1,
                        },
                    },
                },
            ),
            encoding="utf-8",
        )

        buffer = TokenUsageBuffer(path, flush_interval=3600)
        buffer.start()
        buffer.enqueue(
            _UsageEvent(
                provider_id="openai",
                model_name="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                date_str="2026-04-24",
                now_iso="2026-04-24T10:00:00+00:00",
            ),
        )
        await buffer.stop()

        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["2026-04-23"]["openai:gpt-4"]["prompt_tokens"] == 7
        assert written["2026-04-24"]["|openai:gpt-4"]["prompt_tokens"] == 100

    @pytest.mark.asyncio
    async def test_flush_retries_after_transient_write_failure(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Failed flush must keep dirty so the next flush retries (#6374)."""
        path = tmp_path / "token_usage.json"
        buffer = TokenUsageBuffer(path, flush_interval=3600)
        buffer._cache_loaded = True
        buffer._disk_cache = {
            "2026-04-24": {
                "openai:gpt-4": {
                    "provider_id": "openai",
                    "model_name": "gpt-4",
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "call_count": 1,
                },
            },
        }
        buffer._dirty = True

        real_replace = __import__("os").replace
        calls = {"n": 0}

        def _flaky_replace(src, dst, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("simulated replace failure")
            return real_replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(
            "qwenpaw.token_usage.storage.os.replace",
            _flaky_replace,
        )

        await buffer._flush_once()
        assert buffer._dirty is True
        assert not path.exists()
        assert calls["n"] == 1

        await buffer._flush_once()
        assert path.exists()
        assert buffer._dirty is False
        assert calls["n"] == 2
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["2026-04-24"]["openai:gpt-4"]["prompt_tokens"] == 100


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
    """Test TokenUsage models."""

    def test_create_record(self):
        """Should create record with all fields."""
        record = TokenUsageRecord(
            date="2026-04-24",
            provider_id="openai",
            model="gpt-4",
            agent_id="agent-a",
            prompt_tokens=100,
            completion_tokens=50,
            call_count=3,
        )
        assert record.date == "2026-04-24"
        assert record.provider_id == "openai"
        assert record.model == "gpt-4"
        assert record.agent_id == "agent-a"

    def test_empty_summary(self):
        """Should create empty summary with defaults."""
        summary = TokenUsageSummary()
        assert summary.total_prompt_tokens == 0
        assert summary.total_completion_tokens == 0
        assert summary.total_calls == 0
        assert summary.by_model == {}
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
        assert summary.by_model["openai:gpt-4"].model == "gpt-4"
        assert len(summary.by_date) == 1

    def test_token_usage_by_model(self):
        """Should create TokenUsageByModel with provider_id."""
        by_model = TokenUsageByModel(
            provider_id="openai",
            model="gpt-4",
            prompt_tokens=300,
            completion_tokens=150,
            call_count=6,
        )
        assert by_model.provider_id == "openai"
        assert by_model.model == "gpt-4"

    def test_token_usage_by_date_model(self):
        """Should create TokenUsageByDateModel."""
        by_date_model = TokenUsageByDateModel(
            provider_id="dashscope",
            model="qwen3-max",
            prompt_tokens=200,
            completion_tokens=100,
            call_count=4,
        )
        assert by_date_model.provider_id == "dashscope"
        assert by_date_model.model == "qwen3-max"


# =============================================================================
# Test TokenUsageManager
# =============================================================================


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
        assert summary.by_date == {}

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_details_empty(self, tmp_path, monkeypatch):
        """Should return empty list when no data."""
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

        details = await manager.get_details()

        assert details == []

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_details_with_data(self, tmp_path, monkeypatch):
        """Should return raw records for frontend aggregation."""
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

        # Record some usage
        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            agent_id="agent-a",
        )
        await manager.record(
            provider_id="dashscope",
            model_name="qwen3-max",
            prompt_tokens=200,
            completion_tokens=100,
            agent_id="agent-b",
        )

        await asyncio.sleep(0.2)

        details = await manager.get_details()

        # Should have 2 records
        assert len(details) == 2

        # Verify structure
        models = {r.model for r in details}
        assert "gpt-4" in models
        assert "qwen3-max" in models
        by_agent = {r.agent_id: r for r in details}
        assert by_agent["agent-a"].prompt_tokens == 100
        assert by_agent["agent-b"].prompt_tokens == 200

        await manager.stop()

    @pytest.mark.asyncio
    async def test_query_backward_compat_old_keys(self, tmp_path, monkeypatch):
        """Old disk keys without agent_id prefix should still query."""
        from datetime import date

        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )
        path = tmp_path / "test_token_usage.json"
        path.write_text(
            json.dumps(
                {
                    "2026-04-24": {
                        "openai:gpt-4": {
                            "provider_id": "openai",
                            "model_name": "gpt-4",
                            "prompt_tokens": 111,
                            "completion_tokens": 22,
                            "call_count": 1,
                        },
                    },
                },
            ),
            encoding="utf-8",
        )

        manager = TokenUsageManager()
        manager.start(flush_interval=10)
        details = await manager.get_details(
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        )
        assert len(details) == 1
        assert details[0].model == "gpt-4"
        assert details[0].agent_id == ""
        assert details[0].prompt_tokens == 111
        await manager.stop()


# =============================================================================
# Test TokenRecordingModelWrapper
# =============================================================================


class TestTokenRecordingModelWrapper:
    """Test TokenRecordingModelWrapper."""

    # pylint: disable=protected-access

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
        mock_model.model = "gpt-4"
        formatter = object()
        mock_model.formatter = formatter

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
        )

        assert wrapper._provider_id == "openai"
        assert wrapper._model is mock_model
        assert wrapper.model == "gpt-4"
        assert wrapper.formatter is formatter

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
        mock_model.model = "gpt-4"

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
        )

        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50

        token = _current_agent_id.set("interview-agent")
        try:
            wrapper._record_usage(mock_usage)
        finally:
            _current_agent_id.reset(token)

        # pylint: disable=protected-access
        pending = list(
            TokenUsageManager.get_instance()._buffer._queue._queue,
        )
        assert len(pending) == 1
        assert pending[0].agent_id == "interview-agent"

    def test_record_usage_includes_context_and_threshold(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Per-call usage carries context_size and compaction threshold."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_current_session_id",
            lambda: "sess-1",
        )

        mock_model = MagicMock()
        mock_model.model = "gpt-4"
        mock_model.context_size = 1_000_000

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
            compact_threshold=0.8,
        )

        mock_usage = MagicMock()
        mock_usage.input_tokens = 123_000
        mock_usage.output_tokens = 50
        agent_token = _current_agent_id.set("default")
        try:
            wrapper._record_usage(mock_usage)
        finally:
            _current_agent_id.reset(agent_token)

        stored = TokenRecordingModelWrapper.pop_usage_for_session("sess-1")
        assert stored is not None
        assert stored["context_size"] == 1_000_000
        assert stored["compact_threshold"] == 0.8

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

        usage = TokenRecordingModelWrapper.pop_usage_for_session(
            "test-session",
        )
        assert usage is not None
        assert usage["prompt_tokens"] == 100

        # Verify it was removed
        assert (
            TokenRecordingModelWrapper.pop_usage_for_session("test-session")
            is None
        )


# =============================================================================
# Test historical agent attribution migration
# =============================================================================


def _write_session_with_usage(
    path,
    *,
    created_at: str,
    provider_id: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated: bool = False,
):
    usage = {
        "provider_id": provider_id,
        "model_name": model_name,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if estimated:
        usage["estimated"] = True
    payload = {
        "agent": {
            "state": {
                "context": [
                    {
                        "role": "assistant",
                        "created_at": created_at,
                        "content": [{"type": "text", "text": "hi"}],
                        "metadata": {
                            TURN_USAGE_META_KEY: {"usage": usage},
                        },
                    },
                ],
            },
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestHistoricalAgentAttributionMigration:
    """Cover strict, idempotent historical agent_id backfill."""

    def test_splits_legacy_bucket_and_keeps_unknown_residual(
        self,
        tmp_path,
        monkeypatch,
    ):
        usage_path = tmp_path / "token_usage.json"
        legacy = {
            "2026-04-24": {
                "openai:gpt-4": {
                    "provider_id": "openai",
                    "model_name": "gpt-4",
                    "prompt_tokens": 300,
                    "completion_tokens": 90,
                    "call_count": 3,
                },
            },
        }
        usage_path.write_text(json.dumps(legacy), encoding="utf-8")

        agent_a = tmp_path / "agent-a"
        agent_b = tmp_path / "agent-b"
        _write_session_with_usage(
            agent_a / "sessions" / "console" / "s1.json",
            created_at="2026-04-24T10:00:00Z",
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=40,
        )
        _write_session_with_usage(
            agent_b / "sessions" / "console" / "s1.json",
            created_at="2026-04-24T11:00:00Z",
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=50,
            completion_tokens=10,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [("agent-a", agent_a), ("agent-b", agent_b)],
        )

        before = _usage_totals(legacy)
        assert migrate_historical_agent_ids_sync(usage_path) is True
        migrated = json.loads(usage_path.read_text(encoding="utf-8"))
        assert _usage_totals(migrated) == before

        day = migrated["2026-04-24"]
        assert "openai:gpt-4" not in day
        assert day["agent-a|openai:gpt-4"]["prompt_tokens"] == 100
        assert day["agent-a|openai:gpt-4"]["call_count"] == 1
        assert day["agent-b|openai:gpt-4"]["prompt_tokens"] == 50
        assert day["agent-b|openai:gpt-4"]["call_count"] == 1
        assert day["|openai:gpt-4"]["prompt_tokens"] == 150
        assert day["|openai:gpt-4"]["completion_tokens"] == 40
        assert day["|openai:gpt-4"]["call_count"] == 1
        assert day["|openai:gpt-4"]["agent_id"] == ""

    def test_second_run_is_noop(self, tmp_path, monkeypatch):
        usage_path = tmp_path / "token_usage.json"
        usage_path.write_text(
            json.dumps(
                {
                    "2026-04-24": {
                        "openai:gpt-4": {
                            "provider_id": "openai",
                            "model_name": "gpt-4",
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "call_count": 1,
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        agent_a = tmp_path / "agent-a"
        _write_session_with_usage(
            agent_a / "sessions" / "console" / "s1.json",
            created_at="2026-04-24T10:00:00Z",
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=20,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [("agent-a", agent_a)],
        )

        assert migrate_historical_agent_ids_sync(usage_path) is True
        first = usage_path.read_text(encoding="utf-8")
        assert migrate_historical_agent_ids_sync(usage_path) is False
        assert usage_path.read_text(encoding="utf-8") == first

    def test_skips_estimated_and_identity_less_usage(
        self,
        tmp_path,
        monkeypatch,
    ):
        usage_path = tmp_path / "token_usage.json"
        usage_path.write_text(
            json.dumps(
                {
                    "2026-04-24": {
                        "openai:gpt-4": {
                            "provider_id": "openai",
                            "model_name": "gpt-4",
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "call_count": 1,
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        agent_a = tmp_path / "agent-a"
        _write_session_with_usage(
            agent_a / "sessions" / "console" / "est.json",
            created_at="2026-04-24T10:00:00Z",
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=20,
            estimated=True,
        )
        # Missing provider/model identity
        bad = {
            "agent": {
                "state": {
                    "context": [
                        {
                            "role": "assistant",
                            "created_at": "2026-04-24T10:00:00Z",
                            "metadata": {
                                TURN_USAGE_META_KEY: {
                                    "usage": {
                                        "prompt_tokens": 100,
                                        "completion_tokens": 20,
                                    },
                                },
                            },
                        },
                    ],
                },
            },
        }
        bad_path = agent_a / "sessions" / "console" / "bad.json"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [("agent-a", agent_a)],
        )

        assert migrate_historical_agent_ids_sync(usage_path) is True
        migrated = json.loads(usage_path.read_text(encoding="utf-8"))
        day = migrated["2026-04-24"]
        assert "agent-a|openai:gpt-4" not in day
        assert day["|openai:gpt-4"]["prompt_tokens"] == 100
        assert day["|openai:gpt-4"]["call_count"] == 1

    def test_rejects_unsafe_over_allocation(self, tmp_path, monkeypatch):
        usage_path = tmp_path / "token_usage.json"
        usage_path.write_text(
            json.dumps(
                {
                    "2026-04-24": {
                        "openai:gpt-4": {
                            "provider_id": "openai",
                            "model_name": "gpt-4",
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "call_count": 1,
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        agent_a = tmp_path / "agent-a"
        _write_session_with_usage(
            agent_a / "sessions" / "console" / "s1.json",
            created_at="2026-04-24T10:00:00Z",
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=999,
            completion_tokens=20,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [("agent-a", agent_a)],
        )

        assert migrate_historical_agent_ids_sync(usage_path) is True
        migrated = json.loads(usage_path.read_text(encoding="utf-8"))
        day = migrated["2026-04-24"]
        assert "agent-a|openai:gpt-4" not in day
        assert day["|openai:gpt-4"]["prompt_tokens"] == 100
        assert day["|openai:gpt-4"]["call_count"] == 1

    def test_preserves_existing_new_format_rows(self, tmp_path, monkeypatch):
        usage_path = tmp_path / "token_usage.json"
        usage_path.write_text(
            json.dumps(
                {
                    "2026-04-24": {
                        "openai:gpt-4": {
                            "provider_id": "openai",
                            "model_name": "gpt-4",
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "call_count": 1,
                        },
                        "agent-x|openai:gpt-4": {
                            "agent_id": "agent-x",
                            "provider_id": "openai",
                            "model_name": "gpt-4",
                            "prompt_tokens": 55,
                            "completion_tokens": 5,
                            "call_count": 1,
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [],
        )
        before = _usage_totals(
            json.loads(usage_path.read_text(encoding="utf-8")),
        )
        assert migrate_historical_agent_ids_sync(usage_path) is True
        migrated = json.loads(usage_path.read_text(encoding="utf-8"))
        assert _usage_totals(migrated) == before
        day = migrated["2026-04-24"]
        assert day["agent-x|openai:gpt-4"]["prompt_tokens"] == 55
        assert day["|openai:gpt-4"]["prompt_tokens"] == 100

    def test_merges_legacy_into_existing_residual_row(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Existing residual '|model' rows must merge, not overwrite."""
        usage_path = tmp_path / "token_usage.json"
        usage_path.write_text(
            json.dumps(
                {
                    "2026-04-24": {
                        "openai:gpt-4": {
                            "provider_id": "openai",
                            "model_name": "gpt-4",
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "call_count": 1,
                        },
                        "|openai:gpt-4": {
                            "agent_id": "",
                            "provider_id": "openai",
                            "model_name": "gpt-4",
                            "prompt_tokens": 55,
                            "completion_tokens": 5,
                            "call_count": 1,
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [],
        )
        before = _usage_totals(
            json.loads(usage_path.read_text(encoding="utf-8")),
        )
        assert migrate_historical_agent_ids_sync(usage_path) is True
        migrated = json.loads(usage_path.read_text(encoding="utf-8"))
        assert _usage_totals(migrated) == before
        day = migrated["2026-04-24"]
        assert "openai:gpt-4" not in day
        assert day["|openai:gpt-4"]["prompt_tokens"] == 155
        assert day["|openai:gpt-4"]["completion_tokens"] == 25
        assert day["|openai:gpt-4"]["call_count"] == 2

    @pytest.mark.asyncio
    async def test_manager_migration_failure_is_non_fatal(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "token_usage.json",
        )

        async def _boom():
            raise RuntimeError("simulated migration failure")

        manager = TokenUsageManager()
        monkeypatch.setattr(manager, "migrate_historical_agent_ids", _boom)

        # Mirror the startup guard in app lifespan.
        try:
            await manager.migrate_historical_agent_ids()
        except Exception:
            pass
        manager.start(flush_interval=10)
        await manager.stop()

    def test_attributes_despite_old_session_mtime(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Restored/copied sessions with old mtime must still attribute."""
        import os
        from datetime import datetime

        usage_path = tmp_path / "token_usage.json"
        legacy = {
            "2026-04-24": {
                "openai:gpt-4": {
                    "provider_id": "openai",
                    "model_name": "gpt-4",
                    "prompt_tokens": 100,
                    "completion_tokens": 40,
                    "call_count": 1,
                },
            },
        }
        usage_path.write_text(json.dumps(legacy), encoding="utf-8")

        agent_a = tmp_path / "agent-a"
        session = agent_a / "sessions" / "console" / "s1.json"
        _write_session_with_usage(
            session,
            created_at="2026-04-24T10:00:00Z",
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=40,
        )
        old = datetime(2020, 1, 1).timestamp()
        os.utime(session, (old, old))
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [("agent-a", agent_a)],
        )

        assert migrate_historical_agent_ids_sync(usage_path) is True
        migrated = json.loads(usage_path.read_text(encoding="utf-8"))
        day = migrated["2026-04-24"]
        assert day["agent-a|openai:gpt-4"]["prompt_tokens"] == 100
        assert "|openai:gpt-4" not in day

    @pytest.mark.asyncio
    async def test_manager_reload_after_successful_migration(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "token_usage.json",
        )
        usage_path = tmp_path / "token_usage.json"
        legacy = {
            "2026-04-24": {
                "openai:gpt-4": {
                    "provider_id": "openai",
                    "model_name": "gpt-4",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "call_count": 1,
                },
            },
        }
        usage_path.write_text(json.dumps(legacy), encoding="utf-8")
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [],
        )

        manager = TokenUsageManager()
        # Seed buffer with legacy data before migration.
        # pylint: disable=protected-access
        await manager._buffer._seed_cache()
        assert "openai:gpt-4" in manager._buffer._disk_cache["2026-04-24"]

        wrote = await manager.migrate_historical_agent_ids()
        assert wrote is True
        day = manager._buffer._disk_cache["2026-04-24"]
        assert "openai:gpt-4" not in day
        assert day["|openai:gpt-4"]["prompt_tokens"] == 10

    @pytest.mark.asyncio
    async def test_prestart_migration_preserves_dirty_buffer_events(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Flush-before-migrate must not drop unflushed in-memory events."""
        from datetime import date

        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "token_usage.json",
        )
        usage_path = tmp_path / "token_usage.json"
        legacy = {
            "2026-04-24": {
                "openai:gpt-4": {
                    "provider_id": "openai",
                    "model_name": "gpt-4",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "call_count": 1,
                },
            },
        }
        usage_path.write_text(json.dumps(legacy), encoding="utf-8")
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [],
        )

        manager = TokenUsageManager()
        # pylint: disable=protected-access
        await manager._buffer._seed_cache()
        _apply_event(
            manager._buffer._disk_cache,
            _UsageEvent(
                provider_id="openai",
                model_name="gpt-4",
                prompt_tokens=7,
                completion_tokens=3,
                date_str=date(2026, 4, 24).isoformat(),
                now_iso="2026-04-24T12:00:00+00:00",
                agent_id="live-agent",
            ),
        )
        manager._buffer._dirty = True

        wrote = await manager.migrate_historical_agent_ids()
        assert wrote is True
        day = manager._buffer._disk_cache["2026-04-24"]
        # Pre-start dirty event must survive flush-then-migrate-then-reload.
        assert day["live-agent|openai:gpt-4"]["prompt_tokens"] == 7
        assert day["|openai:gpt-4"]["prompt_tokens"] == 10

    @pytest.mark.asyncio
    async def test_migration_rejected_after_start(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "token_usage.json",
        )
        manager = TokenUsageManager()
        manager.start(flush_interval=10)
        try:
            with pytest.raises(RuntimeError, match="before start"):
                await manager.migrate_historical_agent_ids()
        finally:
            await manager.stop()


# =============================================================================
# Daily tool-call aggregation (LLM & Tool Call Trend)
# =============================================================================


def _write_session_with_tool_calls(
    path,
    messages: list[dict],
):
    payload = {
        "agent": {
            "state": {
                "context": messages,
            },
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestCountToolCallsInMessage:
    """Cover tool_use / tool_call block counting."""

    def test_counts_tool_use_and_tool_call(self):
        msg = {
            "content": [
                {"type": "text", "text": "hi"},
                {"type": "tool_use", "id": "1", "name": "search"},
                {"type": "tool_call", "id": "2", "name": "shell"},
            ],
        }
        assert _count_tool_calls_in_message(msg) == 2

    def test_returns_zero_for_non_list_content(self):
        assert _count_tool_calls_in_message({"content": "plain"}) == 0
        assert _count_tool_calls_in_message({}) == 0

    def test_counts_top_level_openai_tool_calls(self):
        msg = {
            "content": "calling tools",
            "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "a"}},
                {"id": "2", "type": "function", "function": {"name": "b"}},
            ],
        }
        assert _count_tool_calls_in_message(msg) == 2

    def test_falls_back_when_content_list_has_no_tool_blocks(self):
        msg = {
            "content": [],
            "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "a"}},
            ],
        }
        assert _count_tool_calls_in_message(msg) == 1
        msg_missing = {
            "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "a"}},
                {"id": "2", "type": "function", "function": {"name": "b"}},
            ],
        }
        assert _count_tool_calls_in_message(msg_missing) == 2

    def test_prefers_content_blocks_over_top_level(self):
        msg = {
            "content": [{"type": "tool_use", "id": "1", "name": "search"}],
            "tool_calls": [
                {"id": "2", "type": "function", "function": {"name": "shell"}},
            ],
        }
        assert _count_tool_calls_in_message(msg) == 1


class TestCollectDailyToolCalls:
    """Cover cross-agent daily tool-call aggregation."""

    def test_aggregates_across_agents_and_filters_by_date(
        self,
        tmp_path,
        monkeypatch,
    ):
        from datetime import date

        agent_a = tmp_path / "agent-a"
        agent_b = tmp_path / "agent-b"
        _write_session_with_tool_calls(
            agent_a / "sessions" / "console" / "s1.json",
            [
                {
                    "role": "assistant",
                    "created_at": "2026-04-24T10:00:00Z",
                    "content": [
                        {"type": "tool_use", "id": "a1", "name": "search"},
                        {"type": "tool_call", "id": "a2", "name": "shell"},
                    ],
                },
                {
                    "role": "assistant",
                    "created_at": "2026-04-25T10:00:00Z",
                    "content": [
                        {"type": "tool_use", "id": "a3", "name": "read"},
                    ],
                },
                {
                    "role": "assistant",
                    "created_at": "2026-04-26T10:00:00Z",
                    "content": [
                        {"type": "tool_use", "id": "out", "name": "skip"},
                    ],
                },
            ],
        )
        _write_session_with_tool_calls(
            agent_b / "sessions" / "console" / "s1.json",
            [
                {
                    "role": "assistant",
                    "timestamp": "2026-04-24T12:00:00Z",
                    "content": [
                        {"type": "tool_call", "id": "b1", "name": "grep"},
                    ],
                },
                {
                    "role": "user",
                    "created_at": "2026-04-24T12:01:00Z",
                    "content": [{"type": "text", "text": "hi"}],
                },
            ],
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [("agent-a", agent_a), ("agent-b", agent_b)],
        )

        result = collect_daily_tool_calls_sync(
            date(2026, 4, 24),
            date(2026, 4, 25),
        )
        assert result == {
            "2026-04-24": 3,
            "2026-04-25": 1,
        }

    def test_counts_tool_calls_despite_old_session_mtime(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Restored sessions with old mtime must still count in-range calls."""
        import os
        from datetime import date, datetime

        agent_a = tmp_path / "agent-a"
        session = agent_a / "sessions" / "console" / "s1.json"
        _write_session_with_tool_calls(
            session,
            [
                {
                    "role": "assistant",
                    "created_at": "2026-04-24T10:00:00Z",
                    "content": [
                        {"type": "tool_use", "id": "a1", "name": "search"},
                    ],
                },
            ],
        )
        old = datetime(2020, 1, 1).timestamp()
        os.utime(session, (old, old))
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [("agent-a", agent_a)],
        )

        result = collect_daily_tool_calls_sync(
            date(2026, 4, 24),
            date(2026, 4, 25),
        )
        assert result == {"2026-04-24": 1}

    def test_skips_corrupt_session_files(self, tmp_path, monkeypatch):
        from datetime import date

        agent_a = tmp_path / "agent-a"
        bad = agent_a / "sessions" / "console" / "bad.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{not-json", encoding="utf-8")
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager._iter_agent_profiles",
            lambda: [("agent-a", agent_a)],
        )

        assert not collect_daily_tool_calls_sync(
            date(2026, 4, 24),
            date(2026, 4, 25),
        )

    @pytest.mark.asyncio
    async def test_manager_get_daily_tool_calls_delegates(
        self,
        monkeypatch,
    ):
        from datetime import date

        manager = TokenUsageManager()
        called = {}

        def _fake(start_date, end_date):
            called["start"] = start_date
            called["end"] = end_date
            called["n"] = called.get("n", 0) + 1
            return {"2026-04-24": 2}

        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.collect_daily_tool_calls_sync",
            _fake,
        )
        result = await manager.get_daily_tool_calls(
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 25),
        )
        assert result == {"2026-04-24": 2}
        assert called["start"] == date(2026, 4, 24)
        assert called["end"] == date(2026, 4, 25)

        # Same range within TTL should hit cache.
        cached = await manager.get_daily_tool_calls(
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 25),
        )
        assert cached == {"2026-04-24": 2}
        assert called["n"] == 1

    @pytest.mark.asyncio
    async def test_manager_get_daily_tool_calls_ttl_expires(
        self,
        monkeypatch,
    ):
        from datetime import date

        manager = TokenUsageManager()
        # pylint: disable=protected-access
        manager._TOOL_CALLS_TTL = 0  # expire immediately
        calls = {"n": 0}

        def _fake(_start_date, _end_date):
            calls["n"] += 1
            return {"2026-04-24": calls["n"]}

        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.collect_daily_tool_calls_sync",
            _fake,
        )
        first = await manager.get_daily_tool_calls(
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 25),
        )
        second = await manager.get_daily_tool_calls(
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 25),
        )
        assert first == {"2026-04-24": 1}
        assert second == {"2026-04-24": 2}
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_manager_get_daily_tool_calls_single_flight(
        self,
        monkeypatch,
    ):
        from datetime import date

        manager = TokenUsageManager()
        calls = {"n": 0}

        def _fake(_start_date, _end_date):
            calls["n"] += 1
            return {"2026-04-24": calls["n"]}

        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.collect_daily_tool_calls_sync",
            _fake,
        )
        results = await asyncio.gather(
            manager.get_daily_tool_calls(
                start_date=date(2026, 4, 24),
                end_date=date(2026, 4, 25),
            ),
            manager.get_daily_tool_calls(
                start_date=date(2026, 4, 24),
                end_date=date(2026, 4, 25),
            ),
        )
        assert results[0] == results[1] == {"2026-04-24": 1}
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_manager_get_daily_tool_calls_cancel_safe(
        self,
        monkeypatch,
    ):
        from datetime import date

        manager = TokenUsageManager()
        started = threading.Event()
        release = threading.Event()
        calls = {"n": 0}

        def _fake(_start_date, _end_date):
            calls["n"] += 1
            started.set()
            # Block the worker thread until the first waiter is cancelled.
            assert release.wait(timeout=5)
            return {"2026-04-24": 1}

        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.collect_daily_tool_calls_sync",
            _fake,
        )

        first = asyncio.create_task(
            manager.get_daily_tool_calls(
                start_date=date(2026, 4, 24),
                end_date=date(2026, 4, 25),
            ),
        )
        await asyncio.to_thread(started.wait, 5)
        second = asyncio.create_task(
            manager.get_daily_tool_calls(
                start_date=date(2026, 4, 24),
                end_date=date(2026, 4, 25),
            ),
        )
        # Let the second waiter attach to the shared in-flight task.
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert await second == {"2026-04-24": 1}
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_manager_get_daily_tool_calls_prunes_expired_cache(
        self,
        monkeypatch,
    ):
        from datetime import date

        manager = TokenUsageManager()
        # pylint: disable=protected-access
        old_key = (date(2026, 4, 1), date(2026, 4, 2))
        manager._tool_calls_cache[old_key] = (
            time.monotonic() - manager._TOOL_CALLS_TTL - 1,
            {"2026-04-01": 9},
        )

        def _fake(_start_date, _end_date):
            return {"2026-04-24": 1}

        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.collect_daily_tool_calls_sync",
            _fake,
        )
        result = await manager.get_daily_tool_calls(
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 25),
        )
        assert result == {"2026-04-24": 1}
        assert old_key not in manager._tool_calls_cache
