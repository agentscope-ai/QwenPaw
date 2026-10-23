"""Current ZIP and real host fixtures without host platform imports."""

import asyncio
from importlib import abc
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from extension_process_suite import runtime

ROOT = Path(__file__).resolve().parents[3]
__all__ = ["runtime", "yuanbao_gateway", "forbid_yuanbao_host"]


@pytest.fixture(autouse=True)
def forbid_yuanbao_host(monkeypatch):
    attempts = []

    class Guard(abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "qwenpaw_channel_yuanbao" or fullname.startswith(
                ("qwenpaw_channel_yuanbao.", "qwenpaw.app.channels.yuanbao")
            ):
                attempts.append(fullname)
                raise AssertionError(
                    "Yuanbao implementation imported in host: " + fullname
                )

    assert not any(
        name.startswith(
            ("qwenpaw_channel_yuanbao", "qwenpaw.app.channels.yuanbao")
        )
        for name in sys.modules
    )
    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    yield
    assert attempts == []


def official_yuanbao_zip(directory, key, **_ignored):
    from qwenpaw.plugins.official_channels import bundled_channel_source

    assert key == "yuanbao"
    with bundled_channel_source("yuanbao") as source:
        target = directory / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    return target


@pytest_asyncio.fixture
async def yuanbao_gateway(tmp_path):
    owned = []

    async def create(name="A"):
        directory = tmp_path / ("gateway-" + name)
        directory.mkdir()
        stdout = (directory / "stdout.log").open("w")
        stderr = (directory / "stderr.log").open("w")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(Path(__file__).with_name("yuanbao_closeout_gateway.py")),
            str(ROOT),
            str(directory),
            env={
                **os.environ,
                "QWENPAW_WORKING_DIR": str(directory / "work"),
                "QWENPAW_SECRET_DIR": str(directory / "secret"),
                "QWENPAW_BACKUP_DIR": str(directory / "backup"),
            },
            stdout=stdout,
            stderr=stderr,
        )
        client = httpx.AsyncClient(trust_env=False)
        owned.append((process, client, directory, stdout, stderr))
        async with asyncio.timeout(8):
            while not (directory / "ready.json").exists():
                assert process.returncode is None, (
                    directory / "stderr.log"
                ).read_text()
                await asyncio.sleep(0.01)
        data = json.loads((directory / "ready.json").read_text())

        async def control(action, **payload):
            response = await client.request(
                "GET" if action == "state" else "POST",
                data["base"] + "/_test/" + action,
                **({"json": payload} if action != "state" else {}),
            )
            assert response.status_code == 200
            return response.json()

        return SimpleNamespace(
            **data, control=control, process=process, directory=directory
        )

    yield create
    for process, client, directory, stdout, stderr in reversed(owned):
        try:
            if (
                process.returncode is None
                and (directory / "ready.json").exists()
            ):
                base = json.loads((directory / "ready.json").read_text())[
                    "base"
                ]
                await client.post(base + "/_test/stop")
            await asyncio.wait_for(process.wait(), 3)
        finally:
            if process.returncode is None:
                process.terminate()
                await process.wait()
            await client.aclose()
            stdout.close()
            stderr.close()
