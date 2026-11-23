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


def test_local_commands_use_plugin_ownership_and_existing_model_files(
    tmp_path,
    monkeypatch,
    fresh_registry,
    bounded_dependency_environment,
):
    import shutil
    import threading
    import asyncio
    from types import SimpleNamespace

    import click
    import httpx

    from qwenpaw import constant
    from qwenpaw.cli.plugin_resources import doctor_contributions
    from qwenpaw.config import utils
    from qwenpaw.plugins.local_model_legacy import bundled_local_source
    from qwenpaw.utils import runtime_api

    # Model a legal installation without importing or downloading either SDK.
    for package, version in (
        ("huggingface_hub", "0.20.0"),
        ("modelscope-hub", "0.7.1"),
    ):
        metadata = (
            bounded_dependency_environment
            / f"{package.replace('-', '_')}-{version}.dist-info"
        )
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {package}\nVersion: {version}\n",
            encoding="utf-8",
        )

    plugins = tmp_path / "plugins"
    monkeypatch.setattr(constant, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(utils, "WORKING_DIR", tmp_path)
    config = tmp_path / "config.json"
    data = tmp_path / "local-data"
    settings = {"plugins": {"local-llamacpp": {"data_dir": str(data)}}}
    config.write_text(json.dumps(settings), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(cli, ["models", "local"]).exit_code == 2
    source = plugins / "local-llamacpp"
    shutil.copytree(bundled_local_source(), source)
    threads = set(threading.enumerate())
    result = runner.invoke(cli, ["models", "download", "--help"])
    assert result.exit_code == 0, result.output
    assert "--source" in result.output and "Examples:" in result.output
    assert not data.exists()
    model = data / "models" / "example" / "small" / "weights.gguf"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"GGUF")
    result = runner.invoke(cli, ["models", "local"])
    assert result.exit_code == 0, (result.output, result.exception)
    assert "example/small" in result.output
    result = runner.invoke(
        cli,
        ["models", "remove-local", "example/small"],
        input="n\n",
    )
    assert result.exit_code == 0 and model.exists()

    requests = []
    slow = False

    async def runtime(request):
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(
                409,
                json={"detail": "Cannot delete a model while it is running"},
            )
        if slow:
            await asyncio.Event().wait()
        return httpx.Response(200, json={"running": False})

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        runtime_api.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(
            transport=httpx.MockTransport(runtime),
            **kwargs,
        ),
    )
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "local-test")
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "test-token")
    monkeypatch.setenv("QWENPAW_RUNTIME_API_URL", "http://127.0.0.1:54321")

    @click.command()
    def check():
        for _name, notes in doctor_contributions(
            SimpleNamespace(
                cfg=None,
                raw_cfg={},
                cli_base_url="http://127.0.0.1:54321",
                timeout=0.5 if slow else 2,
                deep=True,
            ),
        ):
            for note in notes:
                click.echo(note)

    result = runner.invoke(check)
    assert result.exit_code == 0, (result.output, result.exception)
    assert "inference was not checked" in result.output
    assert len(requests) == 1
    assert (
        str(requests[0].url)
        == "http://127.0.0.1:54321/api/local-models/diagnostics"
    )
    assert requests[0].headers["X-QwenPaw-Runtime-Token"] == "test-token"
    slow = True
    result = runner.invoke(check)
    assert result.exit_code == 0, (result.output, result.exception)
    assert "Local llama.cpp binary:" in result.output
    assert "(extension error) TimeoutError" in result.output
    remove = ["models", "remove-local", "example/small", "-y"]
    result = runner.invoke(cli, remove)
    assert result.exit_code == 1 and model.exists(), result.output
    assert "Cannot delete a model while it is running" in result.output
    assert requests[-1].url.path == "/api/local-models/models"
    assert requests[-1].url.params["model_id"] == "example/small"
    assert requests[-1].headers["X-QwenPaw-Runtime-Token"] == "test-token"
    monkeypatch.delenv("QWENPAW_RUNTIME_ID")
    result = runner.invoke(cli, remove)
    assert result.exit_code == 0, (result.output, result.exception)
    assert not model.exists()
    settings["plugins"]["local-llamacpp"]["enabled"] = False
    config.write_text(json.dumps(settings), encoding="utf-8")
    assert runner.invoke(cli, ["models", "local"]).exit_code == 2
    shutil.rmtree(source)
    assert runner.invoke(cli, ["models", "local"]).exit_code == 2
    assert not fresh_registry.cli_contributions
    assert not fresh_registry.extensions
    assert not fresh_registry.runtime_owners.leases()
    assert set(threading.enumerate()) <= threads


@pytest.mark.parametrize("kind", ["custom", "native", "static"])
def test_sdk_provider_doctor_preserves_registration_only_boundary(
    tmp_path,
    monkeypatch,
    fresh_registry,
    bounded_dependency_environment,
    kind,
):
    import click

    from qwenpaw import constant
    from qwenpaw.cli.doctor_cmd import _check_active_llm
    from qwenpaw.cli.plugin_resources import ensure_resources
    from qwenpaw.cli.plugin_session import session_for
    from qwenpaw.config import utils
    from qwenpaw.config.config import ModelSlotConfig
    from qwenpaw.providers.provider_manager import ProviderManager
    from qwenpaw.providers.openai_provider import OpenAIProvider
    from qwenpaw.providers.provider import ModelConnectionResult

    async def check_static(provider, model_id, _timeout):
        assert provider.base_url == "https://example.test/v1"
        assert model_id == "test"
        return ModelConnectionResult(success=True, message="reachable")

    monkeypatch.setattr(
        OpenAIProvider,
        "check_model_connection",
        check_static,
    )

    plugins = tmp_path / "plugins"
    source = plugins / "doctor-provider"
    source.mkdir(parents=True)
    monkeypatch.setattr(constant, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(utils, "WORKING_DIR", tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": source.name,
                "version": "1.0.0",
                "type": "provider",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.1.0", "capabilities": ["providers"]},
            },
        ),
        encoding="utf-8",
    )
    (source / "main.py").write_text(
        f"KIND = {kind!r}\n"
        + """
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo

def unexpected(*args):
    raise AssertionError('Doctor entered business execution')

class Plugin:
    def register(self, ctx):
        ctx.on_activate(unexpected)
        ctx.register_provider(ProviderSpec(
            'doctor-provider', 'Doctor provider',
            protocol=None if KIND == 'custom' else 'openai-chat',
            generate=unexpected if KIND == 'custom' else None,
            connect=unexpected if KIND == 'native' else None,
            check_connection=unexpected if KIND == 'custom' else None,
            require_api_key=False,
            base_url='https://example.test/v1',
            models=(ModelInfo('test', 'Test', supports_multimodal=False),),
        ))

plugin = Plugin()
""",
        encoding="utf-8",
    )

    @click.command()
    @click.pass_context
    def check(ctx):
        ensure_resources("providers")
        session_for(ctx).run(
            ProviderManager.get_instance().set_default_model(
                "chat",
                ModelSlotConfig(provider_id="doctor-provider", model="test"),
            ),
        )
        status, detail, _notes = session_for(ctx).run(
            _check_active_llm(1, False),
        )
        assert status is (True if kind == "static" else None), detail
        click.echo(detail)

    result = CliRunner().invoke(check)
    assert result.exit_code == 0, (result.output, result.exception)
    assert (
        "reachable" if kind == "static" else "requires plugin activation"
    ) in result.output
    assert fresh_registry.get_provider("doctor-provider") is None


@pytest.mark.parametrize("args", [[], ["status"], ["status", "--help"]])
def test_group_overlay_preserves_custom_click_behavior(monkeypatch, args):
    from types import SimpleNamespace

    import click

    from qwenpaw.cli import plugin_cli

    monkeypatch.setattr(
        plugin_cli,
        "catalog_for",
        lambda ctx: SimpleNamespace(children=lambda path: set(), mounts={}),
    )

    class CustomGroup(click.Group):
        __slots__ = ("message",)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.message = "before"

        def parse_args(self, ctx, args):
            ctx.meta["custom_parser"] = True
            return super().parse_args(ctx, args)

        def invoke(self, ctx):
            assert ctx.meta["custom_parser"]
            click.echo(self.message)
            result = super().invoke(ctx)
            click.echo("after")
            return result

    @click.group(cls=CustomGroup, invoke_without_command=True)
    def group():
        pass

    @group.command()
    def status():
        click.echo("ready")

    runner = CliRunner()
    native = runner.invoke(group, args)
    mounted_group = plugin_cli.overlay(group)
    assert isinstance(mounted_group, CustomGroup)
    assert mounted_group.group_class is group.group_class
    mounted = runner.invoke(mounted_group, args)
    assert mounted.exit_code == native.exit_code == 0
    assert mounted.output == native.output
    assert type(group) is CustomGroup
    assert group.commands == {"status": status}


@pytest.mark.parametrize(
    "channel,requirement,available",
    [
        (False, "lifecycle-fixture==1.0", True),
        (False, "qwenpaw-missing-cli-sdk==1.0", False),
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
    if available:
        assert result.output == "sent\n"

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


def test_missing_parent_reports_plugin_path_without_loading_entry(
    tmp_path,
    monkeypatch,
):
    import click

    from qwenpaw.cli.plugin_cli import (
        ExtensibleGroup,
        catalog_for,
        missing_cli_root_messages,
    )
    from qwenpaw.config import utils

    source = tmp_path / "orphan"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "orphan",
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.2.0", "capabilities": ["cli"]},
                "cli": [
                    {"id": "root", "path": ["missing", "status"]},
                    {"id": "nested", "path": ["known", "missing", "status"]},
                ],
            },
        ),
        encoding="utf-8",
    )
    (source / "main.py").write_text(
        "raise AssertionError('Parent lookup must stay passive')",
        encoding="utf-8",
    )
    monkeypatch.setattr(utils, "get_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(
        utils,
        "get_config_path",
        lambda: tmp_path / "config.json",
    )

    @click.group(cls=ExtensibleGroup)
    def root():
        pass

    @root.group()
    def known():
        pass

    @root.command()
    @click.pass_context
    def diagnose(ctx):
        for message in missing_cli_root_messages(ctx, catalog_for(ctx)):
            click.echo(message)

    runner = CliRunner()
    for args in (["missing"], ["known", "missing"]):
        result = runner.invoke(root, [*args, "status"])
        assert result.exit_code == 2
        assert f"requires a parent command group at: {' '.join(args)}" in (
            result.output
        )
    result = runner.invoke(root, ["diagnose"])
    assert result.exit_code == 0
    assert "requires a parent command group at: missing" in result.output


def test_required_subcommand_fails_without_activating_plugin(monkeypatch):
    from types import SimpleNamespace

    import click

    from qwenpaw.cli import plugin_cli

    class CustomGroup(click.Group):
        def invoke(self, ctx):
            return super().invoke(ctx)

    def unexpected_execution(*_args):
        pytest.fail("A missing subcommand activated the plugin")

    monkeypatch.setattr(plugin_cli, "catalog_for", lambda _ctx: None)
    command = plugin_cli._execution_command(
        CustomGroup("example", no_args_is_help=False),
        SimpleNamespace(session=SimpleNamespace(execute=unexpected_execution)),
    )

    result = CliRunner().invoke(command)

    assert result.exit_code == 2, result.output
    assert "Missing command" in result.output


@pytest.mark.parametrize(
    "mode",
    ["command", "invoke", "group-invoke", "lazy", "alias", "nested"],
)
def test_plugin_command_registers_runs_and_cleans_up(
    tmp_path,
    monkeypatch,
    fresh_registry,
    bounded_dependency_environment,
    mode,
):
    from qwenpaw import constant
    from qwenpaw.cli import plugin_commands
    from qwenpaw.cli.plugin_session import PluginSession
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
                        "kind": (
                            "command"
                            if mode in {"command", "invoke"}
                            else "group"
                        ),
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    (source / "main.py").write_text(
        f"MODE = {mode!r}\n"
        + """
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
    if MODE == 'command':
        return status
    if MODE == 'invoke':
        class CustomCommand(click.Command):
            def invoke(self, ctx):
                return status.callback(**ctx.params)
        return CustomCommand('status', params=status.params)
    if MODE == 'group-invoke':
        class DefaultGroup(click.Group):
            def get_command(self, ctx, name):
                return status if name == 'child' else None

            def invoke(self, ctx):
                record('invoke-active' if plugin.loop is not None else 'route')
                return super().invoke(ctx)
        def default_status(**options):
            if click.get_current_context().invoked_subcommand is None:
                return status.callback(**options)
        return DefaultGroup(
            'status', callback=default_status, params=status.params,
            invoke_without_command=True,
        )
    class LazyGroup(click.Group):
        def list_commands(self, ctx):
            return ['alias', 'nested', 'status']
        def get_command(self, ctx, name):
            if name == 'status':
                return status
            if name == 'alias':
                return self.get_command(ctx, 'status')
            if name == 'nested':
                return LazyGroup('nested')
            return None
    return LazyGroup()

class Plugin:
    loop = None

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
    execute_calls = []
    execute = PluginSession.execute

    def track_execution(session, plugin_id, registration, callback, *a, **kw):
        execute_calls.append(plugin_id)

        def guarded(*args, **kwargs):
            instance = session.loader.lifecycle.get_instance(plugin_id)
            assert instance.activity.tasks
            return callback(*args, **kwargs)

        return execute(session, plugin_id, registration, guarded, *a, **kw)

    monkeypatch.setattr(PluginSession, "execute", track_execution)
    runner = CliRunner()
    args = ["models", "example"]
    if mode not in {"command", "invoke", "group-invoke"}:
        args.extend(
            {
                "lazy": ["status"],
                "alias": ["alias"],
                "nested": ["nested", "status"],
            }[mode],
        )
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
    assert not execute_calls
    if mode == "group-invoke":
        events.unlink()
        result = runner.invoke(cli, [*args, "child", "--help"])
        assert result.exit_code == 0, result.output
        assert events.read_text().splitlines() == ["register", "route"]
        assert not execute_calls
        events.unlink()
        result = runner.invoke(cli, [*args, "child"])
        assert result.exit_code == 0, (result.output, result.exception)
        assert events.read_text().splitlines() == [
            "register",
            "route",
            "activate",
            "run",
            "close",
        ]
        assert execute_calls == ["terminal-example"]
    for tail, code in (([], 0), (["--fail"], 1)):
        events.write_text("", encoding="utf-8")
        execute_calls.clear()
        result = runner.invoke(cli, [*args, *tail])
        assert result.exit_code == code, (result.output, result.exception)
        assert "ready" in result.output
        expected = ["register", "activate"]
        if mode == "group-invoke":
            expected.append("invoke-active")
        assert events.read_text().splitlines() == [*expected, "run", "close"]
        assert execute_calls == ["terminal-example"]
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
    assert (
        runner.invoke(cli, ["models", "config-key", "--help"]).exit_code == 0
    )


def test_cli_cleanup_keeps_memory_implementations_unloaded(tmp_path):
    """A fresh process must clean CLI ownership without loading backends."""
    import os
    from pathlib import Path
    import subprocess
    import sys

    import qwenpaw

    from .timing import WAIT_TIMEOUT

    plugin = tmp_path / "plugins" / "import-boundary"
    plugin.mkdir(parents=True)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (plugin / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin.name,
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.1.0", "capabilities": ["cli"]},
                "cli": [{"id": "status", "path": ["example"]}],
            },
        ),
        encoding="utf-8",
    )
    (plugin / "main.py").write_text(
        """
import click
from qwenpaw.plugins.cli import CliSpec

def build(call):
    @click.command()
    @click.option('--fail', is_flag=True)
    def status(fail):
        click.echo('ready')
        if fail:
            raise click.ClickException('requested failure')
    return status

class Plugin:
    def register(self, ctx):
        ctx.register_cli(CliSpec('status', build))

plugin = Plugin()
""",
        encoding="utf-8",
    )
    code = """
import sys
sys.path.insert(0, sys.argv[1])
import threading
from click.testing import CliRunner
from qwenpaw.cli.main import cli
from qwenpaw.plugins.registry import PluginRegistry

threads = set(threading.enumerate())
for args, expected in (
    (['--help'], 0),
    (['example', '--help'], 0),
    (['example'], 0),
    (['example', '--fail'], 1),
):
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == expected, (result.output, result.exception)
    if '--help' not in args:
        assert 'ready' in result.output
    assert not any(n.startswith('qwenpaw.agents.memory') for n in sys.modules)
    assert 'qwenpaw.agents.model_factory' not in sys.modules
    assert not PluginRegistry().cli_contributions
    assert set(threading.enumerate()) <= threads

from qwenpaw.memory.registry import memory_registry as internal
import qwenpaw.memory as public
assert public.memory_registry is internal
from qwenpaw.agents.memory import base_memory_manager as legacy
for name in public.__all__:
    assert getattr(public, name) is getattr(legacy, name), name
assert set(public.__all__) <= set(dir(public))
assert not hasattr(public, 'unknown_memory_contract')
for backend in ('none', 'remelight'):
    assert public.get_memory_manager_backend(backend) is internal.get(backend)
"""
    source = Path(qwenpaw.__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(source)],
        cwd=tmp_path,
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_TELEMETRY_DISABLED": "true",
        },
        capture_output=True,
        text=True,
        timeout=WAIT_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_interrupt_waits_for_async_cleanup_before_session_close(tmp_path):
    """A real SIGINT must finish async finally before the loop is closed."""
    from pathlib import Path
    import subprocess
    import sys

    import qwenpaw

    from .timing import WAIT_TIMEOUT

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
        timeout=WAIT_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Task was destroyed" not in result.stderr


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "failure,exit_code",
    [
        ("click.Abort()", 1),
        ("click.exceptions.Exit(7)", 7),
        ("TimeoutError()", 0),
    ],
)
def test_doctor_handles_check_errors_and_click_control_flow(
    tmp_path,
    monkeypatch,
    fresh_registry,
    bounded_dependency_environment,
    asynchronous,
    failure,
    exit_code,
):
    import threading
    from types import SimpleNamespace

    import click

    from qwenpaw import constant
    from qwenpaw.cli.plugin_resources import doctor_contributions
    from qwenpaw.config import utils

    plugins = tmp_path / "plugins"
    source = plugins / "doctor-control-flow"
    source.mkdir(parents=True)
    monkeypatch.setattr(constant, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(utils, "WORKING_DIR", tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": source.name,
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.1.0", "capabilities": ["extensions"]},
                "extensions": [
                    {"point": "qwenpaw.doctor", "id": "stop"},
                    {"point": "qwenpaw.doctor", "id": "next"},
                ],
            },
        ),
        encoding="utf-8",
    )
    signature = "async def" if asynchronous else "def"
    cleanup = "await asyncio.sleep(0)" if asynchronous else "pass"
    (source / "main.py").write_text(
        f"""
import asyncio
from pathlib import Path
import click
from qwenpaw.plugins.doctor import DOCTOR, DoctorSpec

{signature} check(call):
    try:
        raise {failure}
    finally:
        {cleanup}
        Path(__file__).with_name('cleaned').touch()

def next_check(call):
    Path(__file__).with_name('continued').touch()
    return ['next check']

class Plugin:
    def register(self, ctx):
        ctx.register_extension(DOCTOR, DoctorSpec('stop', check))
        ctx.register_extension(DOCTOR, DoctorSpec('next', next_check))

plugin = Plugin()
""",
        encoding="utf-8",
    )

    @click.command()
    def doctor():
        for _, notes in doctor_contributions(
            SimpleNamespace(
                cfg=None,
                raw_cfg={},
                cli_base_url="http://127.0.0.1:1",
                timeout=1,
                deep=False,
            ),
        ):
            for note in notes:
                click.echo(note)

    threads = set(threading.enumerate())
    result = CliRunner().invoke(doctor)
    assert result.exit_code == exit_code
    if exit_code == 0:
        assert "(extension error) TimeoutError" in result.output
    else:
        assert "extension error" not in result.output
    assert (source / "cleaned").exists()
    assert (source / "continued").exists() is (exit_code == 0)
    assert not fresh_registry.extensions
    assert not fresh_registry.runtime_owners.leases()
    assert set(threading.enumerate()) <= threads


@pytest.mark.parametrize(
    "capability,cancelled",
    [("providers", False), ("channels", False), ("providers", True)],
)
def test_native_resource_discovery_preserves_definition_lifecycle(
    tmp_path,
    monkeypatch,
    fresh_registry,
    bounded_dependency_environment,
    capability,
    cancelled,
):
    import threading
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    import click

    from qwenpaw import constant
    from qwenpaw.cli.plugin_resources import ensure_resources
    from qwenpaw.config import utils
    from qwenpaw.providers.provider_manager import ProviderManager

    manager = SimpleNamespace(
        register_plugin_provider_async=AsyncMock(),
        unregister_plugin_provider=Mock(),
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)

    plugins = tmp_path / "plugins"
    source = plugins / "resource-control-flow"
    source.mkdir(parents=True)
    monkeypatch.setattr(constant, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(utils, "WORKING_DIR", tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": source.name,
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.1.0", "capabilities": [capability]},
            },
        ),
        encoding="utf-8",
    )
    (source / "main.py").write_text(
        f"CANCELLED = {cancelled!r}\nCAPABILITY = {capability!r}\n"
        + """
import asyncio
from pathlib import Path
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.providers import ProviderSpec

def unexpected(*args):
    raise AssertionError('Definition discovery started business resources')

class Plugin:
    async def register(self, ctx):
        try:
            if CANCELLED:
                raise asyncio.CancelledError()
            if CAPABILITY == 'providers':
                ctx.register_provider(ProviderSpec('resource-example',
                    'Resource example', unexpected))
            else:
                ctx.register_channel(ChannelSpec('resource-example',
                    'Resource example', unexpected))
            ctx.on_activate(unexpected)
        finally:
            await asyncio.sleep(0)
            Path(__file__).with_name('cleaned').touch()

plugin = Plugin()
""",
        encoding="utf-8",
    )

    @click.command()
    def command():
        ensure_resources(capability)
        ensure_resources(capability)
        instance = fresh_registry.get_channel_catalog()
        if capability == "channels":
            assert "resource-example" in instance
        else:
            assert "resource-example" in fresh_registry.get_all_providers()
        click.echo("continued")

    threads = set(threading.enumerate())
    result = CliRunner().invoke(command)
    assert result.exit_code == (1 if cancelled else 0), result.exception
    assert ("Aborted!" in result.output) == cancelled
    assert ("continued" in result.output) == (not cancelled)
    assert "unavailable:" not in result.output
    assert manager.register_plugin_provider_async.await_count == (
        1 if capability == "providers" and not cancelled else 0
    )
    assert (source / "cleaned").exists()
    assert not fresh_registry.runtime_owners.leases()
    assert not fresh_registry.leftover_registrations(source.name)
    assert set(threading.enumerate()) <= threads


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
