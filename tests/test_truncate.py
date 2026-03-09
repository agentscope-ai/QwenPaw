# -*- coding: utf-8 -*-
"""Unit tests for Shell and FileIO truncation."""
# pylint: disable=redefined-outer-name

import asyncio
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from copaw.agents.tools import file_io, shell
from copaw.agents.tools.utils import DEFAULT_MAX_LINES, DEFAULT_MAX_BYTES


# ============ Shell Truncation Tests ============


@pytest.fixture(scope="module")
def shell_test_dir():
    """Create temporary directory for shell tests."""
    test_dir = tempfile.mkdtemp(prefix="test_shell_truncate_")
    yield Path(test_dir)
    shutil.rmtree(test_dir, ignore_errors=True)


def test_shell_normal_output(shell_test_dir):
    """Test normal shell command output without truncation."""
    result = asyncio.run(
        shell.execute_shell_command("echo hello", cwd=shell_test_dir),
    )
    text = result.content[0].get("text", "")
    assert "hello" in text
    assert "truncated" not in text.lower()


def test_shell_multiline_output(shell_test_dir):
    """Test multiline output without truncation."""
    result = asyncio.run(
        shell.execute_shell_command("seq 1 10", cwd=shell_test_dir),
    )
    text = result.content[0].get("text", "")
    assert "1" in text
    assert "10" in text
    assert "truncated" not in text.lower()


def test_shell_truncated_by_lines(shell_test_dir):
    """Test shell output truncation by line limit."""
    lines_to_generate = DEFAULT_MAX_LINES + 500
    cmd = f"seq 1 {lines_to_generate}"
    result = asyncio.run(shell.execute_shell_command(cmd, cwd=shell_test_dir))
    text = result.content[0].get("text", "")

    # Should contain truncation notice
    assert "truncated" in text.lower()
    # Should contain the last line (tail is kept for shell output)
    assert str(lines_to_generate) in text
    # Verify first numeric line is > 1 (head was truncated)
    numeric_lines = [
        line for line in text.strip().split("\n") if line.isdigit()
    ]
    if numeric_lines:
        assert int(numeric_lines[0]) > 1


def test_shell_truncated_by_bytes(shell_test_dir):
    """Test shell output truncation by byte limit."""
    # Generate output exceeding DEFAULT_MAX_BYTES (30KB)
    # Each line is ~100 chars, need ~350 lines for 35KB
    lines_needed = (DEFAULT_MAX_BYTES // 100) + 100
    cmd = f"seq 1 {lines_needed} | xargs -I{{}} printf '%.0s=' {{1..100}}"
    # Simpler approach: use yes command with timeout
    cmd = f"yes {'x' * 100} | head -n {lines_needed}"
    result = asyncio.run(shell.execute_shell_command(cmd, cwd=shell_test_dir))
    text = result.content[0].get("text", "")

    # Should have truncation notice with KB mention
    assert "truncated" in text.lower() or "KB" in text


def test_shell_command_failure(shell_test_dir):
    """Test failed command returns error without truncation issue."""
    result = asyncio.run(
        shell.execute_shell_command("exit 1", cwd=shell_test_dir),
    )
    text = result.content[0].get("text", "")
    assert "failed" in text.lower()
    assert "exit code" in text.lower()


def test_shell_timeout(shell_test_dir):
    """Test command timeout handling."""
    result = asyncio.run(
        shell.execute_shell_command("sleep 10", timeout=1, cwd=shell_test_dir),
    )
    text = result.content[0].get("text", "")
    assert "timeout" in text.lower()


# ============ FileIO Truncation Tests ============


@pytest.fixture
def fileio_test_dir():
    """Create temporary directory with test files for file_io tests."""
    test_dir = tempfile.mkdtemp(prefix="test_fileio_truncate_")
    test_path = Path(test_dir)

    # Create simple test file
    simple_file = test_path / "simple.txt"
    simple_file.write_text(
        "line1\nline2\nline3\nline4\nline5",
        encoding="utf-8",
    )

    # Create large file (exceeds DEFAULT_MAX_LINES)
    large_file = test_path / "large.txt"
    with open(large_file, "w", encoding="utf-8") as f:
        for i in range(1, DEFAULT_MAX_LINES + 500):
            f.write(f"line {i}\n")

    # Create large bytes file (exceeds DEFAULT_MAX_BYTES ~30KB)
    large_bytes_file = test_path / "large_bytes.txt"
    with open(large_bytes_file, "w", encoding="utf-8") as f:
        content = "x" * 100 + "\n"  # ~101 bytes per line
        lines_needed = (DEFAULT_MAX_BYTES // 101) + 100
        for _ in range(lines_needed):
            f.write(content)

    yield {
        "dir": test_path,
        "simple_file": simple_file,
        "large_file": large_file,
        "large_bytes_file": large_bytes_file,
    }
    shutil.rmtree(test_dir, ignore_errors=True)


def test_read_file_normal(fileio_test_dir):
    """Test normal file reading without truncation."""
    with mock.patch.object(file_io, "WORKING_DIR", fileio_test_dir["dir"]):
        result = asyncio.run(file_io.read_file("simple.txt"))
    text = result.content[0].get("text", "")
    assert "line1" in text
    assert "line5" in text


def test_read_file_absolute_path(fileio_test_dir):
    """Test reading file with absolute path."""
    result = asyncio.run(
        file_io.read_file(str(fileio_test_dir["simple_file"])),
    )
    text = result.content[0].get("text", "")
    assert "line1" in text
    assert "line5" in text


def test_read_file_with_line_range(fileio_test_dir):
    """Test reading specific line range."""
    result = asyncio.run(
        file_io.read_file(
            str(fileio_test_dir["simple_file"]),
            start_line=2,
            end_line=4,
        ),
    )
    text = result.content[0].get("text", "")
    assert "line2" in text
    assert "line4" in text
    assert "lines 2-4" in text.lower()


def test_read_file_truncated_by_lines(fileio_test_dir):
    """Test file truncation by line limit."""
    result = asyncio.run(file_io.read_file(str(fileio_test_dir["large_file"])))
    text = result.content[0].get("text", "")

    # Should contain first line (head is kept for file reading)
    assert "line 1" in text
    # Should have truncation hint
    assert "continue" in text.lower()


def test_read_file_truncated_by_bytes(fileio_test_dir):
    """Test file truncation by byte limit."""
    result = asyncio.run(
        file_io.read_file(str(fileio_test_dir["large_bytes_file"])),
    )
    text = result.content[0].get("text", "")

    # Should have truncation hint
    assert "continue" in text.lower() or "KB" in text


def test_read_file_not_exists():
    """Test reading non-existent file."""
    result = asyncio.run(file_io.read_file("/nonexistent/path/file.txt"))
    text = result.content[0].get("text", "")
    assert "Error" in text
    assert "does not exist" in text


def test_read_file_is_directory(fileio_test_dir):
    """Test reading a directory returns error."""
    result = asyncio.run(file_io.read_file(str(fileio_test_dir["dir"])))
    text = result.content[0].get("text", "")
    assert "Error" in text
    assert "not a file" in text


def test_read_file_start_line_exceeds(fileio_test_dir):
    """Test start_line exceeding file length."""
    result = asyncio.run(
        file_io.read_file(str(fileio_test_dir["simple_file"]), start_line=100),
    )
    text = result.content[0].get("text", "")
    assert "Error" in text
    assert "exceeds" in text


def test_read_file_invalid_range(fileio_test_dir):
    """Test invalid line range (start > end)."""
    result = asyncio.run(
        file_io.read_file(
            str(fileio_test_dir["simple_file"]),
            start_line=4,
            end_line=2,
        ),
    )
    text = result.content[0].get("text", "")
    assert "Error" in text


# ============ Write/Edit Tests ============


@pytest.fixture
def write_test_dir():
    """Create temporary directory for write tests."""
    test_dir = tempfile.mkdtemp(prefix="test_write_")
    yield Path(test_dir)
    shutil.rmtree(test_dir, ignore_errors=True)


def test_write_file_new(write_test_dir):
    """Test writing a new file."""
    file_path = write_test_dir / "new_file.txt"
    result = asyncio.run(file_io.write_file(str(file_path), "test content"))
    text = result.content[0].get("text", "")
    assert "Wrote" in text
    assert file_path.read_text(encoding="utf-8") == "test content"


def test_write_file_overwrite(write_test_dir):
    """Test overwriting existing file."""
    file_path = write_test_dir / "overwrite.txt"
    file_path.write_text("old content", encoding="utf-8")

    result = asyncio.run(file_io.write_file(str(file_path), "new content"))
    text = result.content[0].get("text", "")
    assert "Wrote" in text
    assert file_path.read_text(encoding="utf-8") == "new content"


def test_write_file_empty_path():
    """Test writing with empty path."""
    result = asyncio.run(file_io.write_file("", "content"))
    text = result.content[0].get("text", "")
    assert "Error" in text


def test_edit_file_replace(write_test_dir):
    """Test replacing text in file."""
    file_path = write_test_dir / "edit_test.txt"
    file_path.write_text("Hello World\nHello Again", encoding="utf-8")

    result = asyncio.run(file_io.edit_file(str(file_path), "Hello", "Hi"))
    text = result.content[0].get("text", "")
    assert "Successfully" in text

    content = file_path.read_text(encoding="utf-8")
    assert "Hello" not in content
    assert "Hi World" in content
    assert "Hi Again" in content


def test_edit_file_text_not_found(write_test_dir):
    """Test editing when text not found."""
    file_path = write_test_dir / "edit_test2.txt"
    file_path.write_text("Some content", encoding="utf-8")

    result = asyncio.run(file_io.edit_file(str(file_path), "NotExists", "New"))
    text = result.content[0].get("text", "")
    assert "Error" in text
    assert "not found" in text


def test_append_file(write_test_dir):
    """Test appending content to file."""
    file_path = write_test_dir / "append_test.txt"
    file_path.write_text("original", encoding="utf-8")

    result = asyncio.run(file_io.append_file(str(file_path), " appended"))
    text = result.content[0].get("text", "")
    assert "Appended" in text
    assert file_path.read_text(encoding="utf-8") == "original appended"


def test_append_file_empty_path():
    """Test appending with empty path."""
    result = asyncio.run(file_io.append_file("", "content"))
    text = result.content[0].get("text", "")
    assert "Error" in text
