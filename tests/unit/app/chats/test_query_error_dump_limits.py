# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Tests for the bounded retention policy of query error dumps."""

from __future__ import annotations

import json
import os
import time

import pytest

from qwenpaw.app.chats import query_error_dump as dump_mod

_LIMIT_ENVS = (
    "QWENPAW_QUERY_ERROR_DUMP_DIR",
    "QWENPAW_QUERY_ERROR_DUMP_MAX_FILES",
    "QWENPAW_QUERY_ERROR_DUMP_MAX_TOTAL_MB",
    "QWENPAW_QUERY_ERROR_DUMP_MAX_FILE_MB",
    "QWENPAW_QUERY_ERROR_DUMP_MAX_AGE_DAYS",
    "QWENPAW_QUERY_ERROR_DUMP_MIN_INTERVAL_SECONDS",
    "QWENPAW_QUERY_ERROR_DUMP_AGENT_STATE",
)


@pytest.fixture(autouse=True)
def clean_limit_env(monkeypatch):
    """Keep every test independent from the ambient dump configuration."""
    for name in _LIMIT_ENVS:
        monkeypatch.delenv(name, raising=False)
    dump_mod._recent_dumps.clear()


@pytest.fixture()
def dump_dir(monkeypatch, tmp_path):
    """Point the dump directory and tempfile fallback at a test directory."""
    target = tmp_path / "dumps"
    target.mkdir()
    monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_DIR", str(target))
    monkeypatch.setattr(dump_mod.tempfile, "gettempdir", lambda: str(target))
    return target


def _write_dump(agent=None, message="boom"):
    """Write one dump and return its path."""
    result = None
    try:
        raise ValueError(message)
    except BaseException as caught:  # noqa: BLE001 - mirrors prod usage
        result = dump_mod.write_query_error_dump(
            None,
            caught,
            {"agent": agent},
        )
    return result


def _disable_limits(monkeypatch):
    """Turn off the retention limits so one test isolates one policy."""
    monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILES", "0")
    monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_TOTAL_MB", "0")
    monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_AGE_DAYS", "0")


def _make_dump(directory, name, size=10, age_seconds=0.0):
    """Create a fake dump on disk with a controllable mtime and size."""
    path = directory / f"qwenpaw_query_error_{name}.json"
    path.write_bytes(b"x" * size)
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(path, (old, old))
    return path


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class TestResolveLimits:
    def test_defaults_are_used_when_unset(self):
        policy = dump_mod._resolve_policy()
        assert policy == dump_mod.DumpPolicy(
            max_files=dump_mod.DEFAULT_MAX_FILES,
            max_total_bytes=dump_mod.DEFAULT_MAX_TOTAL_MB * 1024**2,
            max_file_bytes=dump_mod.DEFAULT_MAX_FILE_MB * 1024**2,
            max_age_seconds=dump_mod.DEFAULT_MAX_AGE_DAYS * 86400,
            min_interval_seconds=(dump_mod.DEFAULT_MIN_INTERVAL_SECONDS),
            include_agent_state=True,
        )

    def test_environment_overrides_every_limit(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILES", "3")
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_TOTAL_MB", "2")
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILE_MB", "1")
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_AGE_DAYS", "2")
        monkeypatch.setenv(
            "QWENPAW_QUERY_ERROR_DUMP_MIN_INTERVAL_SECONDS",
            "30",
        )
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_AGENT_STATE", "false")
        assert dump_mod._resolve_policy() == dump_mod.DumpPolicy(
            max_files=3,
            max_total_bytes=2 * 1024**2,
            max_file_bytes=1 * 1024**2,
            max_age_seconds=2 * 86400,
            min_interval_seconds=30,
            include_agent_state=False,
        )

    @pytest.mark.parametrize(
        "value",
        ["", "many", "-1", "1.5"],
    )
    def test_invalid_values_fall_back_to_defaults(self, monkeypatch, value):
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILES", value)
        policy = dump_mod._resolve_policy()
        assert policy.max_files == dump_mod.DEFAULT_MAX_FILES

    def test_zero_disables_a_limit(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILES", "0")
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_AGE_DAYS", "0")
        policy = dump_mod._resolve_policy()
        assert policy.max_files == 0
        assert policy.max_age_seconds == 0


class TestConfiguredDirectory:
    def test_dump_lands_in_the_configured_directory(self, dump_dir):
        path = _write_dump()
        assert os.path.dirname(path) == str(dump_dir)

    def test_directory_is_created_on_demand(self, monkeypatch, tmp_path):
        target = tmp_path / "nested" / "dumps"
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_DIR", str(target))

        path = _write_dump()

        assert os.path.isfile(path)
        assert target.is_dir()

    def test_unusable_directory_falls_back_to_temp(
        self,
        monkeypatch,
        tmp_path,
    ):
        fallback = tmp_path / "fallback"
        fallback.mkdir()
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")

        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_DIR", str(blocker / "x"))
        monkeypatch.setattr(
            dump_mod.tempfile,
            "gettempdir",
            lambda: str(fallback),
        )

        path = _write_dump()

        assert os.path.dirname(path) == str(fallback)


class TestRetention:
    def test_file_count_limit_keeps_the_newest(self, dump_dir, monkeypatch):
        _disable_limits(monkeypatch)
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILES", "3")
        for index in range(5):
            _make_dump(dump_dir, f"old{index}", age_seconds=1000 - index)

        newest = _write_dump()

        remaining = sorted(dump_dir.glob("qwenpaw_query_error_*.json"))
        assert len(remaining) == 3
        assert newest in [str(path) for path in remaining]

    def test_age_limit_removes_expired_dumps(self, dump_dir, monkeypatch):
        _disable_limits(monkeypatch)
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_AGE_DAYS", "1")
        expired = _make_dump(dump_dir, "expired", age_seconds=10 * 86400)
        fresh = _make_dump(dump_dir, "fresh", age_seconds=60)

        _write_dump()

        assert not expired.exists()
        assert fresh.exists()

    def test_total_size_limit_removes_oldest_first(
        self,
        dump_dir,
        monkeypatch,
    ):
        _disable_limits(monkeypatch)
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_TOTAL_MB", "1")
        old = _make_dump(
            dump_dir,
            "old",
            size=700 * 1024,
            age_seconds=600,
        )
        recent = _make_dump(
            dump_dir,
            "recent",
            size=700 * 1024,
            age_seconds=60,
        )

        _write_dump()

        assert not old.exists()
        assert recent.exists()

    def test_unrelated_temp_files_are_never_removed(
        self,
        dump_dir,
        monkeypatch,
    ):
        _disable_limits(monkeypatch)
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILES", "1")
        unrelated = dump_dir / "someone_elses_file.json"
        unrelated.write_text("{}", encoding="utf-8")
        lookalike = dump_dir / "notes_qwenpaw_query_error_.json"
        lookalike.write_text("{}", encoding="utf-8")
        _make_dump(dump_dir, "old", age_seconds=90)

        _write_dump()

        assert unrelated.exists()
        assert lookalike.exists()

    def test_newest_dump_survives_even_over_the_total_budget(
        self,
        dump_dir,
        monkeypatch,
    ):
        _disable_limits(monkeypatch)
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_TOTAL_MB", "1")
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILES", "1")
        old = _make_dump(dump_dir, "old", size=5 * 1024**2, age_seconds=600)

        newest = _write_dump()

        assert os.path.isfile(newest)
        assert not old.exists()

    def test_a_burst_of_writes_is_still_bounded(
        self,
        dump_dir,
        monkeypatch,
    ):
        _disable_limits(monkeypatch)
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILES", "2")
        monkeypatch.setenv(
            "QWENPAW_QUERY_ERROR_DUMP_MIN_INTERVAL_SECONDS",
            "0",
        )

        for index in range(5):
            assert _write_dump(message=f"failure {index}")

        assert len(list(dump_dir.glob("qwenpaw_query_error_*.json"))) == 2


class TestThrottle:
    def test_identical_error_reuses_the_previous_dump(
        self,
        dump_dir,
        monkeypatch,
    ):
        monkeypatch.setenv(
            "QWENPAW_QUERY_ERROR_DUMP_MIN_INTERVAL_SECONDS",
            "600",
        )

        first = _write_dump()
        second = _write_dump()

        assert first == second
        assert len(list(dump_dir.glob("qwenpaw_query_error_*.json"))) == 1

    def test_different_message_creates_a_new_dump(
        self,
        dump_dir,
        monkeypatch,
    ):
        monkeypatch.setenv(
            "QWENPAW_QUERY_ERROR_DUMP_MIN_INTERVAL_SECONDS",
            "600",
        )

        first = _write_dump(message="connection reset")
        second = _write_dump(message="dns lookup failed")

        assert first != second
        assert len(list(dump_dir.glob("qwenpaw_query_error_*.json"))) == 2

    def test_zero_interval_disables_throttling(
        self,
        dump_dir,
        monkeypatch,
    ):
        monkeypatch.setenv(
            "QWENPAW_QUERY_ERROR_DUMP_MIN_INTERVAL_SECONDS",
            "0",
        )

        first = _write_dump()
        second = _write_dump()

        assert first != second

    def test_expired_entry_creates_a_new_dump(
        self,
        dump_dir,
        monkeypatch,
    ):
        monkeypatch.setenv(
            "QWENPAW_QUERY_ERROR_DUMP_MIN_INTERVAL_SECONDS",
            "600",
        )
        first = _write_dump()
        key = next(iter(dump_mod._recent_dumps))
        recorded, path = dump_mod._recent_dumps[key]
        dump_mod._recent_dumps[key] = (recorded - 601, path)

        second = _write_dump()

        assert first != second

    def test_deleted_dump_is_written_again(self, dump_dir, monkeypatch):
        monkeypatch.setenv(
            "QWENPAW_QUERY_ERROR_DUMP_MIN_INTERVAL_SECONDS",
            "600",
        )
        first = _write_dump()
        os.unlink(first)

        second = _write_dump()

        assert second != first
        assert os.path.isfile(second)


class TestAgentStateToggle:
    def test_state_is_not_collected_when_disabled(
        self,
        dump_dir,
        monkeypatch,
    ):
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_AGENT_STATE", "false")
        collected = []

        class Agent:
            def state_dict(self):
                collected.append(True)
                return {"history": "x"}

        payload = _read(_write_dump(Agent()))

        assert payload["agent_state"] is None
        assert collected == []

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_truthy_values_enable_state(self, monkeypatch, value):
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_AGENT_STATE", value)
        assert dump_mod._resolve_policy().include_agent_state is True

    @pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
    def test_falsey_values_disable_state(self, monkeypatch, value):
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_AGENT_STATE", value)
        assert dump_mod._resolve_policy().include_agent_state is False


class TestPerFileSizeCap:
    def test_oversized_agent_state_is_replaced_by_a_summary(
        self,
        dump_dir,
        monkeypatch,
    ):
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILE_MB", "1")

        class Agent:
            def state_dict(self):
                return {"history": "x" * (3 * 1024**2)}

        path = _write_dump(Agent())

        payload = _read(path)
        assert os.path.getsize(path) <= 1024**2
        assert payload["agent_state"]["_omitted"]
        assert payload["agent_state"]["_bytes"] > 1024**2
        assert payload["truncated"] is True

    def test_small_dumps_are_written_verbatim(self, dump_dir, monkeypatch):
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILE_MB", "1")

        class Agent:
            def state_dict(self):
                return {"turns": 2}

        payload = _read(_write_dump(Agent()))

        assert payload["agent_state"] == {"turns": 2}
        assert "truncated" not in payload

    def test_zero_file_limit_disables_the_cap(self, dump_dir, monkeypatch):
        monkeypatch.setenv("QWENPAW_QUERY_ERROR_DUMP_MAX_FILE_MB", "0")

        class Agent:
            def state_dict(self):
                return {"history": "x" * (2 * 1024**2)}

        path = _write_dump(Agent())

        assert os.path.getsize(path) > 1024**2
        assert _read(path)["agent_state"]["history"]


class TestShrinkPayload:
    def _payload(self):
        return {
            "trace": "t" * 100_000,
            "exception_type": "ConnectionError",
            "exception_message": "upstream down",
            "request_info": {"session_id": "s"},
            "request": {"body": "r" * 100_000},
            "agent_state": {"history": "a" * 100_000},
        }

    def test_payload_within_budget_is_unchanged(self):
        payload = self._payload()
        assert dump_mod._shrink_payload(
            payload, payload["trace"], 10**9
        ) == (payload)

    def test_zero_budget_disables_shrinking(self):
        payload = self._payload()
        assert (
            dump_mod._shrink_payload(payload, payload["trace"], 0) == payload
        )

    def test_agent_state_is_dropped_first(self):
        payload = self._payload()
        shrunk = dump_mod._shrink_payload(
            payload,
            payload["trace"],
            250_000,
        )

        assert shrunk["agent_state"]["_omitted"]
        assert shrunk["trace"] == payload["trace"]
        assert shrunk["truncated"] is True
        assert dump_mod._json_text_size(shrunk) <= 250_000

    def test_trace_is_truncated_before_the_request_is_dropped(self):
        payload = self._payload()
        payload["agent_state"] = None
        payload["request"] = {"body": "r" * 10_000}
        shrunk = dump_mod._shrink_payload(
            payload,
            payload["trace"],
            45_000,
        )

        assert len(shrunk["trace"]) == dump_mod._TRACE_TAIL_CHARS
        assert shrunk["request"] == payload["request"]
        assert dump_mod._json_text_size(shrunk) <= 45_000

    def test_oversized_request_is_dropped(self):
        payload = self._payload()
        payload["agent_state"] = None
        payload["trace"] = "short trace"
        shrunk = dump_mod._shrink_payload(
            payload,
            payload["trace"],
            5_000,
        )

        assert shrunk["request"]["_omitted"]
        assert dump_mod._json_text_size(shrunk) <= 5_000

    def test_tiny_budget_falls_back_to_identifying_fields(self):
        payload = self._payload()
        shrunk = dump_mod._shrink_payload(
            payload,
            payload["trace"],
            2_000,
        )

        assert set(shrunk) == {
            "trace",
            "exception_type",
            "exception_message",
            "request_info",
            "request",
            "agent_state",
            "ts_utc",
            "truncated",
        }
        assert shrunk["trace"] == payload["trace"][-1000:]
        assert shrunk["request"] is None
        assert shrunk["agent_state"] is None
        assert dump_mod._json_text_size(shrunk) <= 2_000


class TestFailureHandling:
    def test_failed_write_leaves_no_partial_file(
        self,
        dump_dir,
        monkeypatch,
    ):
        def deny(*args, **kwargs):
            raise TypeError("not serializable")

        monkeypatch.setattr(dump_mod.json, "dump", deny)

        assert _write_dump() is None
        assert list(dump_dir.iterdir()) == []

    def test_prune_failure_does_not_lose_the_dump(
        self,
        dump_dir,
        monkeypatch,
    ):
        def explode(*args, **kwargs):
            raise RuntimeError("cannot scan")

        monkeypatch.setattr(dump_mod.os, "scandir", explode)

        path = _write_dump()

        assert os.path.isfile(path)
