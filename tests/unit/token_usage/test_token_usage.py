# -*- coding: utf-8 -*-
"""Unit tests for the token usage core module."""
from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.agent_context import peek_current_agent_id
from qwenpaw.token_usage.buffer import (
    TokenUsageBuffer,
    _UsageEvent,
    _apply_event,
)
from qwenpaw.token_usage.manager import (
    TokenUsageByDateModel,
    TokenUsageByModel,
    TokenUsageManager,
    TokenUsageRecord,
    TokenUsageStats,
    TokenUsageSummary,
    _usage_agent_id,
)
from qwenpaw.token_usage.model_wrapper import (
    TokenRecordingModelWrapper,
    _cache_usage_metrics,
)
from qwenpaw.token_usage.storage import load_data, save_data_sync
from qwenpaw.token_usage.turn_usage import add_session_cache_usage

_EMPTY_AGENT_KEY = "\x1f".join(("", "openai", "gpt-4"))
_NAMED_AGENT_KEY = "\x1f".join(("bot-a", "openai", "gpt-4"))


def _ev(**kwargs) -> _UsageEvent:
    base = {
        "provider_id": "openai",
        "model_name": "gpt-4",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "date_str": "2026-04-24",
        "now_iso": "2026-04-24T10:00:00+00:00",
    }
    base.update(kwargs)
    return _UsageEvent(**base)


def _row(**kwargs) -> dict:
    base = {
        "provider_id": "openai",
        "model_name": "gpt-4",
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "call_count": 1,
    }
    base.update(kwargs)
    return base


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
        _apply_event(cache, _ev())
        entry = cache["2026-04-24"][_EMPTY_AGENT_KEY]
        assert entry["prompt_tokens"] == 100
        assert entry["completion_tokens"] == 50
        assert entry["call_count"] == 1

    def test_apply_event_accumulates_same_model(self):
        """Should accumulate tokens for same provider:model on same date."""
        cache = {}
        for _ in range(3):
            _apply_event(cache, _ev())
        entry = cache["2026-04-24"][_EMPTY_AGENT_KEY]
        assert entry["prompt_tokens"] == 300
        assert entry["call_count"] == 3

    def test_apply_event_accumulates_cache_usage(self):
        """Cache token counters should use the same aggregation bucket."""
        cache = {}
        _apply_event(
            cache,
            _ev(
                cache_read_tokens=80,
                cache_write_tokens=10,
                cache_eligible_input_tokens=100,
                cache_observed=True,
            ),
        )
        _apply_event(cache, _ev())

        entry = cache["2026-04-24"][_EMPTY_AGENT_KEY]
        assert entry["cache_read_tokens"] == 80
        assert entry["cache_write_tokens"] == 10
        assert entry["cache_eligible_input_tokens"] == 100
        assert entry["cache_observed_calls"] == 1

    def test_apply_event_does_not_merge_into_legacy_row(self):
        """Named/empty agent ids stay off the legacy provider:model row."""
        cache = {
            "2026-04-24": {
                "openai:gpt-4": _row(prompt_tokens=10, completion_tokens=5),
                _EMPTY_AGENT_KEY: _row(
                    prompt_tokens=0,
                    completion_tokens=0,
                    agent_id="",
                ),
            },
        }
        _apply_event(cache, _ev(agent_id="bot-a"))
        _apply_event(
            cache,
            _ev(
                agent_id="",
                prompt_tokens=1,
                completion_tokens=1,
            ),
        )
        day = cache["2026-04-24"]
        assert day["openai:gpt-4"]["call_count"] == 1
        assert day[_NAMED_AGENT_KEY]["agent_id"] == "bot-a"
        assert day[_EMPTY_AGENT_KEY]["agent_id"] == ""
        assert day[_EMPTY_AGENT_KEY]["call_count"] == 2


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

        entry = buffer._disk_cache["2026-04-24"][_EMPTY_AGENT_KEY]
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
        assert written["2026-04-24"][_EMPTY_AGENT_KEY]["prompt_tokens"] == 100

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
            prompt_tokens=100,
            completion_tokens=50,
            call_count=3,
        )
        assert record.date == "2026-04-24"
        assert record.provider_id == "openai"
        assert record.model == "gpt-4"
        assert record.agent_id is None

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
    async def test_get_summary_uses_token_weighted_cache_rate(self):
        """Summary should divide total cache reads by total eligible input."""
        manager = TokenUsageManager()
        # pylint: disable=protected-access
        manager._buffer.get_merged_data = AsyncMock(
            return_value={
                "2026-04-24": {
                    "deepseek:chat": _row(
                        provider_id="deepseek",
                        model_name="chat",
                        prompt_tokens=1000,
                        cache_read_tokens=540,
                        cache_write_tokens=0,
                        cache_eligible_input_tokens=1000,
                        cache_observed_calls=2,
                        call_count=2,
                    ),
                },
            },
        )

        summary = await manager.get_summary(
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 24),
        )

        assert summary.total_cache_read_tokens == 540
        assert summary.total_cache_eligible_input_tokens == 1000
        assert summary.cache_observed_calls == 2
        assert summary.cache_hit_rate == 54

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
        )
        await manager.record(
            provider_id="dashscope",
            model_name="qwen3-max",
            prompt_tokens=200,
            completion_tokens=100,
        )

        await asyncio.sleep(0.2)

        details = await manager.get_details()

        # Should have 2 records
        assert len(details) == 2

        # Verify structure
        models = {r.model for r in details}
        assert "gpt-4" in models
        assert "qwen3-max" in models
        assert all(r.agent_id == "" for r in details)

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_details_legacy_and_agent_rows(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Legacy rows stay unattributed; agent keys keep model and id."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "t.json",
        )
        (tmp_path / "t.json").write_text(
            json.dumps(
                {
                    "2026-04-24": {
                        "k": _row(
                            provider_id="o",
                            model_name="m",
                        ),
                        _EMPTY_AGENT_KEY: _row(model_name=""),
                        _NAMED_AGENT_KEY: _row(agent_id="bot-a"),
                    },
                },
            ),
            encoding="utf-8",
        )
        manager = TokenUsageManager()
        manager.start(flush_interval=10)
        rows = await manager.get_details(
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 24),
        )
        assert rows[0].agent_id is None
        missing = next(r for r in rows if r.provider_id == "openai")
        assert missing.model == "gpt-4"
        assert "\x1f" not in missing.model
        named = next(r for r in rows if r.agent_id == "bot-a")
        assert named.model == "gpt-4"
        await manager.stop()

    @pytest.mark.asyncio
    async def test_query_legacy_key_fallback_without_model_name(self):
        """Legacy colon keys should recover the model name from the key."""
        manager = TokenUsageManager()
        merged = {
            "2026-04-24": {
                "prov2:model-from-key": {
                    "provider_id": "prov2",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "call_count": 1,
                },
                "ollama:namespace:model:tag": {
                    "provider_id": "ollama",
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "call_count": 2,
                },
            },
        }

        # pylint: disable=protected-access
        rows = await manager._query(
            merged,
            date(2026, 4, 24),
            date(2026, 4, 24),
            None,
            None,
        )

        assert [row.model_dump() for row in rows] == [
            {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cache_eligible_input_tokens": 0,
                "cache_observed_calls": 0,
                "call_count": 1,
                "date": "2026-04-24",
                "provider_id": "prov2",
                "model": "model-from-key",
                "agent_id": None,
            },
            {
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cache_eligible_input_tokens": 0,
                "cache_observed_calls": 0,
                "call_count": 2,
                "date": "2026-04-24",
                "provider_id": "ollama",
                "model": "namespace:model:tag",
                "agent_id": None,
            },
        ]

        # pylint: disable=protected-access
        filtered = await manager._query(
            merged,
            date(2026, 4, 24),
            date(2026, 4, 24),
            "model-from-key",
            None,
        )
        assert [row.model_dump() for row in filtered] == [
            {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cache_eligible_input_tokens": 0,
                "cache_observed_calls": 0,
                "call_count": 1,
                "date": "2026-04-24",
                "provider_id": "prov2",
                "model": "model-from-key",
                "agent_id": None,
            },
        ]


# =============================================================================
# Test TokenRecordingModelWrapper
# =============================================================================


class TestTokenRecordingModelWrapper:
    """Test TokenRecordingModelWrapper."""

    # pylint: disable=protected-access

    def test_cache_usage_metrics_for_deepseek(self):
        """DeepSeek reports cache hits inside total prompt tokens."""
        deepseek_model = type(
            "DeepSeekModel",
            (),
            {"__module__": "agentscope.model._deepseek._model"},
        )()

        observed, eligible = _cache_usage_metrics(
            deepseek_model,
            100,
            80,
            0,
        )

        assert observed is True
        assert eligible == 100

    def test_cache_usage_metrics_for_anthropic(self):
        """Anthropic reports uncached, read, and write tokens separately."""
        anthropic_model = type(
            "AnthropicModel",
            (),
            {"__module__": "agentscope.model._anthropic._model"},
        )()

        observed, eligible = _cache_usage_metrics(
            anthropic_model,
            10,
            80,
            10,
        )

        assert observed is True
        assert eligible == 100

    def test_cache_usage_metrics_for_unknown_model(self):
        """Unknown adapters should not expose a misleading percentage."""
        observed, eligible = _cache_usage_metrics(object(), 100, 80, 0)

        assert observed is False
        assert eligible == 0

    def test_cache_usage_metrics_rejects_invalid_total_semantics(self):
        """A cache count above total input should not produce a percentage."""
        deepseek_model = type(
            "DeepSeekModel",
            (),
            {"__module__": "agentscope.model._deepseek._model"},
        )()

        observed, eligible = _cache_usage_metrics(
            deepseek_model,
            100,
            101,
            0,
        )

        assert observed is False
        assert eligible == 0

    def _stream_harness(self, _tmp_path, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            "qwenpaw.token_usage.model_wrapper.get_token_usage_manager",
            lambda: MagicMock(enqueue=captured.append),
        )
        model = MagicMock()
        model.model = "gpt-4"
        return TokenRecordingModelWrapper("openai", model), captured

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
        mock_usage.cache_input_tokens = 0
        mock_usage.cache_creation_input_tokens = 0

        wrapper._record_usage(mock_usage)

    def test_record_usage_uses_contextvar_agent_id(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Should stamp ContextVar agent id onto the event."""
        fake_var = MagicMock()
        fake_var.get.return_value = "bot-a"
        monkeypatch.setattr(
            "qwenpaw.app.agent_context._current_agent_id",
            fake_var,
        )
        wrapper, captured = self._stream_harness(tmp_path, monkeypatch)
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_input_tokens = 0
        usage.cache_creation_input_tokens = 0
        wrapper._record_usage(usage)
        assert captured[0].agent_id == "bot-a"
        fake_var.get.return_value = None
        wrapper._record_usage(usage)
        assert captured[1].agent_id == ""
        monkeypatch.setattr(
            "qwenpaw.app.agent_context._current_agent_id",
            ContextVar("current_agent_id", default=None),
        )
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_active_agent_id",
            lambda: "default",
        )
        assert peek_current_agent_id() == ""
        assert _usage_agent_id() == ""

    def test_record_usage_carries_cache_metrics(self, tmp_path, monkeypatch):
        """Provider cache counters should reach both event and turn usage."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.model_wrapper._cache_usage_metrics",
            lambda *_args: (True, 100),
        )
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_current_session_id",
            lambda: "sess-cache",
        )
        wrapper, captured = self._stream_harness(tmp_path, monkeypatch)
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 10
        usage.cache_input_tokens = 80
        usage.cache_creation_input_tokens = 5

        wrapper._record_usage(usage)

        assert captured[0].cache_read_tokens == 80
        assert captured[0].cache_write_tokens == 5
        assert captured[0].cache_eligible_input_tokens == 100
        assert captured[0].cache_observed is True
        stored = TokenRecordingModelWrapper.pop_usage_for_session(
            "sess-cache",
        )
        assert stored is not None
        assert stored["cache_hit_rate"] == 80

    def test_record_usage_discards_unverified_cache_metrics(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Unknown provider semantics should not pollute cache totals."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.model_wrapper._cache_usage_metrics",
            lambda *_args: (False, 0),
        )
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_current_session_id",
            lambda: "sess-unknown-cache",
        )
        wrapper, captured = self._stream_harness(tmp_path, monkeypatch)
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 10
        usage.cache_input_tokens = 80
        usage.cache_creation_input_tokens = 5

        wrapper._record_usage(usage)

        assert captured[0].cache_read_tokens == 0
        assert captured[0].cache_write_tokens == 0
        assert captured[0].cache_observed is False
        stored = TokenRecordingModelWrapper.pop_usage_for_session(
            "sess-unknown-cache",
        )
        assert stored is not None
        assert stored["cache_read_tokens"] == 0
        assert stored["cache_write_tokens"] == 0
        assert stored["cache_hit_rate"] is None

    def test_record_usage_accumulates_all_calls_in_turn(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A tool-heavy turn should include every successful model call."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.model_wrapper._cache_usage_metrics",
            lambda _model, prompt, _read, _write: (True, prompt),
        )
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_current_session_id",
            lambda: "sess-multi-call",
        )
        wrapper, _captured = self._stream_harness(tmp_path, monkeypatch)
        first = MagicMock(
            input_tokens=100,
            output_tokens=10,
            cache_input_tokens=80,
            cache_creation_input_tokens=0,
        )
        second = MagicMock(
            input_tokens=120,
            output_tokens=20,
            cache_input_tokens=100,
            cache_creation_input_tokens=0,
        )

        wrapper._record_usage(first)
        wrapper._record_usage(second)

        stored = TokenRecordingModelWrapper.pop_usage_for_session(
            "sess-multi-call",
        )
        assert stored is not None
        assert stored["prompt_tokens"] == 220
        assert stored["completion_tokens"] == 30
        assert stored["total_tokens"] == 250
        assert stored["cache_read_tokens"] == 180
        assert stored["cache_eligible_input_tokens"] == 220
        assert stored["cache_hit_rate"] == pytest.approx(180 / 220 * 100)

    def test_session_cache_usage_uses_latest_persisted_checkpoint(self):
        """Session totals should extend the newest durable checkpoint."""

        class UnreadableMessage:
            """Fail if aggregation scans before the newest checkpoint."""

            role = "assistant"

            @property
            def metadata(self):
                raise AssertionError("scanned before latest checkpoint")

        def message(role, usage=None):
            metadata = (
                {
                    "qwenpaw_turn_usage": {
                        "usage": usage,
                        "context_usage": None,
                    },
                }
                if usage is not None
                else {}
            )
            return MagicMock(role=role, metadata=metadata)

        messages = [
            UnreadableMessage(),
            message(
                "assistant",
                {
                    "cache_observed": True,
                    "cache_read_tokens": 80,
                    "cache_eligible_input_tokens": 100,
                    "session_cache_observed": True,
                    "session_cache_read_tokens": 100,
                    "session_cache_eligible_input_tokens": 200,
                },
            ),
            message("user"),
            message("assistant"),
        ]
        current_turn = {
            "cache_observed": True,
            "cache_read_tokens": 80,
            "cache_eligible_input_tokens": 100,
        }

        result = add_session_cache_usage(current_turn, messages)

        assert result is not None
        assert result["session_cache_read_tokens"] == 180
        assert result["session_cache_eligible_input_tokens"] == 300
        assert result["session_cache_hit_rate"] == 60

    def test_session_cache_usage_survives_unobserved_current_turn(self):
        """An estimated current turn should retain the prior session rate."""
        previous = MagicMock(
            role="assistant",
            metadata={
                "qwenpaw_turn_usage": {
                    "usage": {
                        "session_cache_observed": True,
                        "session_cache_read_tokens": 90,
                        "session_cache_eligible_input_tokens": 100,
                    },
                    "context_usage": None,
                },
            },
        )
        current_user = MagicMock(role="user", metadata={})
        current_assistant = MagicMock(role="assistant", metadata={})

        result = add_session_cache_usage(
            {"cache_observed": False},
            [previous, current_user, current_assistant],
        )

        assert result is not None
        assert result["session_cache_observed"] is True
        assert result["session_cache_hit_rate"] == 90

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
        mock_usage.cache_input_tokens = 0
        mock_usage.cache_creation_input_tokens = 0
        wrapper._record_usage(mock_usage)

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
