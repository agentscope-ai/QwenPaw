# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the shell output disk-size accounting.

``_check_output_disk_size`` decides when a long-running command is
writing more output than the disk cap allows. It is consulted in the
subprocess poll loop, and both of its failure modes matter: a size
that is too small lets the output grow without bound, while a raised
exception kills a command that was merely verbose.

The two streams are independent and each one can arrive either as an
open reader (the Windows shape) or as a path (the POSIX shape), so the
interesting cases are the precedence between them and which stat
failures are swallowed.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from qwenpaw.agents.tools.shell import (
    _SHELL_MAX_DISK_BYTES,
    _check_output_disk_size,
)


class _OSErrorFileno(io.RawIOBase):
    """A reader whose fileno() fails the way a dead handle does."""

    def fileno(self) -> int:
        raise OSError(9, "Bad file descriptor")

    def readable(self) -> bool:
        return True


class _ValueErrorFileno:
    """A reader whose fileno() fails with something that is not OSError."""

    def fileno(self) -> int:
        raise ValueError("not an OSError")


class _StaleFd:
    """Reports a file descriptor number that nothing holds."""

    def __init__(self, number: int) -> None:
        self._number = number

    def fileno(self) -> int:
        return self._number


def _write(path: Path, size: int) -> Path:
    """Create a file of exactly ``size`` bytes and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"z" * size)
    return path


class TestPathBasedAccounting:
    """POSIX hands the helper two temp-file paths."""

    def test_no_inputs_at_all_is_zero(self):
        assert _check_output_disk_size(None, None, None, None) == 0

    def test_both_streams_are_summed(self, tmp_path):
        out = _write(tmp_path / "out.bin", 100)
        err = _write(tmp_path / "err.bin", 30)

        total = _check_output_disk_size(str(out), str(err), None, None)

        assert total == 130

    @pytest.mark.parametrize(
        ("out_size", "err_size", "expected"),
        [(100, None, 100), (None, 30, 30), (None, None, 0)],
    )
    def test_a_single_stream_is_counted_alone(
        self,
        tmp_path,
        out_size,
        err_size,
        expected,
    ):
        out = _write(tmp_path / "out.bin", out_size) if out_size else None
        err = _write(tmp_path / "err.bin", err_size) if err_size else None

        total = _check_output_disk_size(
            str(out) if out else None,
            str(err) if err else None,
            None,
            None,
        )

        assert total == expected

    def test_a_zero_byte_file_counts_as_zero(self, tmp_path):
        empty = _write(tmp_path / "empty.bin", 0)

        assert _check_output_disk_size(str(empty), None, None, None) == 0

    def test_the_real_size_is_reported_not_a_cached_one(self, tmp_path):
        out = _write(tmp_path / "out.bin", 10)

        first = _check_output_disk_size(str(out), None, None, None)
        out.write_bytes(b"z" * 5000)
        second = _check_output_disk_size(str(out), None, None, None)

        assert first == 10
        assert second == 5000

    def test_a_missing_path_is_skipped_not_fatal(self, tmp_path):
        """The output file can be gone by the time the loop polls it."""
        gone = tmp_path / "already_removed.bin"

        total = _check_output_disk_size(
            str(gone),
            str(_write(tmp_path / "err.bin", 30)),
            None,
            None,
        )

        assert not gone.exists()
        assert total == 30

    def test_both_paths_missing_is_zero(self, tmp_path):
        total = _check_output_disk_size(
            str(tmp_path / "gone1.bin"),
            str(tmp_path / "gone2.bin"),
            None,
            None,
        )

        assert total == 0

    def test_a_directory_path_uses_its_own_stat_size(self, tmp_path):
        """stat() succeeds on a directory, so it must not crash."""
        total = _check_output_disk_size(str(tmp_path), None, None, None)

        assert total == os.stat(tmp_path).st_size


class TestReaderBasedAccounting:
    """Windows keeps the temp files open and passes the readers."""

    def test_both_readers_are_summed(self, tmp_path):
        out = _write(tmp_path / "out.bin", 100)
        err = _write(tmp_path / "err.bin", 30)
        with out.open("rb") as out_reader, err.open("rb") as err_reader:
            total = _check_output_disk_size(
                None,
                None,
                out_reader,
                err_reader,
            )

        assert total == 130

    def test_a_reader_wins_over_the_path_for_the_same_stream(self, tmp_path):
        """The reader branch is the ``if``; the path is an ``elif``."""
        big = _write(tmp_path / "big.bin", 5000)
        small = _write(tmp_path / "small.bin", 100)
        with small.open("rb") as reader:
            total = _check_output_disk_size(str(big), None, reader, None)

        assert total == 100

    def test_one_reader_and_one_path_are_summed(self, tmp_path):
        out = _write(tmp_path / "out.bin", 100)
        err = _write(tmp_path / "err.bin", 30)
        with out.open("rb") as reader:
            total = _check_output_disk_size(None, str(err), reader, None)

        assert total == 130

    def test_a_dead_reader_handle_is_skipped_not_fatal(self, tmp_path):
        """A broken handle costs that stream only, and never raises."""
        err = _write(tmp_path / "err.bin", 30)

        # The stdout reader is dead, so stdout contributes nothing - and
        # the stdout path is an elif, so it is not used as a fallback.
        # stderr has no reader, so its path leg is still consulted.
        total = _check_output_disk_size(
            str(_write(tmp_path / "out.bin", 100)),
            str(err),
            _OSErrorFileno(),
            None,
        )
        other = _check_output_disk_size(None, str(err), None, _OSErrorFileno())

        assert total == 30
        assert other == 0

    def test_a_stale_descriptor_number_is_skipped_not_fatal(self, tmp_path):
        out = _write(tmp_path / "out.bin", 100)

        total = _check_output_disk_size(None, None, _StaleFd(9999), None)
        with_path = _check_output_disk_size(
            str(out),
            None,
            _StaleFd(9999),
            None,
        )

        assert total == 0
        # The path leg is an elif, so it is not consulted as a fallback.
        assert with_path == 0


class TestErrorsThatMustNotBeSwallowed:
    """Only OSError is guarded; anything else has to surface."""

    def test_a_closed_reader_raises_instead_of_reporting_zero(self, tmp_path):
        """A closed file raises ValueError, which the guard does not catch.

        Reporting 0 here would silently disable the disk cap for the
        rest of the command, so the loud failure is the wanted shape.
        """
        out = _write(tmp_path / "out.bin", 100)
        reader = out.open("rb")
        reader.close()

        with pytest.raises(ValueError):
            _check_output_disk_size(None, None, reader, None)

    def test_a_closed_reader_also_defeats_the_path_leg(self, tmp_path):
        """The path is an elif, so it is never reached as a fallback."""
        out = _write(tmp_path / "out.bin", 100)
        reader = out.open("rb")
        reader.close()

        with pytest.raises(ValueError):
            _check_output_disk_size(str(out), None, reader, None)

    def test_a_non_oserror_from_fileno_propagates(self):
        with pytest.raises(ValueError):
            _check_output_disk_size(None, None, _ValueErrorFileno(), None)

    def test_a_broken_stderr_reader_propagates_too(self, tmp_path):
        out = _write(tmp_path / "out.bin", 100)
        err = _write(tmp_path / "err.bin", 30)
        reader = err.open("rb")
        reader.close()

        with pytest.raises(ValueError):
            _check_output_disk_size(str(out), None, None, reader)


class TestDiskCapContext:
    """The returned number is compared against the module cap."""

    def test_the_cap_is_a_positive_byte_count(self):
        assert isinstance(_SHELL_MAX_DISK_BYTES, int)
        assert _SHELL_MAX_DISK_BYTES > 0

    def test_output_over_the_cap_is_reported_verbatim(self, tmp_path):
        """The poll loop compares with ``>``, so the size must not be
        clamped, rounded or otherwise lossy."""
        over = _write(tmp_path / "over.bin", _SHELL_MAX_DISK_BYTES + 1)

        total = _check_output_disk_size(str(over), None, None, None)

        assert total > _SHELL_MAX_DISK_BYTES
        assert total == _SHELL_MAX_DISK_BYTES + 1

    def test_output_exactly_at_the_cap_is_not_over(self, tmp_path):
        at_cap = _write(tmp_path / "at_cap.bin", _SHELL_MAX_DISK_BYTES)

        total = _check_output_disk_size(str(at_cap), None, None, None)

        assert total == _SHELL_MAX_DISK_BYTES
        assert total <= _SHELL_MAX_DISK_BYTES

    def test_both_streams_can_jointly_exceed_the_cap(self, tmp_path):
        half = _SHELL_MAX_DISK_BYTES // 2 + 1
        out = _write(tmp_path / "out.bin", half)
        err = _write(tmp_path / "err.bin", half)

        total = _check_output_disk_size(str(out), str(err), None, None)

        assert total > _SHELL_MAX_DISK_BYTES
