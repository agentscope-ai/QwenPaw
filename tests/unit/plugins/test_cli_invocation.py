# -*- coding: utf-8 -*-
"""A terminal invocation owns plugin execution without installing its peers."""

from dataclasses import dataclass
import json
from typing import Callable

from click.testing import CliRunner
import pytest

from qwenpaw.cli.main import cli
from qwenpaw.plugins.api import PluginApi
from qwenpaw.plugins.provision import inventory_path, record_tool_factory
from qwenpaw.plugins.source_usage import source_writer


@pytest.mark.parametrize(
    "channel,requirement,available",
    [
        (False, "lifecycle-fixture==1.0", True),
        (False, "qwenpaw-missing-cli-sdk==1.0", False),
        (False, "lifecycle-fixture>=2.0", False),
        (False, 'qwenpaw-missing-cli-sdk; python_version < "1"', True),
        (True, "lifecycle-fixture==1.0", True),
        (True, "qwenpaw-missing-cli-sdk==1.0", False),
    ],
)
def test_capability_dependencies_are_admitted_before_implementation(
    tmp_path,
    monkeypatch,
    fresh_registry,
    bounded_dependency_environment,
    requirement,
    available,
    channel,
):
    import threading
    from types import SimpleNamespace
    import click
    from qwenpaw import constant
    from qwenpaw.config import utils
    from qwenpaw.cli.plugin_resources import doctor_contributions
    from qwenpaw.plugins.doctor import DOCTOR

    plugins = tmp_path / "plugins"
    source = plugins / "dependency-example"
    source.mkdir(parents=True)
    monkeypatch.setattr(constant, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(utils, "WORKING_DIR", tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    manifest = {
        "id": source.name,
        "version": "1.0.0",
        "entry": {"backend": "main.py"},
        "sdk": {
            "version": "1.1.0",
            "capabilities": ["cli", "extensions", "dependencies"],
        },
        "optional_dependencies": {
            "light": ["lifecycle-fixture==1.0"],
            "transport": [requirement],
        },
        "extensions": [
            {"point": DOCTOR.id, "id": "config"},
            {"point": DOCTOR.id, "id": "sdk", "requires": ["transport"]},
        ],
        "cli": [
            {"id": "example", "path": ["example"], "kind": "group"},
            {
                "id": "status",
                "path": ["example", "status"],
                "requires": ["light"],
            },
            {
                "id": "send",
                "path": ["example", "send"],
                "requires": ["transport"],
            },
        ],
    }
    if channel:
        from pathlib import Path
        from qwenpaw.app.channels.catalog import (
            get_configurable_channel_catalog,
        )

        manifest["type"] = "channel"
        manifest["entry"]["descriptor"] = "channel.json"
        descriptor = json.loads(
            (
                Path(__file__).resolve().parents[3]
                / "plugins/channel/telegram/channel.json"
            ).read_text(),
        )
        descriptor.pop("requirements_file")
        descriptor.update(
            schema_version=3,
            requires=["transport"],
            channel_key="dependency-example",
        )
        (source / "channel.json").write_text(
            json.dumps(descriptor),
            encoding="utf-8",
        )
    (source / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "main.py").write_text(
        """
from pathlib import Path
import click
from qwenpaw.plugins.cli import CliSpec
from qwenpaw.plugins.doctor import DOCTOR, DoctorSpec

def build_status(call):
    from .light import build
    return build(call)

def build_send(call):
    from .heavy import build
    return build(call)

def check_sdk(call):
    from .heavy import check
    return check(call)

class Plugin:
    def register(self, ctx):
        ctx.register_cli(CliSpec('example', lambda call: click.Group('example')))
        ctx.register_cli(CliSpec('status', build_status))
        ctx.register_cli(CliSpec('send', build_send))
        ctx.register_extension(DOCTOR, DoctorSpec('config', lambda c: ['config ok']))
        ctx.register_extension(DOCTOR, DoctorSpec('sdk', check_sdk))
plugin = Plugin()
""",
        encoding="utf-8",
    )
    (source / "light.py").write_text(
        """
from pathlib import Path
import click
Path(__file__).with_name('light-imported').touch()
def build(call):
    return click.Command('status', callback=lambda: click.echo('ready'))
""",
        encoding="utf-8",
    )
    (source / "heavy.py").write_text(
        """
from pathlib import Path
import click
Path(__file__).with_name('imported').touch()
def build(call):
    return click.Command('send', callback=lambda: click.echo('sent'))
def check(call):
    return ['sdk ok']
""",
        encoding="utf-8",
    )
    if channel:
        catalog = get_configurable_channel_catalog()
        assert "dependency-example" in catalog
        assert not fresh_registry.get_channel_catalog()
        assert not (source / "imported").exists()
    runner = CliRunner()
    threads = set(threading.enumerate())
    for args in (["--help"], ["example", "--help"], ["example", "status"]):
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, (result.output, result.exception)
        assert not (source / "imported").exists()
        assert (source / "light-imported").exists() is (args[-1] == "status")
    assert result.output == "ready\n"
    for tail in (["--help"], []):
        result = runner.invoke(cli, ["example", "send", *tail])
        assert result.exit_code == (0 if available else 1), result.output
        assert (source / "imported").exists() is available
        if not available:
            assert "DEPENDENCY_UNSATISFIED" in result.output
            assert "Traceback" not in result.output

    @click.command()
    def check():
        result = doctor_contributions(
            SimpleNamespace(
                cfg=None,
                raw_cfg={},
                cli_base_url="http://127.0.0.1:1",
                timeout=2,
                deep=False,
            ),
        )
        assert (source.name + ":config", ["config ok"]) in result
        sdk_notes = dict(result)[source.name + ":sdk"]
        assert (
            sdk_notes == ["sdk ok"]
            if available
            else ("DEPENDENCY_UNSATISFIED" in sdk_notes[0])
        )

    result = runner.invoke(check)
    assert result.exit_code == 0, (result.output, result.exception)
    assert set(threading.enumerate()) <= threads
    assert not fresh_registry.cli_contributions
    assert not fresh_registry.extensions
    (tmp_path / "config.json").write_text(
        json.dumps({"plugins": {source.name: {"enabled": False}}}),
        encoding="utf-8",
    )
    result = runner.invoke(cli, ["example", "status"])
    assert result.exit_code == 2, result.output


def test_plugin_command_registers_runs_and_cleans_up(
    tmp_path,
    monkeypatch,
    fresh_registry,
    bounded_dependency_environment,
):
    from qwenpaw import constant
    from qwenpaw.cli import plugin_commands
    from qwenpaw.config import utils
    from qwenpaw.plugins import api

    plugins = tmp_path / "plugins"
    source = tmp_path / "source"
    (source / "skills").mkdir(parents=True)
    monkeypatch.setattr(constant, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(utils, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(plugin_commands, "_is_running", lambda: False)
    monkeypatch.delenv("QWENPAW_RUNTIME_ID", raising=False)
    settings = {
        "agents": {
            "profiles": {
                "default": {
                    "id": "default",
                    "workspace_dir": str(tmp_path / "workspace"),
                },
            },
        },
    }
    config = tmp_path / "config.json"
    config.write_text(json.dumps(settings), encoding="utf-8")
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "terminal-example",
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {
                    "version": "1.1.0",
                    "capabilities": ["cli", "tools", "skills", "resources"],
                },
                "cli": [
                    {
                        "id": "status",
                        "path": ["models", "example"],
                        "help": "Example status",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    (source / "main.py").write_text(
        """
import asyncio
from pathlib import Path
import threading
import click
from qwenpaw.plugins.cli import CliSpec
from qwenpaw.plugins.skills import SkillSpec
from qwenpaw.plugins.tools import ToolResult, ToolSpec

events = Path(__file__).with_name('events')
def record(event):
    with events.open('a') as output:
        output.write(event + '\\n')

def build(call):
    @click.command()
    @click.option('--fail', is_flag=True)
    def status(fail):
        async def read():
            assert threading.current_thread() is threading.main_thread()
            assert asyncio.get_running_loop() is plugin.loop
            await asyncio.sleep(0)
            record('run')
            return 'ready'
        click.echo(call.run(read()))
        if fail:
            raise click.ClickException('requested failure')
    return status

class Plugin:
    def register(self, ctx):
        record('register')
        ctx.register_tool(ToolSpec('peer', 'Peer tool', {'type': 'object'},
                                   lambda call, args: ToolResult.text('ok')))
        ctx.register_skills(SkillSpec())
        ctx.register_cli(CliSpec('status', build))
        async def activate(call):
            self.loop = asyncio.get_running_loop()
            record('activate')
            async def close():
                assert asyncio.get_running_loop() is self.loop
                await asyncio.sleep(0)
                record('close')
            call.resources.defer(close)
        ctx.on_activate(activate)
plugin = Plugin()
""",
        encoding="utf-8",
    )

    def unexpected_install(*args, **kwargs):
        pytest.fail("A terminal command executed host installation setup")

    monkeypatch.setattr(api, "_write_tool_config", unexpected_install)
    monkeypatch.setattr(PluginApi, "_do_install_skills", unexpected_install)
    runner = CliRunner()
    args = ["models", "example"]
    assert runner.invoke(cli, args).exit_code == 2
    result = runner.invoke(cli, ["plugin", "install", str(source)])
    assert result.exit_code == 0, (result.output, result.exception)
    source = plugins / "terminal-example"
    assert source.is_dir()
    record_tool_factory("terminal-example", "backend_tool", {"enabled": True})
    inventory = inventory_path("terminal-example")
    saved = inventory.read_bytes()
    events = source / "events"
    for help_args in (["--help"], ["models", "--help"]):
        result = runner.invoke(cli, help_args)
        assert result.exit_code == 0, result.output
    assert "Example status" in result.output
    assert not events.exists()

    result = runner.invoke(cli, [*args, "--help"])
    assert result.exit_code == 0, result.output
    assert events.read_text().splitlines() == ["register"]
    for tail, code in (([], 0), (["--fail"], 1)):
        events.write_text("", encoding="utf-8")
        result = runner.invoke(cli, [*args, *tail])
        assert result.exit_code == code, (result.output, result.exception)
        assert "ready" in result.output
        assert events.read_text().splitlines() == [
            "register",
            "activate",
            "run",
            "close",
        ]
        assert inventory.read_bytes() == saved
        assert not fresh_registry.leftover_registrations("terminal-example")
        with source_writer(source):
            pass

    settings["plugins"] = {"terminal-example": {"enabled": False}}
    config.write_text(json.dumps(settings), encoding="utf-8")
    assert (
        "Example status" not in runner.invoke(cli, ["models", "--help"]).output
    )
    assert runner.invoke(cli, args).exit_code == 2
    result = runner.invoke(
        cli,
        ["plugin", "uninstall", "terminal-example"],
        input="y\n",
    )
    assert result.exit_code == 0, (result.output, result.exception)
    assert not source.exists()
    assert not inventory.exists()
    assert not fresh_registry.leftover_registrations("terminal-example")
    assert (
        "Example status" not in runner.invoke(cli, ["models", "--help"]).output
    )
    assert runner.invoke(cli, args).exit_code == 2

    def unexpected_plugin_scan(*args, **kwargs):
        pytest.fail("A core command unnecessarily scanned plugins")

    monkeypatch.setattr(
        "qwenpaw.plugins.discovery.discover_plugins",
        unexpected_plugin_scan,
    )
    assert runner.invoke(cli, ["models", "local", "--help"]).exit_code == 0


def test_interrupt_waits_for_async_cleanup_before_session_close(tmp_path):
    """A real SIGINT must finish async finally before the loop is closed."""
    from pathlib import Path
    import subprocess
    import sys

    import qwenpaw

    source = Path(qwenpaw.__file__).resolve().parent.parent
    code = """
import sys
sys.path.insert(0, sys.argv[1])
import asyncio
import signal
import click
from qwenpaw.cli.plugin_session import PluginSession

events = []
session = PluginSession()

async def operation():
    try:
        asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)
        await asyncio.Event().wait()
    finally:
        await asyncio.sleep(0)
        events.append('cleaned')

try:
    session.run(operation())
except click.Abort:
    events.append('aborted')
finally:
    session.close()
    events.append('closed')
assert events == ['cleaned', 'aborted', 'closed'], events
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(source)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Task was destroyed" not in result.stderr


async def test_extensions_revoke_owned_calls_without_click(sdk_component):
    from qwenpaw.plugins.doctor import DOCTOR, DoctorSpec
    from qwenpaw.plugins.extensions import ExtensionPoint
    from qwenpaw.plugins.errors import SDKError, StaleContextError

    @dataclass(frozen=True)
    class InventorySpec:
        id: str
        read: Callable[[], dict[str, int]]

    inventory = ExtensionPoint("test.inventory", InventorySpec)
    async with sdk_component(capabilities=("extensions",)) as (host, ctx):
        registry = host._loader.registry
        registry.extension_points[inventory.id] = inventory
        ctx._api.manifest["extensions"] = [
            {"point": DOCTOR.id, "id": "check"},
            {"point": inventory.id, "id": "items"},
        ]
        first = ctx.register_extension(
            DOCTOR,
            DoctorSpec("check", lambda call: ["ready"]),
        )
        ctx.register_extension(
            inventory,
            InventorySpec("items", lambda: {"count": 1}),
        )
        (reference,) = registry.get_extensions(DOCTOR)
        # Independent consumers query the same registration without Click.
        for _ in range(2):
            with registry.get_extensions(DOCTOR)[0].invocation() as spec:
                assert spec.check(None) == ["ready"]
        with registry.get_extensions(inventory)[0].invocation() as spec:
            assert spec.read() == {"count": 1}
        with pytest.raises(SDKError, match="Duplicate"):
            ctx.register_extension(DOCTOR, DoctorSpec("check", lambda c: []))
        with pytest.raises(SDKError, match="Expected DoctorSpec"):
            ctx.register_extension(DOCTOR, InventorySpec("bad", lambda: {}))
        with pytest.raises(SDKError, match="Unsupported"):
            ctx.register_extension(
                ExtensionPoint(DOCTOR.id, InventorySpec),
                InventorySpec("bad", lambda: {}),
            )
        ctx._api.manifest["extensions"] = [{"point": DOCTOR.id, "id": "check"}]
        with pytest.raises(SDKError, match="Undeclared"):
            ctx.register_extension(
                inventory,
                InventorySpec("other", lambda: {}),
            )
        await first.close()
        with pytest.raises(StaleContextError):
            with reference.invocation():
                pytest.fail("Released extension was invoked")
        ctx.register_extension(DOCTOR, DoctorSpec("check", lambda c: ["new"]))
        # Delayed teardown of the old registration must preserve its replacement.
        first._release()
        (replacement,) = registry.get_extensions(DOCTOR)
        with replacement.invocation() as spec:
            assert spec.check(None) == ["new"]
        registry.unregister_plugin(ctx.plugin_id)
        assert not registry.extensions
        with pytest.raises(StaleContextError):
            with replacement.invocation():
                pytest.fail("Bulk removal left a callable extension")
        ctx.register_extension(DOCTOR, DoctorSpec("check", lambda c: []))
        (replacement,) = registry.get_extensions(DOCTOR)
    assert not registry.extensions
    with pytest.raises(StaleContextError):
        with replacement.invocation():
            pytest.fail("Disposed plugin was invoked")
