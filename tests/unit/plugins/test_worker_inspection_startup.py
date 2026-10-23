# -*- coding: utf-8 -*-
"""Exercise Windows socketpair semantics with real child-process IPC.

Forcing the stdlib TCP fallback on other hosts simulates the Windows
self-pipe operations; it does not substitute for native Windows coverage.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

from qwenpaw.channel_protocol.artifacts import code_root_digest
from qwenpaw.plugins.execution import PluginLaunchSpec, PluginProcess
from qwenpaw.plugins.execution import bootstrap
from qwenpaw.plugins.execution.process import ProcessError

ROOT = Path(__file__).resolve().parents[3]


def _inspection_spec(tmp_path, monkeypatch, *, candidate_operation=""):
    code = tmp_path / "candidate"
    code.mkdir()
    imported = tmp_path / "imported"
    candidate_source = "import socket\n"
    candidate_source += candidate_operation
    candidate_source += (
        f"from pathlib import Path\nPath({str(imported)!r}).touch()\n"
        "class Worker:\n"
        "    def bind(self, context): pass\n"
        "    async def start(self, config): pass\n"
        "    async def stop(self): pass\n"
    )
    (code / "candidate.py").write_text(candidate_source, encoding="utf-8")
    launcher = tmp_path / "inspection-worker.py"
    launcher.write_text(
        "import _socket, runpy, socket\n"
        "native_socketpair = getattr(_socket, 'socketpair', None)\n"
        "if native_socketpair is not None:\n"
        "    del _socket.socketpair\n"
        "try:\n"
        "    # Load the real stdlib fallback: bind, listen, connect, accept.\n"
        "    fallback = runpy.run_path(socket.__file__)['socketpair']\n"
        "finally:\n"
        "    if native_socketpair is not None:\n"
        "        _socket.socketpair = native_socketpair\n"
        "socket.socketpair = fallback\n"
        f"runpy.run_path({str(ROOT / 'src/qwenpaw/plugins/execution/worker.py')!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(PluginProcess, "_worker_path", lambda *_: launcher)
    return (
        PluginLaunchSpec(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            code_root=code,
            source_revision=bootstrap._hash_code_root(code),
            plugin_id="fixture.inspection",
            instance_id="inspection-loop",
            generation=1,
            entrypoint="candidate:Worker",
            config={},
        ),
        imported,
    )


@pytest.mark.parametrize("mode", ["audit", "probe"])
async def test_inspection_initializes_trusted_loop_before_guard(
    tmp_path,
    monkeypatch,
    mode,
):
    spec, imported = _inspection_spec(tmp_path, monkeypatch)
    (spec.code_root / "candidate.data").write_bytes(b"metadata")
    nested = spec.code_root / "candidate"
    nested.mkdir()
    (nested / "data.txt").write_bytes(b"nested")
    (nested / "driver.pyc").write_bytes(b"compiled")
    cache = nested / "__pycache__"
    cache.mkdir()
    (cache / "driver.cpython-313.pyc").write_bytes(b"cached")
    spec = replace(spec, source_revision=code_root_digest(spec.code_root))
    process = PluginProcess()
    try:
        result = await getattr(process, mode)(spec)
        assert result.cleanup.exited is True
        assert result.cleanup.residual == ()
        assert imported.exists() is (mode == "probe")
    finally:
        stopped = await process.stop()
        assert stopped.exited is True
        assert stopped.residual == ()


@pytest.mark.parametrize(
    "candidate_operation",
    [
        "with socket.socket() as connection:\n"
        "    connection.bind(('127.0.0.1', 0))\n",
        "with socket.socket() as connection:\n"
        "    connection.connect(('127.0.0.1', 9))\n",
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-I', '-c', 'pass'], check=True)\n",
    ],
    ids=["bind", "connect", "spawn"],
)
async def test_inspection_still_denies_candidate_network_or_process(
    tmp_path,
    monkeypatch,
    candidate_operation,
):
    spec, imported = _inspection_spec(
        tmp_path,
        monkeypatch,
        candidate_operation=candidate_operation,
    )
    process = PluginProcess()
    try:
        with pytest.raises(ProcessError) as error:
            await process.probe(spec)
        assert error.value.reason_code == "PROBE_NETWORK_OR_PROCESS_DENIED"
        assert not imported.exists()
    finally:
        stopped = await process.stop()
        assert stopped.exited is True
        assert stopped.residual == ()
