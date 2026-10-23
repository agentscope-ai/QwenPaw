"""Generic private environment validation and actual inspection isolation."""
import json
import os
from pathlib import Path
import sys

import pytest

from qwenpaw.plugins.execution import PluginLaunchSpec, PluginProcess
from qwenpaw.plugins.execution.bootstrap import (
    BootstrapError,
    _hash_code_root,
    validate_private_environment,
)

ROOT = Path(__file__).resolve().parents[3]
SECRET = "private-canary-do-not-expose"


def spec_at(tmp_path, private_env):
    code = tmp_path / "code"
    code.mkdir()
    marker = tmp_path / "imports.jsonl"
    (code / "worker.py").write_text(
        """import json, os
from pathlib import Path
Path(MARKER).write_text(json.dumps({'value':os.environ.get('TRUSTED_TOKEN'), 'pid':os.getpid()}))
class Worker:
    def bind(self, context):
        context.peer.register_method('fixture.token', self.token)
    async def start(self, config): pass
    async def stop(self): pass
    async def token(self, params, request): return {'value':os.environ.get('TRUSTED_TOKEN')}
""".replace(
            "MARKER", repr(str(marker))
        )
    )
    return (
        PluginLaunchSpec(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            code_root=code,
            source_revision=_hash_code_root(code),
            plugin_id="fixture.context",
            instance_id="trusted-context",
            generation=1,
            entrypoint="worker:Worker",
            config={},
            private_env=private_env,
        ),
        marker,
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {1: "x"},
        {"A": 1},
        {"A": "x\0y"},
        {"A": "\ud800"},
        {"a": "x", "A": "y"},
        {"é": "x"},
        {"A" * 129: "x"},
        {f"KEY_{i}": "x" for i in range(33)},
        {"TOKEN": "x" * 16385},
        {f"KEY_{i}": "x" * 16384 for i in range(4)},
    ],
)
def test_invalid_private_mapping_is_rejected_without_payload(value):
    with pytest.raises(BootstrapError) as error:
        validate_private_environment(value)
    assert error.value.reason_code == "LAUNCH_ENVIRONMENT_INVALID"
    assert str(error.value) == "Invalid private launch environment"


@pytest.mark.parametrize(
    "name",
    [
        "PYTHONPATH",
        "pythonstartup",
        "__PYVENV_LAUNCHER__",
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
        "QWENPAW_WORKING_DIR",
        "HOME",
        "PATH",
        "BASH_ENV",
    ],
)
def test_bootstrap_and_directory_controls_cannot_be_reintroduced(name):
    with pytest.raises(BootstrapError) as error:
        validate_private_environment({name: SECRET})
    assert SECRET not in str(error.value)


def test_exact_bounds_and_empty_values_are_detached():
    value = {f"KEY_{i}": "" for i in range(32)}
    value["KEY_0"] = "x" * 16384
    result = validate_private_environment(value)
    assert result == value and result is not value
    value["KEY_0"] = "changed"
    assert result["KEY_0"] == "x" * 16384


@pytest.mark.asyncio
async def test_runtime_import_sees_detached_mapping_and_health_repr_redacts(
    tmp_path,
):
    original = {"TRUSTED_TOKEN": SECRET}
    spec, marker = spec_at(tmp_path, original)
    original["TRUSTED_TOKEN"] = "caller-mutated"
    assert spec.private_env == {"TRUSTED_TOKEN": SECRET}
    assert SECRET not in repr(spec)
    process = PluginProcess()
    try:
        await process.start(spec)
        assert json.loads(marker.read_text())["value"] == SECRET
        assert (await process.call("fixture.token", {}))["value"] == SECRET
        assert SECRET not in repr(process.health_snapshot())
    finally:
        stopped = await process.stop()
        assert stopped.exited and not stopped.residual


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["audit", "probe"])
async def test_actual_inspection_omits_secret_even_before_component_import(
    tmp_path, mode
):
    spec, marker = spec_at(tmp_path, {"TRUSTED_TOKEN": SECRET})
    process = PluginProcess()
    result = await getattr(process, mode)(spec)
    assert result.cleanup.exited and not result.cleanup.residual
    if mode == "audit":
        assert not marker.exists()
    else:
        observed = json.loads(marker.read_text())
        assert observed["value"] is None and observed["pid"] != os.getpid()
    assert SECRET not in repr(result)
    assert SECRET not in repr(process.health_snapshot())


@pytest.mark.asyncio
async def test_mutated_launch_mapping_is_revalidated_before_any_child(
    tmp_path,
):
    spec, marker = spec_at(tmp_path, {})
    spec.private_env["PYTHONPATH"] = SECRET
    process = PluginProcess()
    with pytest.raises(Exception) as error:
        await process.start(spec)
    assert (
        getattr(error.value, "reason_code", None)
        == "LAUNCH_ENVIRONMENT_INVALID"
    )
    assert SECRET not in str(error.value)
    assert process.health_snapshot()["pid"] is None and not marker.exists()
