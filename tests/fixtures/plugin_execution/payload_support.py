"""Small fixtures reusing the existing generic launch and actual Process."""

from dataclasses import replace
import json
from pathlib import Path

import pytest
import pytest_asyncio

from process_suite import alive, digest


def ledger_rows(marker):
    if not marker.exists():
        return []
    return [json.loads(line) for line in marker.read_text().splitlines()]


@pytest.fixture
def payload_launch(launch):
    def make(**overrides):
        spec, marker = launch(**overrides)
        path = spec.code_root / "worker.py"
        path.write_text(
            path.read_text() + "\n" + Path(__file__).with_name("payload_worker.py").read_text()
        )
        return replace(
            spec, entrypoint="worker:PayloadWorker", source_revision=digest(spec.code_root)
        ), marker

    return make


@pytest_asyncio.fixture
async def payload_processes(api):
    owned = []

    def make(**kwargs):
        process = api.PluginProcess(**kwargs)
        owned.append(process)
        return process

    yield make
    for process in owned:
        pid = process.health_snapshot()["pid"]
        result = await process.stop(timeout=2)
        assert result.exited and not result.residual
        assert not alive(pid)
