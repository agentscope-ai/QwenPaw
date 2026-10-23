# -*- coding: utf-8 -*-
"""Trusted home survives launch and bootstrap before component imports."""

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.execution import PluginLaunchSpec, PluginProcess
from qwenpaw.plugins.execution import bootstrap, process as process_module

ROOT = Path(__file__).resolve().parents[3]


def launch_spec(tmp_path, windows):
    code = tmp_path / "code"
    code.mkdir()
    marker = tmp_path / "import.json"
    (code / "worker.py").write_text(
        """import json, ntpath, os
from pathlib import Path
observed = {name: os.environ.get(name) for name in (
    'USERPROFILE', 'HOME', 'HOST_SECRET', 'PYTHONPATH', 'PYTHONHOME')}
if WINDOWS:
    # Exercise CPython's Windows home lookup while keeping real POSIX I/O.
    original = Path.expanduser
    def windows_expanduser(self):
        value = ntpath.expanduser(str(self))
        if value.startswith('~'):
            raise RuntimeError('Could not determine home directory.')
        return type(self)(value)
    Path.expanduser = windows_expanduser
    os.environ['QWENPAW_RUNTIME_ID'] = 'fixture.windows-home'
    try:
        from qwenpaw.constant import WORKING_DIR
        observed['working_dir'] = str(WORKING_DIR)
    finally:
        Path.expanduser = original
observed['pid'] = os.getpid()
Path(MARKER).write_text(json.dumps(observed))
class Worker:
    def bind(self, context):
        context.peer.register_method('fixture.home', self.home)
    async def start(self, config): pass
    async def stop(self): pass
    async def home(self, params, request): return observed
""".replace("WINDOWS", repr(windows)).replace("MARKER", repr(str(marker))),
    )
    return (
        PluginLaunchSpec(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            code_root=code,
            source_revision=bootstrap._hash_code_root(code),
            plugin_id="fixture.home",
            instance_id="home-context",
            generation=1,
            entrypoint="worker:Worker",
            config={},
        ),
        marker,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["run", "manage", "audit", "probe"])
@pytest.mark.parametrize("windows", [False, True], ids=["posix", "windows"])
async def test_real_workers_receive_only_trusted_platform_home(
    tmp_path,
    monkeypatch,
    mode,
    windows,
):
    home = tmp_path / "home"
    home.mkdir()
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(
            name,
            (
                str(home / ".." / "home")
                if name == ("USERPROFILE" if os.name == "nt" else "HOME")
                else str(tmp_path / "caller-profile")
            ),
        )
    monkeypatch.setenv("HOST_SECRET", "host-canary")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "poison-import"))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "poison-home"))
    spec, marker = launch_spec(tmp_path, windows)
    monkeypatch.setattr(
        process_module,
        "os",
        SimpleNamespace(**{**vars(os), "name": "nt" if windows else "posix"}),
    )
    original_spawn = asyncio.create_subprocess_exec
    launched = []

    async def spawn(*args, **kwargs):
        launched.append(dict(kwargs["env"]))
        # Only launch branch is emulated; retain native process custody.
        if os.name == "nt":
            kwargs.pop("start_new_session", None)
        else:
            kwargs["start_new_session"] = True
        return await original_spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    process = PluginProcess()
    try:
        if mode in {"audit", "probe"}:
            result = await getattr(process, mode)(spec)
            assert result.cleanup.exited and not result.cleanup.residual
        elif mode == "manage":
            # Generic Runtime intentionally has no management adapter. Import
            # must finish before that existing interface check rejects it.
            with pytest.raises(process_module.ProcessError) as error:
                await process._start(spec, mode="manage")
            assert error.value.reason_code == "ENTRYPOINT_INVALID"
        else:
            await process.start(spec)
            assert await process.call("fixture.home", {}) == json.loads(
                marker.read_text(),
            )
        assert len(launched) == 1
        assert launched[0].get("USERPROFILE") == (
            str(home.resolve()) if windows else None
        )
        for name in ("HOME", "HOST_SECRET", "PYTHONPATH", "PYTHONHOME"):
            assert name not in launched[0]
        if mode == "audit":
            assert not marker.exists()
        else:
            observed = json.loads(marker.read_text())
            assert observed["pid"] != os.getpid()
            assert observed["USERPROFILE"] == (
                str(home.resolve()) if windows else None
            )
            for name in ("HOME", "HOST_SECRET", "PYTHONPATH", "PYTHONHOME"):
                assert observed[name] is None
            if windows:
                assert observed["working_dir"] == str(home / ".qwenpaw")
    finally:
        stopped = await process.stop()
        assert stopped.exited and not stopped.residual


@pytest.mark.parametrize("name", ["USERPROFILE", "userprofile", "UserProfile"])
def test_bootstrap_retains_windows_profile_without_ambient_controls(
    monkeypatch,
    name,
):
    environment = {
        name: r"C:\Users\Trusted",
        "PATH": "trusted-path",
        "HOME": "untrusted-home",
        "HOST_SECRET": "host-canary",
        "PYTHONPATH": "poison-import",
        "PYTHONHOME": "poison-home",
    }
    monkeypatch.setattr(
        bootstrap,
        "os",
        SimpleNamespace(name="nt", environ=environment),
    )
    bootstrap._clean_environment(())
    assert environment == {name: r"C:\Users\Trusted", "PATH": "trusted-path"}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["USERPROFILE", "userprofile", "UserProfile"])
async def test_private_profile_is_rejected_before_child_creation(
    tmp_path,
    name,
):
    spec, marker = launch_spec(tmp_path, False)
    spec.private_env[name] = "private-profile-canary"
    process = PluginProcess()
    with pytest.raises(process_module.ProcessError) as error:
        await process.start(spec)
    assert error.value.reason_code == "LAUNCH_ENVIRONMENT_INVALID"
    assert "private-profile-canary" not in str(error.value)
    assert process.health_snapshot()["pid"] is None
    assert not marker.exists()
