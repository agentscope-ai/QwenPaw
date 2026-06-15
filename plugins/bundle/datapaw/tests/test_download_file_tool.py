# -*- coding: utf-8 -*-
"""Tests for DataPaw built-in download_file tool."""
import asyncio
import inspect


class _FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, _size):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(self, chunks):
        self.content = _FakeContent(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.requested_urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def get(self, url, timeout=None):  # pylint: disable=unused-argument
        self.requested_urls.append(url)
        return self._response


def test_download_file_saves_url_content(tmp_path, monkeypatch):
    from plugin_datapaw.core import tools as datapaw_tools

    response = _FakeResponse([b"col\n", b"1\n"])
    session = _FakeSession(response)

    monkeypatch.setattr(
        datapaw_tools.aiohttp,
        "ClientSession",
        lambda: session,
    )

    save_path = tmp_path / "node" / "result.csv"
    result = asyncio.run(
        datapaw_tools.download_file(
            "http://internal/result.csv",
            str(save_path),
        ),
    )

    assert session.requested_urls == ["http://internal/result.csv"]
    assert save_path.read_bytes() == b"col\n1\n"
    assert "下载成功" in result.content[0].text
    assert str(save_path) in result.content[0].text


def test_download_file_resolves_relative_artifacts_under_workspace(
    tmp_path,
    monkeypatch,
):
    from plugin_datapaw.core import tools as datapaw_tools

    response = _FakeResponse([b"country,pv\n", b"US,10\n"])
    session = _FakeSession(response)

    monkeypatch.setattr(
        datapaw_tools.aiohttp,
        "ClientSession",
        lambda: session,
    )

    workspace_dir = tmp_path / "workspace"
    other_cwd = tmp_path / "process-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    save_path = (
        "artifacts/1781516185939/graph_4QCojdEp/"
        "n1_fetch_data/pv_country_nov_dec.csv"
    )
    result = asyncio.run(
        datapaw_tools.download_file(
            "http://internal/pv_country.csv",
            save_path,
            workspace_dir=workspace_dir,
        ),
    )

    expected_path = workspace_dir / save_path
    assert session.requested_urls == ["http://internal/pv_country.csv"]
    assert expected_path.read_bytes() == b"country,pv\nUS,10\n"
    assert not (other_cwd / save_path).exists()
    assert str(expected_path) in result.content[0].text


def test_bound_download_file_tool_keeps_public_tool_signature(tmp_path):
    from plugin_datapaw.core.tools import bind_download_file_tool

    tool = bind_download_file_tool(tmp_path / "workspace")

    assert tool.__name__ == "download_file"
    assert list(inspect.signature(tool).parameters) == ["url", "save_path"]


def test_download_file_is_registered_as_default_datapaw_tool():
    from plugin_datapaw.core.tools import (
        DEFAULT_TOOL_NAMES,
        TOOL_REGISTRY,
        download_file,
    )

    assert DEFAULT_TOOL_NAMES == ["download_file"]
    assert TOOL_REGISTRY["download_file"] is download_file
