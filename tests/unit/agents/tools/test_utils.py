# -*- coding: utf-8 -*-
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[4] / "src/qwenpaw/agents/tools/utils.py"
)
PACKAGE_NAME = "qwenpaw.agents.tools"

tools_package = types.ModuleType(PACKAGE_NAME)
tools_package.__path__ = [str(MODULE_PATH.parent)]
sys.modules.setdefault(PACKAGE_NAME, tools_package)

spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.utils",
    MODULE_PATH,
)
assert spec is not None
assert spec.loader is not None
utils = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = utils
spec.loader.exec_module(utils)


class _FakeAsyncFile:
    def __init__(self, reads: list[int], content: str = "ok"):
        self._reads = reads
        self._content = content

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def read(self, size: int) -> str:
        self._reads.append(size)
        return self._content


@pytest.mark.asyncio
async def test_read_file_safe_uses_actual_file_size(monkeypatch):
    reads: list[int] = []

    async def fake_stat(_path: str):
        return SimpleNamespace(st_size=4096)

    def fake_open(*_args, **_kwargs):
        return _FakeAsyncFile(reads)

    monkeypatch.setattr(utils.aiofiles.os, "stat", fake_stat)
    monkeypatch.setattr(utils.aiofiles, "open", fake_open)

    content = await utils.read_file_safe("/tmp/small.txt")

    assert content == "ok"
    assert reads == [4096]


@pytest.mark.asyncio
async def test_read_file_safe_caps_actual_file_size_to_max_bytes(monkeypatch):
    reads: list[int] = []

    async def fake_stat(_path: str):
        return SimpleNamespace(st_size=4096)

    def fake_open(*_args, **_kwargs):
        return _FakeAsyncFile(reads)

    monkeypatch.setattr(utils.aiofiles.os, "stat", fake_stat)
    monkeypatch.setattr(utils.aiofiles, "open", fake_open)

    await utils.read_file_safe("/tmp/small.txt", max_bytes=128)

    assert reads == [128]
