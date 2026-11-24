# -*- coding: utf-8 -*-
"""Unit tests for :mod:`qwenpaw.agents.offloader`.

Covers the date-grouped context archive, the tool-result text dump
(both block-list and plain-string outputs) and the retention cleanup.
All assertions are filesystem based, so the tests stay deterministic
without touching a real agent runtime.
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agentscope.message import Msg
from agentscope.message._block import TextBlock, ToolResultBlock

from qwenpaw.agents.offloader import QwenPawOffloader
from qwenpaw.utils.io_utils import run_sync_io


def _msg(text: str, created_at: str | None = None) -> Msg:
    kwargs = {}
    if created_at is not None:
        kwargs["created_at"] = created_at
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
        **kwargs,
    )


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


@pytest.fixture(name="offloader")
def _offloader(tmp_path) -> QwenPawOffloader:
    return QwenPawOffloader(
        str(tmp_path / "dialog"),
        str(tmp_path / "tools"),
    )


# ---------------------------------------------------------------------------
# offload_context
# ---------------------------------------------------------------------------


class TestOffloadContext:
    async def test_empty_messages_returns_empty_string(self, offloader):
        assert await offloader.offload_context("s1", []) == ""
        # Nothing is created on the empty path.
        assert not Path(offloader._dialog_path).exists()

    async def test_single_message_written_as_jsonl(self, offloader):
        path = await offloader.offload_context("s1", [_msg("hello")])

        assert path.endswith(".jsonl")
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["role"] == "user"
        assert record["content"][0]["text"] == "hello"

    async def test_file_name_uses_message_date(self, offloader):
        path = await offloader.offload_context(
            "s1",
            [_msg("m", created_at="2026-01-02T03:04:05")],
        )

        assert Path(path).name == "2026-01-02.jsonl"

    async def test_messages_grouped_into_per_date_files(self, offloader):
        await offloader.offload_context(
            "s1",
            [
                _msg("a", created_at="2026-01-01T10:00:00"),
                _msg("b", created_at="2026-01-02T10:00:00"),
                _msg("c", created_at="2026-01-01T11:00:00"),
            ],
        )

        dialog = Path(offloader._dialog_path)
        lines1 = (
            (dialog / "2026-01-01.jsonl")
            .read_text(
                encoding="utf-8",
            )
            .splitlines()
        )
        lines2 = (
            (dialog / "2026-01-02.jsonl")
            .read_text(
                encoding="utf-8",
            )
            .splitlines()
        )
        assert len(lines1) == 2
        assert len(lines2) == 1
        assert json.loads(lines1[0])["content"][0]["text"] == "a"
        assert json.loads(lines1[1])["content"][0]["text"] == "c"

    async def test_messages_sorted_by_timestamp_within_a_date(self, offloader):
        await offloader.offload_context(
            "s1",
            [
                _msg("late", created_at="2026-03-01T23:00:00"),
                _msg("early", created_at="2026-03-01T01:00:00"),
            ],
        )

        lines = (
            (Path(offloader._dialog_path) / "2026-03-01.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert json.loads(lines[0])["content"][0]["text"] == "early"
        assert json.loads(lines[1])["content"][0]["text"] == "late"

    async def test_append_across_calls(self, offloader):
        first = await offloader.offload_context(
            "s1",
            [_msg("one", created_at="2026-04-01T00:00:00")],
        )
        await offloader.offload_context(
            "s1",
            [_msg("two", created_at="2026-04-01T01:00:00")],
        )

        lines = Path(first).read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["content"][0]["text"] for line in lines] == [
            "one",
            "two",
        ]

    async def test_returns_last_written_path_for_multiple_dates(
        self,
        offloader,
    ):
        path = await offloader.offload_context(
            "s1",
            [
                _msg("a", created_at="2026-05-01T00:00:00"),
                _msg("b", created_at="2026-05-02T00:00:00"),
            ],
        )

        assert Path(path).exists()
        assert Path(path).name in {"2026-05-01.jsonl", "2026-05-02.jsonl"}

    async def test_session_id_does_not_partition_files(self, offloader):
        """Both sessions land in the same shared date-grouped archive."""
        await offloader.offload_context(
            "session-a",
            [_msg("a", created_at="2026-06-01T00:00:00")],
        )
        await offloader.offload_context(
            "session-b",
            [_msg("b", created_at="2026-06-01T01:00:00")],
        )

        files = list(Path(offloader._dialog_path).iterdir())
        assert [f.name for f in files] == ["2026-06-01.jsonl"]
        assert len(files[0].read_text(encoding="utf-8").splitlines()) == 2

    async def test_unicode_preserved_without_escaping(self, offloader):
        path = await offloader.offload_context(
            "s1",
            [_msg("泰哥好")],
        )

        assert "泰哥好" in Path(path).read_text(encoding="utf-8")

    async def test_broken_timestamp_falls_back_to_today(self, offloader):
        """An unreadable timestamp must not abort the archive."""

        class _Broken:
            @property
            def timestamp(self):
                raise RuntimeError("no timestamp")

            def to_dict(self):
                return {"name": "broken"}

        path = await offloader.offload_context("s1", [_Broken()])

        assert Path(path).name == f"{_today()}.jsonl"
        assert json.loads(
            Path(path).read_text(encoding="utf-8").strip(),
        ) == {"name": "broken"}

    async def test_unsortable_timestamps_keep_insertion_order(
        self,
        offloader,
    ):
        """If ordering blows up, the original order is still archived."""

        class _Unsortable(str):
            """Splits like a timestamp but refuses comparison."""

            def __lt__(self, other):
                raise TypeError("cannot order")

        class _Stub:
            def __init__(self, timestamp, label):
                self._timestamp = timestamp
                self._label = label

            @property
            def timestamp(self):
                return self._timestamp

            def to_dict(self):
                return {"label": self._label}

        msgs = [
            _Stub(_Unsortable("2026-07-01 00:00:00"), "first"),
            _Stub(_Unsortable("2026-07-01 01:00:00"), "second"),
        ]

        path = await offloader.offload_context("s1", msgs)

        lines = Path(path).read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["label"] for line in lines] == [
            "first",
            "second",
        ]


# ---------------------------------------------------------------------------
# offload_tool_result
# ---------------------------------------------------------------------------


def _tool_result(output) -> ToolResultBlock:
    return ToolResultBlock(
        type="tool_result",
        id="call-1",
        name="shell",
        output=output,
    )


def _raw_tool_result(output) -> ToolResultBlock:
    """Build a block bypassing validation.

    ``ToolResultBlock.output`` only accepts ``str`` or a list of
    ``TextBlock``/``DataBlock``, so pydantic coerces plain dicts and
    rejects ``None``.  The offloader still defends against both shapes
    (legacy 1.x payloads and partial blocks); reaching those branches
    requires an unvalidated instance.
    """
    return ToolResultBlock.model_construct(
        type="tool_result",
        id="call-1",
        name="shell",
        output=output,
    )


class TestOffloadToolResult:
    async def test_text_block_list_joined_with_newline(self, offloader):
        path = await offloader.offload_tool_result(
            "s1",
            _tool_result(
                [
                    TextBlock(type="text", text="line one"),
                    TextBlock(type="text", text="line two"),
                ],
            ),
        )

        assert Path(path).parent == Path(offloader._tool_results_dir)
        assert Path(path).suffix == ".txt"
        assert Path(path).read_text(encoding="utf-8") == ("line one\nline two")

    async def test_non_text_blocks_are_skipped(self, offloader):
        path = await offloader.offload_tool_result(
            "s1",
            _raw_tool_result(
                [
                    {"type": "image", "source": "data:..."},
                    TextBlock(type="text", text="kept"),
                ],
            ),
        )

        assert Path(path).read_text(encoding="utf-8") == "kept"

    async def test_dict_text_blocks_are_kept(self, offloader):
        path = await offloader.offload_tool_result(
            "s1",
            _raw_tool_result([{"type": "text", "text": "from dict"}]),
        )

        assert Path(path).read_text(encoding="utf-8") == "from dict"

    async def test_dict_block_without_text_key_yields_empty(self, offloader):
        path = await offloader.offload_tool_result(
            "s1",
            _raw_tool_result([{"type": "text"}]),
        )

        assert Path(path).read_text(encoding="utf-8") == ""

    async def test_plain_string_output(self, offloader):
        path = await offloader.offload_tool_result(
            "s1",
            _tool_result("plain string"),
        )

        assert Path(path).read_text(encoding="utf-8") == "plain string"

    async def test_none_output_becomes_empty_file(self, offloader):
        path = await offloader.offload_tool_result(
            "s1",
            _raw_tool_result(None),
        )

        assert Path(path).exists()
        assert Path(path).read_text(encoding="utf-8") == ""

    async def test_each_call_uses_a_distinct_file(self, offloader):
        first = await offloader.offload_tool_result(
            "s1",
            _tool_result("a"),
        )
        second = await offloader.offload_tool_result(
            "s1",
            _tool_result("b"),
        )

        assert first != second
        assert len(list(Path(offloader._tool_results_dir).iterdir())) == 2

    async def test_creates_missing_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "tools"
        off = QwenPawOffloader(str(tmp_path / "dialog"), str(nested))

        path = await off.offload_tool_result("s1", _tool_result("x"))

        assert nested.is_dir()
        assert Path(path).parent == nested

    async def test_deduplication_reuses_complete_archive(
        self,
        offloader,
        monkeypatch,
    ):
        from qwenpaw.agents import offloader as module

        write = Mock(wraps=module.write_text_atomic)
        monkeypatch.setattr(module, "write_text_atomic", write)
        paths = await asyncio.gather(
            *(
                offloader.offload_tool_result(
                    "s1",
                    _tool_result("same"),
                    deduplicate=True,
                )
                for _ in range(3)
            ),
        )
        assert len(set(paths)) == 1
        assert Path(paths[0]).read_text(encoding="utf-8") == "same"
        write.assert_called_once()
        Path(paths[0]).unlink()
        restored = await offloader.offload_tool_result(
            "s1",
            _tool_result("same"),
            deduplicate=True,
        )
        assert restored == paths[0]
        assert Path(restored).read_text(encoding="utf-8") == "same"

    async def test_deduplication_distinguishes_session_call_and_content(
        self,
        offloader,
    ):
        original = _tool_result("first")
        changed_call = _tool_result("first")
        changed_call.id = "call-2"
        paths = [
            await offloader.offload_tool_result(
                session,
                result,
                deduplicate=True,
            )
            for session, result in (
                ("s1", original),
                ("s2", original),
                ("s1", changed_call),
                ("s1", _tool_result("changed")),
            )
        ]
        assert len(set(paths)) == 4
        assert Path(paths[0]).read_text(encoding="utf-8") == "first"

    @pytest.mark.parametrize("age_days", [29, 31])
    async def test_reused_archive_gets_a_full_retention_window(
        self,
        offloader,
        age_days,
        monkeypatch,
    ):
        from qwenpaw.agents import offloader as module

        path = Path(
            await offloader.offload_tool_result(
                "s1",
                _tool_result("recoverable"),
                deduplicate=True,
            ),
        )
        _age_file(path, days=age_days)
        write = Mock(wraps=module.write_text_atomic)
        monkeypatch.setattr(module, "write_text_atomic", write)

        reused = await offloader.offload_tool_result(
            "s1",
            _tool_result("recoverable"),
            deduplicate=True,
        )

        assert reused == str(path)
        write.assert_not_called()
        assert offloader.cleanup_expired(retention_days=30) == 0
        assert path.read_text(encoding="utf-8") == "recoverable"
        _age_file(path, days=29)
        assert offloader.cleanup_expired(retention_days=30) == 0
        _age_file(path, days=31)
        assert offloader.cleanup_expired(retention_days=30) == 1
        assert not path.exists()

    async def test_reuse_racing_cleanup_keeps_a_complete_archive(
        self,
        offloader,
        monkeypatch,
    ):
        path = Path(
            await offloader.offload_tool_result(
                "s1",
                _tool_result("recoverable"),
                deduplicate=True,
            ),
        )
        _age_file(path, days=31)
        deleting, release = threading.Event(), threading.Event()
        unlink = Path.unlink

        def paused_unlink(target, *args, **kwargs):
            if target == path:
                deleting.set()
                assert release.wait(5)
            return unlink(target, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", paused_unlink)
        cleanup = asyncio.create_task(
            run_sync_io(offloader.cleanup_expired, retention_days=30),
        )
        reuse = None
        try:
            assert await run_sync_io(deleting.wait, 5)
            reuse = asyncio.create_task(
                offloader.offload_tool_result(
                    "s1",
                    _tool_result("recoverable"),
                    deduplicate=True,
                ),
            )
            # Give reuse a chance to overlap the stale deletion decision.
            await asyncio.wait({reuse}, timeout=0.1)
        finally:
            release.set()
            await cleanup
        assert reuse is not None
        assert await reuse == str(path)
        assert path.read_text(encoding="utf-8") == "recoverable"
        assert offloader.cleanup_expired(retention_days=30) == 0


# ---------------------------------------------------------------------------
# cleanup_expired
# ---------------------------------------------------------------------------


def _age_file(path: Path, days: float) -> None:
    """Backdate the file timestamps the retention check reads."""
    stamp = time.time() - days * 86400
    os.utime(path, (stamp, stamp))


class TestCleanupExpired:
    def test_missing_directory_returns_zero(self, tmp_path):
        off = QwenPawOffloader(
            str(tmp_path / "dialog"),
            str(tmp_path / "absent"),
        )

        assert off.cleanup_expired() == 0

    def test_fresh_files_are_kept(self, tmp_path):
        tools = tmp_path / "tools"
        tools.mkdir()
        keep = tools / "fresh.txt"
        keep.write_text("now", encoding="utf-8")
        off = QwenPawOffloader(str(tmp_path / "dialog"), str(tools))

        assert off.cleanup_expired(retention_days=5) == 0
        assert keep.exists()

    def test_expired_files_are_deleted(self, tmp_path):
        tools = tmp_path / "tools"
        tools.mkdir()
        old = tools / "old.txt"
        old.write_text("ancient", encoding="utf-8")
        _age_file(old, days=10)
        fresh = tools / "fresh.txt"
        fresh.write_text("recent", encoding="utf-8")
        off = QwenPawOffloader(str(tmp_path / "dialog"), str(tools))

        assert off.cleanup_expired(retention_days=5) == 1
        assert not old.exists()
        assert fresh.exists()

    def test_retention_window_is_honoured(self, tmp_path):
        tools = tmp_path / "tools"
        tools.mkdir()
        three_days = tools / "three.txt"
        three_days.write_text("3d", encoding="utf-8")
        _age_file(three_days, days=3)
        off = QwenPawOffloader(str(tmp_path / "dialog"), str(tools))

        # Inside the window: kept.
        assert off.cleanup_expired(retention_days=5) == 0
        assert three_days.exists()
        # Outside a shorter window: removed.
        assert off.cleanup_expired(retention_days=1) == 1
        assert not three_days.exists()

    def test_non_txt_files_are_ignored(self, tmp_path):
        tools = tmp_path / "tools"
        tools.mkdir()
        other = tools / "notes.json"
        other.write_text("{}", encoding="utf-8")
        _age_file(other, days=30)
        off = QwenPawOffloader(str(tmp_path / "dialog"), str(tools))

        assert off.cleanup_expired(retention_days=1) == 0
        assert other.exists()

    def test_file_vanishing_mid_scan_is_not_counted(self, tmp_path):
        """A file removed by another worker must not be reported."""
        tools = tmp_path / "tools"
        tools.mkdir()
        gone = tools / "gone.txt"
        gone.write_text("x", encoding="utf-8")
        _age_file(gone, days=20)
        survivor = tools / "old.txt"
        survivor.write_text("y", encoding="utf-8")
        _age_file(survivor, days=20)
        off = QwenPawOffloader(str(tmp_path / "dialog"), str(tools))

        from unittest.mock import patch

        real_stat = os.stat

        def _stat(path, *args, **kwargs):
            if str(path).endswith("gone.txt"):
                raise FileNotFoundError(path)
            return real_stat(path, *args, **kwargs)

        with patch.object(os, "stat", side_effect=_stat):
            assert off.cleanup_expired(retention_days=1) == 1

        assert not survivor.exists()

    def test_stat_failure_is_swallowed(self, tmp_path):
        """A stat error counts as failed, not deleted, and never raises."""
        tools = tmp_path / "tools"
        tools.mkdir()
        bad = tools / "bad.txt"
        bad.write_text("x", encoding="utf-8")
        _age_file(bad, days=20)
        off = QwenPawOffloader(str(tmp_path / "dialog"), str(tools))

        from unittest.mock import patch

        real_stat = os.stat

        def _stat(path, *args, **kwargs):
            # Only the scanned entry fails; Path.exists() on the directory
            # must keep working.
            if str(path).endswith("bad.txt"):
                raise OSError("boom")
            return real_stat(path, *args, **kwargs)

        with patch.object(os, "stat", side_effect=_stat):
            assert off.cleanup_expired(retention_days=1) == 0

        assert bad.exists()

    def test_default_retention_is_five_days(self, tmp_path):
        tools = tmp_path / "tools"
        tools.mkdir()
        four = tools / "four.txt"
        four.write_text("4d", encoding="utf-8")
        _age_file(four, days=4)
        six = tools / "six.txt"
        six.write_text("6d", encoding="utf-8")
        _age_file(six, days=6)
        off = QwenPawOffloader(str(tmp_path / "dialog"), str(tools))

        assert off.cleanup_expired() == 1
        assert four.exists()
        assert not six.exists()

    @pytest.mark.parametrize(
        ("mtime_days", "creation_days", "deleted"),
        [(10, 0, 1), (0, 10, 0)],
    )
    def test_retention_uses_mtime_instead_of_creation_time(
        self,
        tmp_path,
        monkeypatch,
        mtime_days,
        creation_days,
        deleted,
    ):
        """Creation timestamps must not override the latest reference time."""
        tools = tmp_path / "tools"
        tools.mkdir()
        target = tools / "archive.txt"
        target.write_text("x", encoding="utf-8")
        _age_file(target, days=mtime_days)
        off = QwenPawOffloader(str(tmp_path / "dialog"), str(tools))
        real_stat = os.stat
        creation = time.time() - creation_days * 86400

        def _stat(path, *args, **kwargs):
            st = real_stat(path, *args, **kwargs)
            if Path(path) == target:
                return SimpleNamespace(
                    st_mtime=st.st_mtime,
                    st_ctime=creation,
                    st_birthtime=creation,
                )
            return st

        with monkeypatch.context() as patcher:
            patcher.setattr(os, "stat", _stat)
            assert off.cleanup_expired(retention_days=5) == deleted

        assert target.exists() is (deleted == 0)
