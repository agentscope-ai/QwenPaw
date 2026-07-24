# -*- coding: utf-8 -*-
"""Unit tests for per-user token usage attribution."""
from __future__ import annotations

import json
from datetime import date

import pytest

from qwenpaw.token_usage.buffer import _UsageEvent, _apply_event

DAY = date(2026, 7, 23)


def _event(**overrides) -> _UsageEvent:
    """Build a usage event with sensible defaults."""
    kwargs = {
        "provider_id": "openai",
        "model_name": "gpt-4",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "date_str": "2026-07-23",
        "now_iso": "2026-07-23T10:00:00+00:00",
    }
    kwargs.update(overrides)
    return _UsageEvent(**kwargs)


class TestApplyEventByUser:
    """``_apply_event`` records a per-user bucket inside each entry."""

    def test_event_with_user_creates_by_user_bucket(self):
        """A user-attributed event lands in ``by_user`` under that user."""
        cache: dict = {}
        _apply_event(cache, _event(user_id="alice"))

        entry = cache["2026-07-23"]["openai:gpt-4"]
        assert entry["by_user"]["alice"] == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "call_count": 1,
        }

    def test_by_user_totals_match_entry_totals(self):
        """Per-user buckets sum back to the entry's own counters."""
        cache: dict = {}
        _apply_event(cache, _event(user_id="alice"))
        _apply_event(cache, _event(user_id="bob", prompt_tokens=20))

        entry = cache["2026-07-23"]["openai:gpt-4"]
        assert entry["prompt_tokens"] == 120
        assert entry["call_count"] == 2
        by_user = entry["by_user"]
        assert sum(u["prompt_tokens"] for u in by_user.values()) == 120
        assert sum(u["call_count"] for u in by_user.values()) == 2

    def test_event_without_user_falls_back_to_system(self):
        """Calls with no user context are attributed to ``system``."""
        cache: dict = {}
        _apply_event(cache, _event())

        entry = cache["2026-07-23"]["openai:gpt-4"]
        assert entry["by_user"]["system"]["prompt_tokens"] == 100

    def test_legacy_entry_keeps_totals_when_user_arrives(self):
        """A pre-existing entry without ``by_user`` is extended, not reset."""
        cache = {
            "2026-07-23": {
                "openai:gpt-4": {
                    "provider_id": "openai",
                    "model_name": "gpt-4",
                    "prompt_tokens": 900,
                    "completion_tokens": 450,
                    "call_count": 9,
                },
            },
        }
        _apply_event(cache, _event(user_id="alice"))

        entry = cache["2026-07-23"]["openai:gpt-4"]
        assert entry["prompt_tokens"] == 1000
        assert entry["call_count"] == 10
        assert entry["by_user"] == {
            "alice": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "call_count": 1,
            },
        }


class TestUsageEventDefaults:
    """``_UsageEvent`` stays constructible without a user id."""

    def test_user_id_defaults_to_empty(self):
        """Existing callers that omit ``user_id`` still build an event."""
        assert _event().user_id == ""


class TestManagerRecordByUser:
    """``TokenUsageManager.record()`` forwards the user id."""

    @pytest.mark.asyncio
    async def test_record_attributes_user(self, tmp_path, monkeypatch):
        """A recorded call shows up under the given user."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )
        from qwenpaw.token_usage.manager import TokenUsageManager

        manager = TokenUsageManager()
        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            user_id="alice",
        )

        # pylint: disable=protected-access
        merged = await manager._buffer.get_merged_data()
        date_str = next(iter(merged))
        entry = merged[date_str]["openai:gpt-4"]
        assert entry["by_user"]["alice"]["prompt_tokens"] == 100


class TestPersistenceRoundTrip:
    """Attribution survives a flush to disk and a reload."""

    @pytest.mark.asyncio
    async def test_by_user_survives_flush_and_reload(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A recorded caller is still there after restart."""
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.WORKING_DIR",
            tmp_path,
        )
        monkeypatch.setattr(
            "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
            "test_token_usage.json",
        )
        from qwenpaw.token_usage.manager import TokenUsageManager

        writer = TokenUsageManager()
        writer.start(flush_interval=10)
        await writer.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            user_id="alice",
        )
        await writer.stop()  # drains the queue and flushes

        reader = TokenUsageManager()
        records = await reader.get_details(
            start_date=date.today(),
            end_date=date.today(),
            user_id="alice",
        )

        assert [r.prompt_tokens for r in records] == [100]


def _manager_with_data(tmp_path, monkeypatch, data: dict):
    """Return a manager backed by *data* already on disk."""
    monkeypatch.setattr("qwenpaw.token_usage.manager.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
        "test_token_usage.json",
    )
    (tmp_path / "test_token_usage.json").write_text(
        json.dumps(data),
        encoding="utf-8",
    )
    from qwenpaw.token_usage.manager import TokenUsageManager

    return TokenUsageManager()


def _entry(by_user: dict | None, prompt: int, completion: int, calls: int):
    """Build one on-disk provider:model entry."""
    entry = {
        "provider_id": "openai",
        "model_name": "gpt-4",
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "call_count": calls,
    }
    if by_user is not None:
        entry["by_user"] = by_user
    return {"2026-07-23": {"openai:gpt-4": entry}}


def _bucket(prompt: int, completion: int, calls: int) -> dict:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "call_count": calls,
    }


class TestGetDetailsByUser:
    """``get_details()`` expands entries into one record per user."""

    @pytest.mark.asyncio
    async def test_one_record_per_user(self, tmp_path, monkeypatch):
        """Each user bucket becomes its own record."""
        manager = _manager_with_data(
            tmp_path,
            monkeypatch,
            _entry(
                {"alice": _bucket(100, 50, 1), "bob": _bucket(20, 10, 1)},
                120,
                60,
                2,
            ),
        )

        records = await manager.get_details(start_date=DAY, end_date=DAY)

        by_user = {r.user_id: r for r in records}
        assert set(by_user) == {"alice", "bob"}
        assert by_user["alice"].prompt_tokens == 100
        assert by_user["bob"].completion_tokens == 10
        assert by_user["alice"].model == "gpt-4"

    @pytest.mark.asyncio
    async def test_legacy_entry_reports_as_unknown(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Data written before per-user tracking is attributed to unknown."""
        manager = _manager_with_data(
            tmp_path,
            monkeypatch,
            _entry(None, 900, 450, 9),
        )

        records = await manager.get_details(start_date=DAY, end_date=DAY)

        assert len(records) == 1
        assert records[0].user_id == "unknown"
        assert records[0].prompt_tokens == 900
        assert records[0].call_count == 9

    @pytest.mark.asyncio
    async def test_residual_between_totals_and_buckets(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Totals not covered by any bucket surface as an unknown record."""
        manager = _manager_with_data(
            tmp_path,
            monkeypatch,
            _entry({"alice": _bucket(100, 50, 1)}, 1000, 500, 10),
        )

        records = await manager.get_details(start_date=DAY, end_date=DAY)

        by_user = {r.user_id: r for r in records}
        assert by_user["unknown"].prompt_tokens == 900
        assert by_user["unknown"].completion_tokens == 450
        assert by_user["unknown"].call_count == 9

    @pytest.mark.asyncio
    async def test_filters_by_user(self, tmp_path, monkeypatch):
        """``user_id`` narrows the result to that caller."""
        manager = _manager_with_data(
            tmp_path,
            monkeypatch,
            _entry(
                {"alice": _bucket(100, 50, 1), "bob": _bucket(20, 10, 1)},
                120,
                60,
                2,
            ),
        )

        records = await manager.get_details(
            start_date=DAY,
            end_date=DAY,
            user_id="bob",
        )

        assert [r.user_id for r in records] == ["bob"]
        assert records[0].prompt_tokens == 20


class TestGetSummaryByUser:
    """``get_summary()`` aggregates a ``by_user`` breakdown."""

    @pytest.mark.asyncio
    async def test_by_user_aggregation(self, tmp_path, monkeypatch):
        """Per-user totals are summed across models and dates."""
        manager = _manager_with_data(
            tmp_path,
            monkeypatch,
            _entry(
                {"alice": _bucket(100, 50, 1), "bob": _bucket(20, 10, 1)},
                120,
                60,
                2,
            ),
        )

        summary = await manager.get_summary(start_date=DAY, end_date=DAY)

        assert set(summary.by_user) == {"alice", "bob"}
        assert summary.by_user["alice"].prompt_tokens == 100
        assert summary.by_user["bob"].call_count == 1

    @pytest.mark.asyncio
    async def test_totals_unchanged_by_expansion(self, tmp_path, monkeypatch):
        """Expanding per user must not change the reported totals."""
        manager = _manager_with_data(
            tmp_path,
            monkeypatch,
            _entry({"alice": _bucket(100, 50, 1)}, 1000, 500, 10),
        )

        summary = await manager.get_summary(start_date=DAY, end_date=DAY)

        assert summary.total_prompt_tokens == 1000
        assert summary.total_completion_tokens == 500
        assert summary.total_calls == 10
        assert summary.by_model["openai:gpt-4"].prompt_tokens == 1000


class _FakeUsage:
    """Minimal stand-in for agentscope's ChatUsage."""

    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeChunk:
    """Stream chunk carrying usage on the last element."""

    def __init__(self, usage=None) -> None:
        self.usage = usage


class _FakeStreamingModel:
    """Model whose call returns an async generator of chunks."""

    model = "gpt-4"
    context_size = 32768

    def __init__(self, chunks) -> None:
        self._chunks = chunks

    async def __call__(self, **_kwargs):
        async def _gen():
            for chunk in self._chunks:
                yield chunk

        return _gen()


@pytest.fixture(name="usage_manager")
def _usage_manager(tmp_path, monkeypatch):
    """Point the token usage singleton at a temp file."""
    from qwenpaw.token_usage.manager import TokenUsageManager

    monkeypatch.setattr("qwenpaw.token_usage.manager.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
        "test_token_usage.json",
    )
    # pylint: disable=protected-access
    TokenUsageManager._instance = None
    yield TokenUsageManager.get_instance()
    TokenUsageManager._instance = None


async def _recorded_users(manager) -> dict:
    """Return the ``by_user`` bucket of the single recorded entry."""
    # pylint: disable=protected-access
    merged = await manager._buffer.get_merged_data()
    date_str = next(iter(merged))
    return merged[date_str]["openai:gpt-4"]["by_user"]


class TestModelWrapperAttribution:
    """The model wrapper attributes usage to the current caller."""

    @pytest.fixture(autouse=True)
    def _reset_user(self):
        from qwenpaw.app.agent_context import set_current_user_id

        set_current_user_id(None)
        yield
        set_current_user_id(None)

    @pytest.mark.asyncio
    async def test_records_current_user(self, usage_manager):
        """A non-streamed call is billed to the request's caller."""
        from qwenpaw.app.agent_context import set_current_user_id
        from qwenpaw.token_usage.model_wrapper import (
            TokenRecordingModelWrapper,
        )

        set_current_user_id("alice")
        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=_FakeStreamingModel([]),
        )
        # pylint: disable=protected-access
        wrapper._record_usage(_FakeUsage(100, 50))

        by_user = await _recorded_users(usage_manager)
        assert by_user["alice"]["prompt_tokens"] == 100

    @pytest.mark.asyncio
    async def test_records_system_without_user(self, usage_manager):
        """Calls with no request context are billed to ``system``."""
        from qwenpaw.token_usage.model_wrapper import (
            TokenRecordingModelWrapper,
        )

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=_FakeStreamingModel([]),
        )
        # pylint: disable=protected-access
        wrapper._record_usage(_FakeUsage(100, 50))

        by_user = await _recorded_users(usage_manager)
        assert by_user["system"]["prompt_tokens"] == 100

    @pytest.mark.asyncio
    async def test_stream_bills_the_caller_that_started_it(
        self,
        usage_manager,
    ):
        """Streamed usage lands on the caller present when the call began."""
        from qwenpaw.app.agent_context import set_current_user_id
        from qwenpaw.token_usage.model_wrapper import (
            TokenRecordingModelWrapper,
        )

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=_FakeStreamingModel(
                [_FakeChunk(), _FakeChunk(_FakeUsage(100, 50))],
            ),
        )

        set_current_user_id("alice")
        stream = await wrapper(messages=[])
        # The context has moved on by the time the stream is drained.
        set_current_user_id("bob")
        async for _ in stream:
            pass

        by_user = await _recorded_users(usage_manager)
        assert "bob" not in by_user
        assert by_user["alice"]["prompt_tokens"] == 100
