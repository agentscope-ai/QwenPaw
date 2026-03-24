# -*- coding: utf-8 -*-
"""Unit tests for cloud-aware file search tools (grep_search, glob_search)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from copaw.agents.tools.file_search import grep_search, glob_search


def _get_text(resp) -> str:
    """Extract text from ToolResponse content."""
    item = resp.content[0]
    if isinstance(item, dict):
        return item["text"]
    return item.text


def _make_cloud_adapter(sandbox=None):
    """Create a mock FileSystemAdapter in cloud mode."""
    adapter = MagicMock()
    adapter.is_cloud = True
    adapter._backend = MagicMock()
    adapter.sandbox = sandbox or MagicMock()
    return adapter


def _make_sandbox_with_command_result(stdout_text, stderr_text="", error=None):
    """Create a mock sandbox that returns given command output."""
    sandbox = MagicMock()
    result = SimpleNamespace(
        logs=SimpleNamespace(
            stdout=[SimpleNamespace(text=stdout_text)] if stdout_text else [],
            stderr=[SimpleNamespace(text=stderr_text)] if stderr_text else [],
        ),
        error=error,
    )
    sandbox.commands = MagicMock()
    sandbox.commands.run = AsyncMock(return_value=result)
    return sandbox


def _cloud_patches(adapter):
    """Return a combined context manager patching both file_io and file_search adapters."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        with patch(
            "copaw.agents.tools.file_io.get_fs_adapter",
            return_value=adapter,
        ), patch(
            "copaw.agents.tools.file_search.get_fs_adapter",
            return_value=adapter,
        ), patch(
            "copaw.agents.tools.shell.get_cloud_working_dir",
            return_value="/workspace",
        ):
            yield

    return _ctx()


# ---------------------------------------------------------------------------
# grep_search cloud tests
# ---------------------------------------------------------------------------


class TestGrepSearchCloud:
    @pytest.mark.asyncio
    async def test_grep_cloud_with_matches(self):
        """grep_search in cloud mode returns sandbox grep output."""
        sandbox = _make_sandbox_with_command_result(
            "/workspace/main.py:10:    print('hello')\n"
            "/workspace/main.py:20:    print('hello world')\n"
        )
        adapter = _make_cloud_adapter(sandbox=sandbox)

        with _cloud_patches(adapter):
            resp = await grep_search("hello", path="/workspace")
            text = _get_text(resp)
            assert "main.py" in text
            assert "hello" in text

    @pytest.mark.asyncio
    async def test_grep_cloud_no_matches(self):
        """grep_search in cloud mode with no matches."""
        sandbox = _make_sandbox_with_command_result("")
        adapter = _make_cloud_adapter(sandbox=sandbox)

        with _cloud_patches(adapter):
            resp = await grep_search("nonexistent_pattern", path="/workspace")
            text = _get_text(resp)
            assert "No matches" in text

    @pytest.mark.asyncio
    async def test_grep_cloud_empty_pattern(self):
        """grep_search with empty pattern returns error."""
        resp = await grep_search("")
        text = _get_text(resp)
        assert "Error" in text

    @pytest.mark.asyncio
    async def test_grep_cloud_fallback_on_error(self, tmp_path):
        """When cloud grep fails, falls back to local grep."""
        sandbox = MagicMock()
        sandbox.commands = MagicMock()
        sandbox.commands.run = AsyncMock(
            side_effect=Exception("sandbox error")
        )
        adapter = _make_cloud_adapter(sandbox=sandbox)

        # Create a local test file for fallback
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello from local\nworld\n")

        with _cloud_patches(adapter):
            resp = await grep_search("hello", path=str(tmp_path))
            text = _get_text(resp)
            assert "hello" in text


# ---------------------------------------------------------------------------
# glob_search cloud tests
# ---------------------------------------------------------------------------


class TestGlobSearchCloud:
    @pytest.mark.asyncio
    async def test_glob_cloud_with_matches(self):
        """glob_search in cloud mode returns sandbox find output."""
        sandbox = _make_sandbox_with_command_result(
            "/workspace/src/main.py\n"
            "/workspace/src/utils.py\n"
            "/workspace/tests/test_main.py\n"
        )
        adapter = _make_cloud_adapter(sandbox=sandbox)

        with _cloud_patches(adapter):
            resp = await glob_search("**/*.py", path="/workspace")
            text = _get_text(resp)
            assert "main.py" in text
            assert "utils.py" in text

    @pytest.mark.asyncio
    async def test_glob_cloud_no_matches(self):
        """glob_search in cloud mode with no matches."""
        sandbox = _make_sandbox_with_command_result("")
        adapter = _make_cloud_adapter(sandbox=sandbox)

        with _cloud_patches(adapter):
            resp = await glob_search("*.nonexistent", path="/workspace")
            text = _get_text(resp)
            assert "No files matched" in text

    @pytest.mark.asyncio
    async def test_glob_cloud_empty_pattern(self):
        """glob_search with empty pattern returns error."""
        resp = await glob_search("")
        text = _get_text(resp)
        assert "Error" in text

    @pytest.mark.asyncio
    async def test_glob_cloud_relative_paths(self):
        """glob_search in cloud mode shows relative paths."""
        sandbox = _make_sandbox_with_command_result(
            "/workspace/config.json\n"
        )
        adapter = _make_cloud_adapter(sandbox=sandbox)

        with _cloud_patches(adapter):
            resp = await glob_search("*.json", path="/workspace")
            text = _get_text(resp)
            assert "config.json" in text
