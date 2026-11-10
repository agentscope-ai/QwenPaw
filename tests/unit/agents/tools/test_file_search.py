# -*- coding: utf-8 -*-
"""Tests for file_search module — _is_text_file and _walk_and_grep."""

# pylint: disable=protected-access,redefined-outer-name,reimported
import io
import os
import re
import tempfile
import threading
from pathlib import Path

import pytest

from qwenpaw.agents.tools.file_search import (
    _compile_search_pattern,
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
# _compile_search_pattern tests
# ---------------------------------------------------------------------------


def test_compile_search_pattern_literal():
    regex = _compile_search_pattern("hello", is_regex=False, flags=0)
    assert regex.search("hello world")
    assert not regex.search("hi world")


def test_compile_search_pattern_pipe_alternatives():
    pattern = "keyword_a|keyword_b|keyword_c|keyword_d|keyword_e"
    regex = _compile_search_pattern(pattern, is_regex=False, flags=0)
    assert regex.search("the item remains keyword_d")
    assert regex.search("field keyword_c is set")
    assert not regex.search("completely unrelated content")


def test_compile_search_pattern_pipe_only():
    regex = _compile_search_pattern("||", is_regex=False, flags=0)
    assert not regex.search("any line")
    assert regex.search("a||b")

    single = _compile_search_pattern("|", is_regex=False, flags=0)
    assert single.search("a|b")
    assert not single.search("any line")


def test_compile_search_pattern_pipe_preserves_regex_metacharacters():
    regex = _compile_search_pattern("a.b|c.d", is_regex=False, flags=0)
    assert regex.search("a.b")
    assert regex.search("c.d")
    assert not regex.search("axb")


def test_compile_search_pattern_regex_mode():
    regex = _compile_search_pattern(r"foo|bar", is_regex=True, flags=0)
    assert regex.search("foo")
    assert regex.search("bar")


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
    assert status == f"truncated: output size limit (~{_MAX_OUTPUT_CHARS // 1000}KB)"


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
        # Root user bypasses file permission checks, so os.chmod(0o000)
        # does not make the file unreadable when running as root.
        # Skip this test in that environment.
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            import pytest

            pytest.skip("root user bypasses file permission checks")
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
        assert len(line_entries) == 1, f"line {i} appears {len(line_entries)} times"
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


def test_walk_and_grep_pipe_alternatives_literal(temp_dir):
    """Pipe-separated literals should match any alternative."""
    (temp_dir / "file.txt").write_text(
        "the item remains keyword_d\nfield keyword_c is set\n",
        encoding="utf-8",
    )
    pattern = "keyword_a|keyword_b|keyword_d|keyword_c"
    regex = _compile_search_pattern(pattern, is_regex=False, flags=0)
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert len(matches) == 2


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


def test_walk_and_grep_show_file_default_unchanged(temp_dir):
    """Default show_file=True keeps the existing per-line path format."""
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
    assert matches == ["file.txt:2:> line two"]


def test_walk_and_grep_show_file_false_single_file(temp_dir):
    """show_file=False on a single file omits path prefix and headers."""
    (temp_dir / "file.txt").write_text("line one\nline two\nline three\n")
    regex = re.compile(r"two")
    matches, status = _walk_and_grep(
        temp_dir / "file.txt",
        regex,
        0,
        FakeCancel(),
        None,
        show_file=False,
    )
    assert status == "ok"
    assert matches == ["2:> line two"]


def test_walk_and_grep_show_file_false_multi_file(temp_dir):
    """show_file=False groups multi-file results with one header per file."""
    (temp_dir / "a.txt").write_text("match_a\n")
    (temp_dir / "b.txt").write_text("match_b\n")
    regex = re.compile(r"match_")
    matches, status = _walk_and_grep(
        temp_dir,
        regex,
        0,
        FakeCancel(),
        None,
        show_file=False,
    )
    assert status == "ok"
    assert matches == [
        "a.txt",
        "1:> match_a",
        "---",
        "b.txt",
        "1:> match_b",
    ]


def test_walk_and_grep_show_file_false_with_context(temp_dir):
    """show_file=False with context uses --- within and between file groups."""
    (temp_dir / "a.txt").write_text(
        "line zero\nline one\nline two HIT\nline three\nline four\n",
    )
    (temp_dir / "b.txt").write_text("aaa\nbbb HIT\nccc\n")
    regex = re.compile(r"HIT")
    matches, status = _walk_and_grep(
        temp_dir,
        regex,
        2,
        FakeCancel(),
        None,
        show_file=False,
    )
    assert status == "ok"
    assert matches == [
        "a.txt",
        "1:  line zero",
        "2:  line one",
        "3:> line two HIT",
        "4:  line three",
        "5:  line four",
        "---",
        "b.txt",
        "1:  aaa",
        "2:> bbb HIT",
        "3:  ccc",
        "---",
    ]


def test_walk_and_grep_matches_gbk_file(temp_dir):
    """GBK/CP936 files must remain searchable for Chinese queries."""
    target = temp_dir / "note.txt"
    target.write_bytes(
        ("姓名: 张三" + chr(10) + "地址: 上海" + chr(10)).encode("gbk"),
    )

    regex = _compile_search_pattern("张三", is_regex=False, flags=0)
    matches, status = _walk_and_grep(
        temp_dir,
        regex,
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert any("张三" in m for m in matches)


def test_walk_and_grep_vertical_tab_does_not_split_lines(temp_dir):
    """Vertical tab stays inside the line, matching text-mode iteration."""
    target = temp_dir / "vt.txt"
    target.write_bytes(b"alpha\vbeta needle\n")
    matches, status = _walk_and_grep(
        target,
        re.compile(r"needle"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches == ["vt.txt:1:> alpha\vbeta needle"]


def test_walk_and_grep_single_file_over_max_size_streams_prefix(
    temp_dir,
    monkeypatch,
):
    """An explicit file past 2 MiB is searched in full, not size-capped."""
    import qwenpaw.agents.tools.file_search as fs

    target = temp_dir / "big.txt"
    # Short ASCII lines keep the match line small. The needle sits past
    # the directory cap, so a capped reader cannot see it. Repeating a
    # 4 KiB line avoids one giant bytes object.
    line = b"a" * 4095 + b"\n"
    count = (fs._MAX_FILE_SIZE // len(line)) + 1
    with open(target, "wb") as handle:
        for _ in range(count):
            handle.write(line)
        handle.write(b"needle-past-cap\n")
    assert target.stat().st_size > fs._MAX_FILE_SIZE

    regex = re.compile(r"needle-past-cap")
    dir_matches, dir_status = _walk_and_grep(
        temp_dir,
        regex,
        0,
        FakeCancel(),
        None,
    )
    assert dir_status == "ok"
    assert dir_matches == []

    read_sizes: list[int] = []
    real_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if Path(file) == target and "b" in mode:
            original = handle.read

            def tracked(size=-1, /):
                read_sizes.append(size)
                if not isinstance(size, int) or size <= 0 or size > fs._GREP_READ_CHUNK:
                    raise AssertionError(f"unbounded read size {size}")
                return original(size)

            handle.read = tracked
        return handle

    monkeypatch.setattr("builtins.open", tracking_open)
    matches, status = _walk_and_grep(
        target,
        regex,
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert any("needle-past-cap" in line for line in matches)
    assert sum(read_sizes) > fs._MAX_FILE_SIZE


def test_walk_and_grep_gbk_shuo_hello(temp_dir):
    """Valid GBK ``說 hello`` must be searchable, not CP1252 mojibake."""
    target = temp_dir / "shuo.txt"
    target.write_bytes("說 hello\n".encode("gbk"))
    matches, status = _walk_and_grep(
        target,
        re.compile("說"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("說 hello" in line for line in matches)
    assert all("Õf" not in line for line in matches)


def test_walk_and_grep_short_gbk_finds_character(temp_dir):
    """Pattern 张 matches a short GBK ``A张`` file."""
    target = temp_dir / "short-gbk.txt"
    target.write_bytes("A张".encode("gbk"))
    matches, status = _walk_and_grep(
        target,
        re.compile("张"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("张" in line for line in matches)


def test_walk_and_grep_short_cp1252_finds_accent(temp_dir):
    """Pattern Café matches a short CP1252 file."""
    target = temp_dir / "cafe.txt"
    target.write_bytes("Café".encode("cp1252"))
    matches, status = _walk_and_grep(
        target,
        re.compile("Café"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("Café" in line for line in matches)


def test_walk_and_grep_longer_gbk_finds_character(temp_dir):
    """Pattern 锘 matches GBK ``name=锘``."""
    target = temp_dir / "name.txt"
    target.write_bytes("name=锘".encode("gbk"))
    matches, status = _walk_and_grep(
        target,
        re.compile("锘"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("锘" in line for line in matches)


def test_walk_and_grep_gbk_rubu_finds_characters(temp_dir):
    """Pattern 如不 matches GBK bytes that lose to incidental CJK UTF-8."""
    target = temp_dir / "rubu.txt"
    target.write_bytes("name=如不\n".encode("gbk"))
    matches, status = _walk_and_grep(
        target,
        re.compile("如不"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("如不" in line for line in matches)


def test_walk_and_grep_gbk_qijing_finds_characters(temp_dir):
    """Pattern 其经 matches GBK bytes that lose to incidental CJK UTF-8."""
    target = temp_dir / "qijing.txt"
    target.write_bytes("name=其经\n".encode("gbk"))
    matches, status = _walk_and_grep(
        target,
        re.compile("其经"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("其经" in line for line in matches)


def test_walk_and_grep_gbk_qiao_finds_character(temp_dir):
    """Pattern 丂 matches GBK ``name=丂`` instead of lossy ``name=\ufffd@``."""
    target = temp_dir / "qiao.txt"
    target.write_bytes("name=丂".encode("gbk"))
    matches, status = _walk_and_grep(
        target,
        re.compile("丂"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("丂" in line for line in matches)
    assert all("\ufffd" not in line for line in matches)


def test_walk_and_grep_gbk_shang_finds_character(temp_dir):
    """Pattern 丄 matches GBK ``name=丄`` instead of lossy ``name=\ufffdA``."""
    target = temp_dir / "shang.txt"
    target.write_bytes("name=丄".encode("gbk"))
    matches, status = _walk_and_grep(
        target,
        re.compile("丄"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("丄" in line for line in matches)
    assert all("\ufffd" not in line for line in matches)


def test_walk_and_grep_gbk_yi_nuo_finds_characters(temp_dir):
    """Pattern 一锘 matches GBK bytes that also look like short UTF-8."""
    target = temp_dir / "yi.txt"
    target.write_bytes("name=一锘".encode("gbk"))
    matches, status = _walk_and_grep(
        target,
        re.compile("一锘"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("一锘" in line for line in matches)


def test_walk_and_grep_gbk_dang_finds_character(temp_dir):
    """Pattern 檔 matches GBK ``name=檔`` (not CP1252 mojibake)."""
    target = temp_dir / "dang.txt"
    target.write_bytes("name=檔".encode("gbk"))
    matches, status = _walk_and_grep(
        target,
        re.compile("檔"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("檔" in line for line in matches)


def test_walk_and_grep_longer_cp1252_finds_accent(temp_dir):
    """Pattern Café matches a CP1252 file that is not also valid GBK."""
    target = temp_dir / "cafes.txt"
    target.write_bytes("Café au lait".encode("cp1252"))
    matches, status = _walk_and_grep(
        target,
        re.compile("Café"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert any("Café au lait" in line for line in matches)


def test_walk_and_grep_gbk_letter_trails_prefer_gbk(temp_dir):
    """Letter-trail GBK with no unpaired ASCII is searchable as GBK."""
    target = temp_dir / "pairs.txt"
    target.write_bytes(bytes.fromhex("99748c48"))
    regex = re.compile("\u6a9b")
    for root in (target, temp_dir):
        matches, status = _walk_and_grep(
            root,
            regex,
            0,
            FakeCancel(),
            None,
        )
        assert status == "ok", root
        assert matches
        assert any("\u6a9b" in line and "\u5b52" in line for line in matches)
        assert all("\u2122" not in line for line in matches)


def test_walk_and_grep_bom_and_dirty_byte_strips_bom(temp_dir):
    """A BOM plus one invalid byte stays searchable without U+FEFF."""
    target = temp_dir / "bom.txt"
    target.write_bytes(b"\xef\xbb\xbfhello\xff\n")
    matches, status = _walk_and_grep(
        target,
        re.compile("hello"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert all("hello" in line for line in matches)
    assert all("\ufeff" not in line for line in matches)


def test_walk_and_grep_dirty_utf8_does_not_use_replacement(temp_dir):
    """Dirty UTF-8 is searched on the strict ladder, without U+FFFD."""
    target = temp_dir / "nihao.txt"
    raw = "你好世界\n".encode("utf-8") + b"\xff"
    target.write_bytes(raw)
    from qwenpaw.agents.utils.file_handling import decode_text_bytes

    decoded = decode_text_bytes(raw).text
    matches, status = _walk_and_grep(
        target,
        re.compile("你好世界"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    # The Chinese query may not match a latin-1/cp1252 fallback,
    # but the stream must not invent U+FFFD.
    assert all("\ufffd" not in line for line in matches)
    assert "\ufffd" not in decoded


def test_walk_and_grep_streams_bounded_reads_and_keeps_gbk(
    temp_dir,
    monkeypatch,
):
    """In-limit files are read in chunks, including GBK, not via one read()."""
    target = temp_dir / "note.txt"
    payload = ("姓名: 张三\n".encode("gbk")) * 40
    target.write_bytes(payload)
    import qwenpaw.agents.tools.file_search as fs

    monkeypatch.setattr(fs, "_GREP_READ_CHUNK", 16)
    read_sizes: list[int] = []
    real_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if Path(file) == target:
            original = handle.read

            def tracked(size=-1, /):
                if not isinstance(size, int) or size <= 0 or size > 16:
                    raise AssertionError(f"unbounded read size {size}")
                data = original(size)
                read_sizes.append(len(data))
                return data

            handle.read = tracked
        return handle

    monkeypatch.setattr("builtins.open", tracking_open)
    matches, status = _walk_and_grep(
        temp_dir,
        re.compile("张三"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert matches
    assert all("张三" in line for line in matches)
    assert read_sizes
    assert all(0 < size <= 16 for size in read_sizes)
    # Directory scans decode the capped prefix from one read.
    assert sum(read_sizes) == len(payload)


def test_walk_and_grep_directory_reads_each_file_once(temp_dir, monkeypatch):
    """A directory scan must not re-read a file to pick its encoding."""
    import qwenpaw.agents.tools.file_search as fs

    utf8 = temp_dir / "utf8.txt"
    gbk = temp_dir / "gbk.txt"
    utf8_payload = b"needle-utf8\nsecond\n"
    gbk_payload = "姓名: 张三\n".encode("gbk")
    utf8.write_bytes(utf8_payload)
    gbk.write_bytes(gbk_payload)
    monkeypatch.setattr(fs, "_GREP_READ_CHUNK", 5)
    reads: dict[Path, list[int]] = {utf8: [], gbk: []}
    opens: dict[Path, int] = {utf8: 0, gbk: 0}
    real_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        path = Path(file)
        if path in reads and "b" in mode:
            opens[path] += 1
            original = handle.read

            def tracked(size=-1, /):
                if not isinstance(size, int) or size <= 0 or size > 5:
                    raise AssertionError(f"unbounded read size {size}")
                data = original(size)
                reads[path].append(len(data))
                return data

            handle.read = tracked
        return handle

    monkeypatch.setattr("builtins.open", tracking_open)
    matches, status = _walk_and_grep(
        temp_dir,
        re.compile("needle|张三"),
        0,
        FakeCancel(),
        None,
    )
    assert status == "ok"
    assert any("needle-utf8" in line for line in matches)
    assert any("张三" in line for line in matches)
    assert opens == {utf8: 1, gbk: 1}
    assert sum(reads[utf8]) == len(utf8_payload)
    assert sum(reads[gbk]) == len(gbk_payload)


def test_walk_and_grep_cancel_during_single_file_read(temp_dir, monkeypatch):
    """Cancel stops a single-file read before the rest is loaded."""
    target = temp_dir / "wide.txt"
    payload = b"needle\n" * 80
    target.write_bytes(payload)
    import qwenpaw.agents.tools.file_search as fs

    monkeypatch.setattr(fs, "_GREP_READ_CHUNK", 8)
    cancel = threading.Event()
    read_sizes: list[int] = []
    real_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if Path(file) == target:
            original = handle.read

            def tracked(size=-1, /):
                read_sizes.append(size)
                data = original(size)
                cancel.set()
                return data

            handle.read = tracked
        return handle

    monkeypatch.setattr("builtins.open", tracking_open)
    _matches, status = _walk_and_grep(
        target,
        re.compile(r"needle"),
        0,
        cancel,
        None,
    )
    assert status == "timeout"
    assert read_sizes
    assert sum(read_sizes) < len(payload)


def test_walk_and_grep_cancel_during_directory_snapshot(
    temp_dir,
    monkeypatch,
):
    """Cancel stops a capped directory read before the rest is loaded."""
    target = temp_dir / "wide.txt"
    payload = b"needle\n" * 80
    target.write_bytes(payload)
    import qwenpaw.agents.tools.file_search as fs

    monkeypatch.setattr(fs, "_GREP_READ_CHUNK", 8)
    cancel = threading.Event()
    read_sizes: list[int] = []
    real_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if Path(file) == target:
            original = handle.read

            def tracked(size=-1, /):
                read_sizes.append(size)
                data = original(size)
                cancel.set()
                return data

            handle.read = tracked
        return handle

    monkeypatch.setattr("builtins.open", tracking_open)
    _matches, status = _walk_and_grep(
        temp_dir,
        re.compile(r"needle"),
        0,
        cancel,
        None,
    )
    assert status == "timeout"
    assert read_sizes
    assert sum(read_sizes) < len(payload)


def test_iter_grep_lines_matches_normalized_newlines(temp_dir, monkeypatch):
    """Chunked decoding matches a full decode split only on ``\\n``."""
    import qwenpaw.agents.tools.file_search as fs
    from qwenpaw.agents.utils.file_handling import (
        decode_text_bytes_with_encoding_fallback,
    )

    monkeypatch.setattr(fs, "_GREP_READ_CHUNK", 3)
    samples = [
        b"a\r\nb\nc",
        b"a\rb\r\nc\n",
        b"foo\vbar\f baz\n",
        "a\u2028b needle\n".encode("utf-8"),
        "姓名: 张三\r\n下一行\n".encode("gbk"),
        b"\xef\xbb\xbfhello\r\nworld",
        "name=锘".encode("gbk"),
        "Cafés".encode("cp1252"),
        "Cafés au lait".encode("cp1252"),
        bytes.fromhex("99748c48"),
        b"\xef\xbb\xbfhello\xff",
        "你好世界\n".encode("utf-8") + b"\xff",
        "姓名: 张三\n".encode("utf-8") + b"\xff",
        b"hello\x81world",
        b"only",
        b"\n",
        b"\r\n",
        b"",
    ]
    for index, data in enumerate(samples):
        path = temp_dir / f"sample-{index}.txt"
        path.write_bytes(data)
        expected = list(
            io.StringIO(decode_text_bytes_with_encoding_fallback(data)),
        )
        got = list(fs._iter_grep_lines(path, FakeCancel()))
        assert got == expected, data
        # Explicit single-file searches stream with no byte cap.
        got_full = list(fs._iter_grep_lines(path, FakeCancel(), None))
        assert got_full == expected, data


@pytest.mark.parametrize("data", [b"\xef", b"\xef\xbb"])
def test_iter_grep_lines_incomplete_bom_matches_shared_helper(
    temp_dir,
    monkeypatch,
    data,
):
    """Incomplete UTF-8 BOM bytes must not disappear under utf-8-sig."""
    import qwenpaw.agents.tools.file_search as fs
    from qwenpaw.agents.utils.file_handling import (
        decode_text_bytes_with_encoding_fallback,
    )

    monkeypatch.setattr(fs, "_GREP_READ_CHUNK", 1)
    path = temp_dir / "bom.txt"
    path.write_bytes(data)
    expected = list(
        io.StringIO(decode_text_bytes_with_encoding_fallback(data)),
    )
    assert expected
    got = list(fs._iter_grep_lines(path, FakeCancel()))
    assert got == expected
    got_full = list(fs._iter_grep_lines(path, FakeCancel(), None))
    assert got_full == expected


def test_iter_grep_lines_capped_gbk_keeps_character_prefix(
    temp_dir,
    monkeypatch,
):
    """A size cap inside a GBK character drops the cut byte and still yields."""
    import qwenpaw.agents.tools.file_search as fs

    raw = "姓名: 张三".encode("gbk")
    path = temp_dir / "gbk-cut.txt"
    path.write_bytes(raw + b"TAIL")
    monkeypatch.setattr(fs, "_MAX_FILE_SIZE", len(raw) - 1)

    got = list(fs._iter_grep_lines(path, FakeCancel()))

    assert got == ["姓名: 张"]


@pytest.mark.parametrize(
    ("payload", "expected", "expect_fallback"),
    [
        pytest.param(
            "hello 张三\n".encode("utf-8"),
            ("utf-8", False),
            False,
            id="utf8",
        ),
        pytest.param(
            b"\xef\xbb\xbf" + "hello 张三\n".encode("utf-8"),
            ("utf-8-sig", False),
            False,
            id="utf8-bom",
        ),
        pytest.param(b"", ("utf-8", False), False, id="empty"),
        pytest.param(
            "A张".encode("gbk"),
            ("gbk", False),
            True,
            id="short-gbk",
        ),
        pytest.param(
            bytes.fromhex("99748c48"),
            ("gbk", False),
            True,
            id="gbk-letter-trails",
        ),
        pytest.param(
            "Café".encode("cp1252"),
            ("cp1252", False),
            True,
            id="cafe",
        ),
        pytest.param(
            "Café au lait".encode("cp1252"),
            ("cp1252", False),
            True,
            id="cafes",
        ),
        pytest.param(
            "name=锘".encode("gbk"),
            ("gbk", False),
            True,
            id="longer-gbk",
        ),
        pytest.param(
            "姓名: 张三\n".encode("utf-8") + b"\xff",
            ("latin-1", False),
            True,
            id="mostly-utf8-dirty",
        ),
        pytest.param(
            b"\xef\xbb\xbfhello\xff",
            ("cp1252", False),
            True,
            id="bom-dirty",
        ),
        pytest.param(
            b"hello\x81world",
            ("gbk", False),
            True,
            id="dirty-lead",
        ),
    ],
)
def test_select_grep_decoding_skips_legacy_probes_for_utf8(
    temp_dir,
    monkeypatch,
    payload,
    expected,
    expect_fallback,
):
    """Strict UTF-8 must not run the legacy GBK/CP1252 probe pass."""
    import qwenpaw.agents.tools.file_search as fs

    path = temp_dir / "sample.txt"
    path.write_bytes(payload)
    monkeypatch.setattr(fs, "_GREP_READ_CHUNK", 1)
    probed: list[str] = []
    real_probe = fs._GrepStrictProbe

    class _RecordingProbe(real_probe):
        """Record which encodings were constructed."""

        def __init__(self, encoding: str) -> None:
            probed.append(encoding)
            super().__init__(encoding)

    monkeypatch.setattr(fs, "_GrepStrictProbe", _RecordingProbe)

    assert fs._select_grep_decoding(path, FakeCancel(), None) == expected
    if expect_fallback:
        assert "gbk" in probed
        assert "cp1252" in probed
        return
    assert probed == ["utf-8-sig", "utf-8"]


def test_split_normalized_text_only_scans_new_chunk():
    """Pending pieces stay in a list until a newline arrives in the new chunk."""
    import qwenpaw.agents.tools.file_search as fs

    lines, pending = fs._split_normalized_text([], "ab")
    assert lines == []
    assert pending == ["ab"]
    lines, pending = fs._split_normalized_text(pending, "cd\nef\nxy")
    assert lines == ["abcd\n", "ef\n"]
    assert pending == ["xy"]
    lines, pending = fs._split_normalized_text(pending, "")
    assert lines == []
    assert pending == ["xy"]
    lines, pending = fs._split_normalized_text(pending, "z\n")
    assert lines == ["xyz\n"]
    assert pending == []


def test_split_normalized_text_long_line_is_linear(temp_dir):
    """An 8 MiB line split across chunks must stay linear and correct."""
    import time
    import qwenpaw.agents.tools.file_search as fs

    chunk = "a" * (64 * 1024)
    chunks = 128  # 8 MiB
    pending: list[str] = []
    started = time.monotonic()
    for _ in range(chunks):
        lines, pending = fs._split_normalized_text(pending, chunk)
        assert lines == []
    lines, pending = fs._split_normalized_text(pending, "\n")
    elapsed = time.monotonic() - started
    assert lines == ["a" * (64 * 1024 * chunks) + "\n"]
    assert pending == []
    assert elapsed < 1.0


def test_iter_grep_lines_long_line_matches_full_buffer(temp_dir):
    """A long single-file line must match a full-buffer decode split."""
    import qwenpaw.agents.tools.file_search as fs
    from qwenpaw.agents.utils.file_handling import (
        decode_text_bytes_with_encoding_fallback,
    )

    path = temp_dir / "long.txt"
    payload = ("b" * (2 * 1024 * 1024)) + "\nneedle\n"
    path.write_text(payload, encoding="utf-8")
    got = list(fs._iter_grep_lines(path, FakeCancel(), None))
    expected = []
    lines, pending = fs._split_normalized_text(
        [],
        decode_text_bytes_with_encoding_fallback(path.read_bytes()),
    )
    expected.extend(lines)
    if pending:
        expected.append("".join(pending))
    assert got == expected
