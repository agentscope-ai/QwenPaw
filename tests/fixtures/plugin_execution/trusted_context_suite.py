"""Existing launch API's actual cleanup gap; no hypothetical mapping API."""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from qwenpaw.plugins.execution import PluginLaunchSpec, PluginProcess
from qwenpaw.plugins.execution.bootstrap import _hash_code_root

ROOT = Path(__file__).resolve().parents[3]
QQ_ENV = {
    "QQ_API_BASE": "http://127.0.0.1:19001/qq-api",
    "QQ_TOKEN_URL": "http://127.0.0.1:19002/token",
    "QQ_PORTAL_HOST": "127.0.0.1:19003",
}


@asynccontextmanager
async def observed_child(tmp_path, monkeypatch, owner):
    for name, value in {
        **QQ_ENV,
        "DASHSCOPE_API_KEY": "host-env-test-key",
        "UNRELATED_HOST_SECRET": "must-not-inherit",
        "PYTHONPATH": str(tmp_path / "evil-import"),
        "PYTHONSTARTUP": str(tmp_path / "evil-startup"),
        "LD_PRELOAD": str(tmp_path / "evil.so"),
        "DYLD_INSERT_LIBRARIES": str(tmp_path / "evil.dylib"),
    }.items():
        monkeypatch.setenv(name, value)
    code = tmp_path / "code"
    code.mkdir()
    shutil.copyfile(
        Path(__file__).with_name("trusted_context_worker.py"),
        code / "worker.py",
    )
    shutil.copytree(
        ROOT / "plugins/channel/sip/qwenpaw_channel_sip",
        code / "qwenpaw_channel_sip",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    # Existing host policy is explicit during precutover; no fabricated owner.
    from qwenpaw.plugins.official_execution_context import (
        project_official_execution,
    )

    _, selected = project_official_execution(
        owner,
        {},
        working_dir=tmp_path,
        legacy_state_dir=tmp_path / "legacy",
        environment=os.environ,
    )
    if owner == "sip":
        # This original node tests the generic mapping/fallback mechanism only.
        # Normal SIP host policy uses detached config and has its own child test.
        selected = {"DASHSCOPE_API_KEY": os.environ["DASHSCOPE_API_KEY"]}
    spec = PluginLaunchSpec(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        code_root=code,
        source_revision=_hash_code_root(code),
        plugin_id=owner,
        instance_id="context-observer",
        generation=1,
        entrypoint="worker:Worker",
        config={},
        private_env=selected,
    )
    process = PluginProcess()
    try:
        await process.start(spec)
        result = await process.call("fixture.observe_context", {})
        assert result["pid"] == process.health_snapshot()["pid"] != os.getpid()
        assert result["cwd"] == str(code)
        for name in (
            "UNRELATED_HOST_SECRET",
            "PYTHONPATH",
            "PYTHONSTARTUP",
            "LD_PRELOAD",
            "DYLD_INSERT_LIBRARIES",
        ):
            assert result["environment"][name] is None
        assert str(tmp_path / "evil-import") not in result["sys_path"]
        print(
            json.dumps({"owner": owner, "observation": result}, sort_keys=True)
        )
        yield result
    finally:
        stopped = await process.stop()
        assert stopped.exited and not stopped.residual


@pytest.mark.asyncio
async def test_actual_generic_qq_legacy_override_context_reaches_child(
    tmp_path, monkeypatch
):
    async with observed_child(tmp_path, monkeypatch, "qq") as result:
        assert {key: result["environment"][key] for key in QQ_ENV} == QQ_ENV


@pytest.mark.asyncio
async def test_actual_generic_sip_environment_fallback_keeps_explicit_priority(
    tmp_path, monkeypatch
):
    async with observed_child(tmp_path, monkeypatch, "sip") as result:
        assert result["sip_explicit"] == "explicit-test-key"
        assert result["sip_fallback"] == "host-env-test-key"


@pytest.mark.asyncio
async def test_unrelated_owner_does_not_inherit_official_or_injection_variables(
    tmp_path, monkeypatch
):
    async with observed_child(
        tmp_path, monkeypatch, "fixture.unrelated"
    ) as result:
        for key in (*QQ_ENV, "DASHSCOPE_API_KEY"):
            assert result["environment"][key] is None
