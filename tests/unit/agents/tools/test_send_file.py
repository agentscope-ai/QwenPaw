"""Tests for the file-result contract of ``send_file_to_user``."""

from unittest.mock import patch

import pytest
from agentscope.message import ToolResultState, URLSource

from qwenpaw.agents.tools.send_file import send_file_to_user


@pytest.mark.asyncio
async def test_send_file_resolves_relative_path(tmp_path):
    file_path = tmp_path / "report.txt"
    file_path.write_text("content", encoding="utf-8")

    with patch(
        "qwenpaw.agents.tools.file_io.get_all_project_dir_paths",
        return_value=[tmp_path],
    ):
        result = await send_file_to_user("report.txt")

    assert result.state == ToolResultState.SUCCESS
    assert isinstance(result.content[0].source, URLSource)
    assert result.content[0].name == "report.txt"
    assert str(result.content[0].source.url).endswith(
        str(file_path).replace("\\", "/"),
    )


@pytest.mark.asyncio
async def test_send_file_missing_path_is_error(tmp_path):
    with patch(
        "qwenpaw.agents.tools.file_io.get_all_project_dir_paths",
        return_value=[tmp_path],
    ):
        result = await send_file_to_user("missing.txt")

    assert result.state == ToolResultState.ERROR
    assert str(tmp_path / "missing.txt") in result.content[0].text


@pytest.mark.asyncio
async def test_send_file_url_failure_is_error(tmp_path):
    file_path = tmp_path / "report.txt"
    file_path.write_text("content", encoding="utf-8")

    with patch(
        "qwenpaw.agents.tools.send_file._path_to_file_url",
        side_effect=ValueError("bad path"),
    ):
        result = await send_file_to_user(str(file_path))

    assert result.state == ToolResultState.ERROR
    assert "bad path" in result.content[0].text
