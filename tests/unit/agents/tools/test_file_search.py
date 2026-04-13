# -*- coding: utf-8 -*-
"""Tests for file_search module — _is_text_file and _walk_and_grep."""

# pylint: disable=redefined-outer-name,protected-access
import os
import re
import tempfile
import threading
from pathlib import Path

import pytest

from qwenpaw.agents.tools.file_search import (
    _is_text_file,
    _MAX_MATCHES,
    _MAX_OUTPUT_CHARS,
    _walk_and_grep,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dir():
    """Create a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


class FakeCancel:
    """Fake threading.Event that is never set."""

    def is_set(self) -> bool:
        return False


class FakeCancelAfter(FakeCancel):
    """Fake cancel that triggers after N is_set() checks."""

    def __init__(self, after: int):
        self.after = after
        self._checks = 0

    def is_set(self) -> bool:
        self._checks += 1
        return self._checks > self.after


# ---------------------------------------------------------------------------
# _is_text_file tests
# ---------------------------------------------------------------------------


def test_is_text_file_known_binary(temp_dir):
    (temp_dir / "test.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert _is_text_file(temp_dir / "test.png") is False


def test_is_text_file_python_source(temp_dir):
    (temp_dir / "test.py").write_text("print('hello')")
    assert _is_text_file(temp_dir / "test.py") is True


# ---------------------------------------------------------------------------
# _walk_and_grep tests
# ---------------------------------------------------------------------------


def test_walk_and_grep_single_file_match(temp_dir):
    """Test grep finds a match in a single file."""
    (temp_dir / "file.txt").write_text("line one\nline two\nline three\n")
    regex = re.compile(r"two")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert len(matches) == 1
    assert matches == ["file.txt:2:> line two"]


def test_walk_and_grep_no_match(temp_dir):
    """Test grep returns empty when nothing matches."""
    (temp_dir / "file.txt").write_text("line one\nline two\n")
    regex = re.compile(r"notfound")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert not matches


def test_walk_and_grep_context_lines_two(temp_dir):
    """Test context_lines=2 includes two lines before and after match."""
    lines = ["line zero", "line one", "line two", "line three", "line four"]
    (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
    regex = re.compile(r"two")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        2,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    # start=max(0,3-1-2)=0, end=min(5,3+2)=5 → lines 1-5
    # line 1 zero, line 2 one, line 3 two (match), line 4 three, line 5 four
    expected = [
        "file.txt:1:  line zero",
        "file.txt:2:  line one",
        "file.txt:3:> line two",
        "file.txt:4:  line three",
        "file.txt:5:  line four",
        "---",
    ]
    assert matches == expected


def test_walk_and_grep_context_lines_at_start(temp_dir):
    """Test context lines when match is at the very first line."""
    lines = ["first line match", "second line", "third line"]
    (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
    regex = re.compile(r"first")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        2,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    # start=max(0,1-1-2)=0, end=min(3,1+2)=3 → lines 1-3
    expected = [
        "file.txt:1:> first line match",
        "file.txt:2:  second line",
        "file.txt:3:  third line",
        "---",
    ]
    assert matches == expected


def test_walk_and_grep_context_lines_at_end(temp_dir):
    """Test context lines when match is at the very last line."""
    lines = ["first line", "second line", "last line match"]
    (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
    regex = re.compile(r"last")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        2,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    # start=max(0,3-1-2)=0, end=min(3,3+2)=3 → lines 1-3
    expected = [
        "file.txt:1:  first line",
        "file.txt:2:  second line",
        "file.txt:3:> last line match",
        "---",
    ]
    assert matches == expected


def test_walk_and_grep_context_lines_capped(temp_dir):
    """Test context_lines is capped at _MAX_CONTEXT_LINES."""
    lines = ["line zero", "line one", "line two", "line three", "line four"]
    (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
    regex = re.compile(r"two")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        100,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    match_line_nos = [int(m.split(":")[1]) for m in matches if ":> " in m]
    assert match_line_nos == [3]


def test_walk_and_grep_multiple_hits_same_file_overlapping_context(temp_dir):
    """Test two matches close together
    — overlapping context, no deduplication."""
    lines = ["line zero", "line one", "line two", "line three"]
    (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
    # "one" at line 2: start=max(0,2-1-2)=0, end=min(4,2+2)=4 → [1,2,3,4]
    # "two" at line 3: start=max(0,3-1-2)=0, end=min(4,3+2)=4 → [1,2,3,4]
    regex = re.compile(r"one|two")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        2,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    expected = [
        "file.txt:1:  line zero",
        "file.txt:2:> line one",
        "file.txt:3:  line two",
        "file.txt:4:  line three",
        "---",
        "file.txt:1:  line zero",
        "file.txt:2:  line one",
        "file.txt:3:> line two",
        "file.txt:4:  line three",
        "---",
    ]
    assert matches == expected


def test_walk_and_grep_two_matches_separate_files(temp_dir):
    """Test two matches in different files, each with context_lines=2."""
    (temp_dir / "a.txt").write_text("aaa\nbbb\nccc\nddd\n")
    (temp_dir / "b.txt").write_text("111\n222\n333\n444\n")
    regex = re.compile(r"bbb|222")
    matches, status = _walk_and_grep(temp_dir, regex, 2, FakeCancel(), None)
    assert status == "ok"
    # a.txt: match "bbb" @ line 2 → context lines 1-4
    # b.txt: match "222" @ line 2 → context lines 1-4
    expected = [
        "a.txt:1:  aaa",
        "a.txt:2:> bbb",
        "a.txt:3:  ccc",
        "a.txt:4:  ddd",
        "---",
        "b.txt:1:  111",
        "b.txt:2:> 222",
        "b.txt:3:  333",
        "b.txt:4:  444",
        "---",
    ]
    assert matches == expected


def test_walk_and_grep_multiple_files(temp_dir):
    """Test grep across multiple files in a directory."""
    (temp_dir / "a.txt").write_text("apple\n")
    (temp_dir / "b.txt").write_text("banana\n")
    (temp_dir / "c.txt").write_text("apple banana\n")
    regex = re.compile(r"apple")
    matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), None)
    assert status == "ok"
    assert len(matches) == 2
    rel_names = sorted(m.split(":")[0] for m in matches)
    assert rel_names == ["a.txt", "c.txt"]


def test_walk_and_grep_include_pattern(temp_dir):
    """Test include_pattern filters files by glob."""
    (temp_dir / "a.py").write_text("def foo(): pass\n")
    (temp_dir / "b.txt").write_text("def foo(): pass\n")
    (temp_dir / "c.py").write_text("def bar(): pass\n")
    regex = re.compile(r"def")
    matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), "*.py")
    assert status == "ok"
    rel_names = sorted(m.split(":")[0] for m in matches)
    assert rel_names == ["a.py", "c.py"]


def test_walk_and_grep_include_pattern_with_context(temp_dir):
    """Test include_pattern combined with context_lines=2."""
    (temp_dir / "a.py").write_text("def foo():\n    pass\n")
    (temp_dir / "b.txt").write_text("def foo():\n    pass\n")
    regex = re.compile(r"def")
    matches, status = _walk_and_grep(temp_dir, regex, 2, FakeCancel(), "*.py")
    assert status == "ok"
    rel_names = sorted(set(m.split(":")[0] for m in matches if m != "---"))
    assert rel_names == ["a.py"]


def test_walk_and_grep_skips_binary_extensions(temp_dir):
    """Test that binary files are skipped."""
    (temp_dir / "data.pdf").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    (temp_dir / "code.py").write_text("def foo(): pass\n")
    regex = re.compile(r"def")
    matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), None)
    assert status == "ok"
    rel_names = sorted(m.split(":")[0] for m in matches)
    assert rel_names == ["code.py"]


def test_walk_and_grep_skips_directories(temp_dir):
    """Test that skipped directories are not traversed."""
    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("def foo()\n")
    (temp_dir / "code.py").write_text("def bar(): pass\n")
    regex = re.compile(r"def")
    matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), None)
    assert status == "ok"
    rel_names = sorted(m.split(":")[0] for m in matches)
    assert rel_names == ["code.py"]


def test_walk_and_grep_skips_skip_dirs_nested(temp_dir):
    """Test that various skipped dirs are excluded."""
    skipped = [".git", "node_modules", "__pycache__", ".venv", "venv"]
    for name in skipped:
        d = temp_dir / name
        d.mkdir()
        (d / "secret.txt").write_text("should not appear\n")
    (temp_dir / "code.py").write_text("def bar(): pass\n")
    regex = re.compile(r"def")
    matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), None)
    assert status == "ok"
    rel_names = sorted(m.split(":")[0] for m in matches)
    assert rel_names == ["code.py"]


def test_walk_and_grep_truncated_match_limit(temp_dir):
    """Test truncation when match limit is reached."""
    for i in range(300):
        (temp_dir / f"file_{i}.txt").write_text(f"match line {i}\n")
    regex = re.compile(r"match")
    _matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), None)
    assert status == f"truncated: match limit ({_MAX_MATCHES})"


def test_walk_and_grep_truncated_output_size(temp_dir):
    """Test truncation when output size limit is reached."""
    long_line = "x" * (_MAX_OUTPUT_CHARS)
    (temp_dir / "big.txt").write_text(f"match {long_line}\n")
    regex = re.compile(r"match")
    _matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), None)
    assert (
        status
        == f"truncated: output size limit (~{_MAX_OUTPUT_CHARS // 1000}KB)"
    )


def test_walk_and_grep_cancel_event(temp_dir):
    """Test that cancel event stops iteration early."""
    for i in range(10):
        (temp_dir / f"file_{i}.py").write_text(f"def foo{i}(): pass\n" * 100)
    regex = re.compile(r"def")
    cancel = threading.Event()
    cancel.set()
    _matches, status = _walk_and_grep(temp_dir, regex, 0, cancel, None)
    assert status == "timeout"


def test_walk_and_grep_cancel_during_walk(temp_dir):
    """Test cancel event fires during os.walk (not during file read)."""
    # 100 dirs × 1 match each = 100 entries, well under 200 limit.
    # FakeCancelAfter(after=50) fires on the 51st is_set() check.
    for i in range(100):
        d = temp_dir / f"dir_{i:03d}"
        d.mkdir()
        (d / "f.py").write_text("def foo(): pass\n")
    regex = re.compile(r"def")
    cancel = FakeCancelAfter(after=50)
    _matches, status = _walk_and_grep(temp_dir, regex, 0, cancel, None)
    assert status == "timeout"


def test_walk_and_grep_single_file_mode(temp_dir):
    """Test when search_root is a file (not a directory)."""
    (temp_dir / "only.txt").write_text("line one\nline two\nline three\n")
    regex = re.compile(r"one")
    matches, status = _walk_and_grep(
        temp_dir / "only.txt",
        regex,
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert len(matches) == 1
    assert matches[0] == "only.txt:1:> line one"


def test_walk_and_grep_single_file_mode_with_context(temp_dir):
    """Test single-file mode with context_lines=2 and five hits demonstrating
    four distinct gap sizes between consecutive hits.

    File (14 lines):
      1:  '1'
      2:  '2 hit'   -- HIT 1
      3:  '3 hit'   -- HIT 2 (gap=0, adjacent to HIT 1)
      4:  '4'           (gap=1 between HIT 2 and 3: only line 4)
      5:  '5 hit'   -- HIT 3
      6:  '6'           (gap=2 between HIT 3 and 4: lines 6,7)
      7:  '7'
      8:  '8 hit'   -- HIT 4
      9:  '9'           (gap=3 between HIT 4 and 5: lines 9,10,11)
     10:  '10'
     11:  '11'
     12:  '12 hit'  -- HIT 5
     13:  '13'
     14:  '14'

    With context_lines=2, each hit shows ±2 lines clamped to [1,14]:
      HIT 1 @ line 2:  ctx → [1,4]   (lines 1-4)
      HIT 2 @ line 3:  ctx → [1,5]   (lines 1-5, adjacent to HIT 1)
      HIT 3 @ line 5:  ctx → [3,7]   (lines 3-7, 1-line gap: line 4)
      HIT 4 @ line 8:  ctx → [6,10]  (lines 6-10, 2-line gap: lines 6,7)
      HIT 5 @ line 12: ctx → [10,14] (lines 10-14, 3-line gap: lines 9,10,11)

    This produces 5 context blocks with 4 different gap sizes between them:
      gap=0 (adjacent): HIT 1 ↔ HIT 2
      gap=1:             HIT 2 ↔ HIT 3
      gap=2:             HIT 3 ↔ HIT 4
      gap=3:             HIT 4 ↔ HIT 5
    """
    lines = [
        "1",
        "2 hit",
        "3 hit",
        "4",
        "5 hit",
        "6",
        "7",
        "8 hit",
        "9",
        "10",
        "11",
        "12 hit",
        "13",
        "14",
    ]
    (temp_dir / "only.txt").write_text("\n".join(lines) + "\n")
    regex = re.compile(r"hit")
    matches, status = _walk_and_grep(
        temp_dir / "only.txt",
        regex,
        2,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    # fmt: off
    expected = [
        # HIT 1 @ line 2: ctx [1,4]
        "only.txt:1:  1",
        "only.txt:2:> 2 hit",
        "only.txt:3:  3 hit",
        "only.txt:4:  4",
        "---",
        # HIT 2 @ line 3: ctx [1,5]
        "only.txt:1:  1",
        "only.txt:2:  2 hit",
        "only.txt:3:> 3 hit",
        "only.txt:4:  4",
        "only.txt:5:  5 hit",
        "---",
        # HIT 3 @ line 5: ctx [3,7]
        "only.txt:3:  3 hit",
        "only.txt:4:  4",
        "only.txt:5:> 5 hit",
        "only.txt:6:  6",
        "only.txt:7:  7",
        "---",
        # HIT 4 @ line 8: ctx [6,10]
        "only.txt:6:  6",
        "only.txt:7:  7",
        "only.txt:8:> 8 hit",
        "only.txt:9:  9",
        "only.txt:10:  10",
        "---",
        # HIT 5 @ line 12: ctx [10,14]
        "only.txt:10:  10",
        "only.txt:11:  11",
        "only.txt:12:> 12 hit",
        "only.txt:13:  13",
        "only.txt:14:  14",
        "---",
    ]
    # fmt: on
    assert matches == expected


def test_walk_and_grep_empty_directory(temp_dir):
    """Test grep on an empty directory."""
    regex = re.compile(r"anything")
    matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), None)
    assert status == "ok"
    assert not matches


def test_walk_and_grep_file_read_error(temp_dir):
    """Test that unreadable files are skipped gracefully."""
    if os.name != "nt":
        f = temp_dir / "noperm.txt"
        f.write_text("secret\n")
        os.chmod(str(f), 0o000)
        try:
            regex = re.compile(r"secret")
            matches, status = _walk_and_grep(
                temp_dir,
                regex,
                0,
                FakeCancel(),
                None,
            )
            assert status == "ok"
            assert not matches
        finally:
            os.chmod(str(f), 0o644)


def test_walk_and_grep_file_too_large(temp_dir):
    """Test that files larger than _MAX_FILE_SIZE are skipped."""
    large = temp_dir / "large.py"
    large.write_bytes(b"def foo():\n    pass\n" * 1000)
    import qwenpaw.agents.tools.file_search as fs

    original_limit = fs._MAX_FILE_SIZE
    fs._MAX_FILE_SIZE = 10
    try:
        regex = re.compile(r"def")
        matches, status = _walk_and_grep(
            temp_dir,
            regex,
            0,
            FakeCancel(),
            None,
        )
        assert status == "ok"
        rel_names = sorted(m.split(":")[0] for m in matches)
        assert rel_names == []
    finally:
        fs._MAX_FILE_SIZE = original_limit


def test_walk_and_grep_subdirectory_files(temp_dir):
    """Test grep finds matches in nested subdirectories."""
    sub1 = temp_dir / "sub1"
    sub2 = sub1 / "sub2"
    sub2.mkdir(parents=True)
    (sub1 / "a.txt").write_text("match in sub1\n")
    (sub2 / "b.txt").write_text("match in sub2\n")
    (temp_dir / "root.txt").write_text("match in root\n")
    regex = re.compile(r"match")
    matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), None)
    assert status == "ok"
    rel_names = sorted(m.split(":")[0] for m in matches)
    assert rel_names == ["root.txt", "sub1/a.txt", "sub1/sub2/b.txt"]


def test_walk_and_grep_sorted_file_order(temp_dir):
    """Test that files are iterated in sorted order."""
    (temp_dir / "z.txt").write_text("z\n")
    (temp_dir / "a.txt").write_text("a\n")
    (temp_dir / "m.txt").write_text("m\n")
    regex = re.compile(r"[zam]")
    matches, status = _walk_and_grep(temp_dir, regex, 0, FakeCancel(), None)
    assert status == "ok"
    names = [m.split(":")[0] for m in matches]
    assert names == sorted(names)


def test_walk_and_grep_context_separator(temp_dir):
    """Test that --- separator appears between context groups."""
    lines = ["line zero", "line one", "line two", "line three", "line four"]
    (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
    regex = re.compile(r"two")
    matches, _status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        2,
        FakeCancel(),
        None,
    )
    # start=max(0,3-1-2)=0, end=min(5,3+2)=5 → lines 1-5
    expected = [
        "file.txt:1:  line zero",
        "file.txt:2:  line one",
        "file.txt:3:> line two",
        "file.txt:4:  line three",
        "file.txt:5:  line four",
        "---",
    ]
    assert matches == expected


def test_walk_and_grep_three_separate_matches_no_overlap(temp_dir):
    """Test three matches far apart
    — no overlapping context, no duplicate lines.

    With context_lines=2, adjacent matches need >= 2*context_lines+3=7 lines
    between them to avoid overlap.

    Match 1 @ line 1:  context → [1,3]
    Match 2 @ line 7:  context → [5,9]
    Match 3 @ line 13: context → [11,13]
    Gap lines 4 and 10 never appear.
    """
    lines = [
        "line 1 match",
        "line 2",
        "line 3",
        "line 4",
        "line 5",
        "line 6",
        "line 7 match",
        "line 8",
        "line 9",
        "line 10",
        "line 11",
        "line 12",
        "line 13 match",
    ]
    (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
    regex = re.compile(r"match")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        2,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    # Covered by match 1: [1,3], by match 2: [5,9], by match 3: [11,13]
    covered = set(range(1, 4)) | set(range(5, 10)) | set(range(11, 14))
    gap = set(range(1, 14)) - covered  # {4, 10}
    # Check each covered line appears exactly once
    for i in covered:
        line_entries = [m for m in matches if m.startswith(f"file.txt:{i}:")]
        assert (
            len(line_entries) == 1
        ), f"line {i} appears {len(line_entries)} times"
    # Check gap lines do not appear
    for i in gap:
        line_entries = [m for m in matches if m.startswith(f"file.txt:{i}:")]
        assert len(line_entries) == 0


def test_walk_and_grep_context_line_at_file_start_edge(temp_dir):
    """Match on line 2 with context=2 at file start — verifies start clamp."""
    lines = ["first", "second match", "third", "fourth"]
    (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
    regex = re.compile(r"second")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        2,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    # start=max(0,2-1-2)=0, end=min(4,2+2)=4 → lines 1-4
    expected = [
        "file.txt:1:  first",
        "file.txt:2:> second match",
        "file.txt:3:  third",
        "file.txt:4:  fourth",
        "---",
    ]
    assert matches == expected


def test_walk_and_grep_context_line_at_file_end_edge(temp_dir):
    """Match on line 4 with context=2 at file end — verifies end clamp."""
    lines = ["first", "second", "third", "fourth last_match"]
    (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
    regex = re.compile(r"last_match")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        2,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    # start=max(0,4-1-2)=1, end=min(4,4+2)=4 → lines 2,3,4 (index 1,2,3)
    expected = [
        "file.txt:2:  second",
        "file.txt:3:  third",
        "file.txt:4:> fourth last_match",
        "---",
    ]
    assert matches == expected


def test_walk_and_grep_regex_metacharacters(temp_dir):
    """Test regex metacharacters in pattern are handled correctly."""
    (temp_dir / "file.txt").write_text("a.b\nc\\d\ne*f\n")
    regex = re.compile(r"a\.b|c\\d|e\*f")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert len(matches) == 3
    assert matches == [
        "file.txt:1:> a.b",
        "file.txt:2:> c\\d",
        "file.txt:3:> e*f",
    ]


def test_walk_and_grep_first_match_exceeds_output_limit(temp_dir):
    """Test when first match line exceeds _MAX_OUTPUT_CHARS with more lines."""
    import qwenpaw.agents.tools.file_search as fs

    original_limit = fs._MAX_OUTPUT_CHARS
    # Set limit low enough that first match exceeds it
    fs._MAX_OUTPUT_CHARS = 30
    try:
        lines = [
            "first line with match keyword here",
            "second line",
            "third line also has match",
            "fourth line",
        ]
        (temp_dir / "file.txt").write_text("\n".join(lines) + "\n")
        regex = re.compile(r"match")
        matches, status = _walk_and_grep(
            temp_dir / "file.txt",
            regex,
            0,
            FakeCancel(),
            None,
        )
        assert status.startswith("truncated:"), (
            f"Expected truncated status when first match exceeds limit, "
            f"got status='{status}', matches={matches}"
        )
        assert len(matches) == 0
    finally:
        fs._MAX_OUTPUT_CHARS = original_limit
