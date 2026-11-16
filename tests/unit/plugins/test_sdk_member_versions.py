# -*- coding: utf-8 -*-
"""Versioning old classes' new members without rejecting public protocols."""

import json

import pytest

from qwenpaw.plugins.compliance import API_EXPORTS, check_plugin
from qwenpaw.plugins import SDKCompatibilityError, sdk_version


def package(tmp_path, source, version):
    (tmp_path / "plugin.json").write_text(
        json.dumps(
            {
                "id": "versions",
                "version": "1.0",
                "entry": {"backend": "main.py"},
                "sdk": {
                    "version": version,
                    "capabilities": ["resources", "markets"],
                },
            },
        ),
    )
    (tmp_path / "main.py").write_text(source)
    return check_plugin(tmp_path)


@pytest.mark.parametrize(
    "source",
    [
        "from qwenpaw.plugins.harnesses import HarnessSpec\n",
        (
            "from qwenpaw.plugins import PluginContext\n"
            "def f(ctx: PluginContext):\n    ctx.register_harness(None)\n"
        ),
        (
            "from qwenpaw.plugins.testing import PluginTestHost\n"
            "def f(host: PluginTestHost):\n    return host.list_harnesses()\n"
        ),
        (
            "from qwenpaw.plugins.testing import PluginTestHost\n"
            "async def f(host: PluginTestHost):\n"
            "    return await host.harness_status('example')\n"
        ),
        (
            "from qwenpaw.plugins.testing import PluginTestHost\n"
            "def f(host: PluginTestHost):\n"
            "    return host.run_harness('example', None)\n"
        ),
        (
            "from qwenpaw.plugins.resources import ResourceScope as Scope\n"
            "async def f(r: Scope):\n"
            "    await r.run_sync(int, '1')\n"
        ),
        (
            "from qwenpaw.plugins.resources import ResourceScope\n"
            "def f(r: ResourceScope):\n"
            "    r.process(['echo'], tree=True)\n"
        ),
        (
            "from qwenpaw.plugins.markets import MarketContext\n"
            "def f(call: MarketContext):\n"
            "    return call.category, call.lang\n"
        ),
        (
            "class Plugin:\n"
            "    def register(self, ctx):\n"
            "        async def f():\n"
            "            async with ctx.resources.child() as owned:\n"
            "                await owned.run_sync(int, '1')\n"
        ),
        (
            "from qwenpaw.plugins.testing import PluginTestHost\n"
            "async def f(host: PluginTestHost):\n"
            "    await host.search_market('key', '', category='app')\n"
        ),
        (
            "from qwenpaw.plugins.models import ModelSelection\n"
            "selection = ModelSelection('provider', 'model')\n"
        ),
        (
            "from qwenpaw.plugins.tools import ToolContext\n"
            "async def f(call: ToolContext):\n"
            "    return await call.models.catalog()\n"
        ),
        (
            "from qwenpaw.plugins.tools import ToolContext\n"
            "def f(call: ToolContext):\n"
            "    return call.storage.path('db.sqlite')\n"
        ),
        (
            "from qwenpaw.plugins.storage import PluginStorage\n"
            "def f(storage: PluginStorage):\n"
            "    return storage.import_legacy_tree('history', 'history')\n"
        ),
        "from qwenpaw.plugins.stops import StopSpec\n",
        "from qwenpaw.plugins.shell import ShellBackendSpec, ShellRequest, ShellResult\n",
        (
            "from qwenpaw.plugins.workflows import WorkflowSpec, "
            "WorkflowSchedule, WorkflowContext, WorkflowResult, WorkflowNotification\n"
        ),
        "from qwenpaw.plugins.channel_workers import ChannelDefinition\n",
        (
            "from qwenpaw.plugins.channel_workers import ChannelContent, "
            "ResponsePolicy\n"
            "block = ChannelContent(role='refusal')\n"
            "policy = ResponsePolicy(content_source='semantic')\n"
        ),
        (
            "from pathlib import Path\n"
            "from qwenpaw.plugins.testing import PluginTestHost\n"
            "host = PluginTestHost(Path('tmp'), process_channels=('example',))\n"
        ),
        (
            "from qwenpaw.plugins.channels import ChannelMessage\n"
            "message = ChannelMessage('u', (), thread_id='topic')\n"
        ),
        "class Plugin:\n    def register(self, ctx):\n        ctx.register_workflow(None)\n",
        (
            "from qwenpaw.plugins.testing import PluginTestHost\n"
            "async def f(host: PluginTestHost):\n"
            "    await host.run_workflow('plugin:report')\n"
        ),
        "class Plugin:\n    def register(self, ctx):\n        ctx.register_shell_backend(None)\n",
        (
            "from qwenpaw.plugins.modes import ModeContext\n"
            "def f(call: ModeContext):\n"
            "    return call.identity\n"
        ),
        (
            "from qwenpaw.plugins.providers import ProviderContext\n"
            "async def f(call: ProviderContext):\n"
            "    return await call.runs.current()\n"
        ),
        "from qwenpaw.plugins.apps import ChatRequest\nrequest = ChatRequest('hello', model=None)\n",
        (
            "from qwenpaw.plugins.apps import PawApp\n"
            "app = PawApp(app_id='upload')\n"
            "app.route('/upload', body='form')\n"
        ),
        (
            "from qwenpaw.plugins.apps import PawApp\n"
            "app = PawApp(app_id='upload')\n"
            "app.route('/upload', max_body_bytes=1024)\n"
        ),
        (
            "from qwenpaw.plugins.apps import HttpRequest\n"
            "def f(request: HttpRequest):\n"
            "    return request.form\n"
        ),
        "from qwenpaw.plugins.apps import UploadedFile, FileResponse\n",
        (
            "from qwenpaw.plugins.commands import CommandSpec\n"
            "spec = CommandSpec('name', lambda call, args: None, control=True)\n"
        ),
        (
            "from qwenpaw.plugins.prompts import PromptSpec\n"
            "spec = PromptSpec('dynamic', '', 100, None, lambda call: 'hello')\n"
        ),
        "from qwenpaw.plugins.prompts import PromptSpec\nspec = PromptSpec('dynamic')\n",
        (
            "from qwenpaw.plugins.commands import CommandSpec\n"
            "spec = CommandSpec('name', lambda call, args: None, (), '', True)\n"
        ),
        (
            "from qwenpaw.plugins.testing import PluginTestHost\n"
            "async def f(host: PluginTestHost):\n"
            "    await host.call_control_command('/name')\n"
        ),
        (
            "from qwenpaw.plugins.tools import ToolContext\n"
            "async def f(call: ToolContext):\n"
            "    await call.checkpoints.timeline()\n"
        ),
        "from qwenpaw.plugins.checkpoints import CheckpointService, CheckpointError\n",
        (
            "from qwenpaw.plugins.apps import AppContext\n"
            "async def f(call: AppContext):\n"
            "    return await call.conversations.history(limit=10)\n"
        ),
        (
            "from qwenpaw.plugins.tools import ToolContext\n"
            "async def f(call: ToolContext):\n"
            "    return await call.workspace_ops.resolve_path('file')\n"
        ),
    ],
)
def test_new_member_requires_new_minimum(tmp_path, source):
    old = package(tmp_path, source, "1.0")
    assert any(f.code == "sdk-version" for f in old.findings)
    assert not old.ok
    current = package(tmp_path, source, "1.2")
    assert current.ok, current.findings


@pytest.mark.parametrize(
    "source",
    [
        "from qwenpaw.plugins.models import ModelSelection\n",
        "from qwenpaw.plugins.channel_workers import ChannelDefinition\n",
        (
            "from qwenpaw.plugins.resources import ResourceScope\n"
            "async def f(scope: ResourceScope):\n"
            "    await scope.run_sync(int, '1')\n"
        ),
        (
            "from qwenpaw.plugins import PluginContext\n"
            "def f(ctx: PluginContext):\n"
            "    ctx.register_shell_backend(None)\n"
        ),
    ],
)
def test_sdk_11_rejects_sdk_12_additions(tmp_path, source):
    old = package(tmp_path, source, "1.1.0")
    assert not old.ok
    assert {finding.code for finding in old.findings} == {"sdk-version"}
    assert package(tmp_path, source, "1.2.0").ok


def test_harness_interfaces_keep_sdk_11_minimum(tmp_path):
    source = (
        "from qwenpaw.plugins import PluginContext\n"
        "from qwenpaw.plugins.harnesses import HarnessSpec\n"
        "from qwenpaw.plugins.testing import PluginTestHost\n"
        "def f(ctx: PluginContext, host: PluginTestHost):\n"
        "    ctx.register_harness(None)\n"
        "    host.list_harnesses()\n"
        "    host.harness_status('example')\n"
        "    host.run_harness('example', None)\n"
    )
    assert package(tmp_path, source, "1.1.0").ok
    assert not package(tmp_path, source, "1.0.0").ok


def test_old_host_rejects_new_plugin_before_loading(monkeypatch):
    declaration = {"version": "1.2.0", "capabilities": ["resources"]}
    sdk_version.validate_sdk(declaration, "new-plugin")
    monkeypatch.setattr(sdk_version, "SDK_VERSION", "1.1.0")
    with pytest.raises(SDKCompatibilityError, match="Unsupported SDK version"):
        sdk_version.validate_sdk(declaration, "new-plugin")


@pytest.mark.parametrize("capability", ["shell", "stops", "workflows"])
def test_new_capabilities_require_sdk_12(capability):
    declaration = {"version": "1.1.0", "capabilities": [capability]}
    with pytest.raises(SDKCompatibilityError, match="SDK >= 1.2.0"):
        sdk_version.validate_sdk(declaration)
    declaration["version"] = "1.2.0"
    sdk_version.validate_sdk(declaration)


def test_third_party_similar_names_do_not_require_sdk_upgrade(tmp_path):
    report = package(
        tmp_path,
        "from example import Runner\nasync def f(r: Runner):\n    await r.run_sync()\n",
        "1.0",
    )
    assert report.ok, report.findings


def test_frontend_cannot_be_mistaken_for_python_version_coverage(tmp_path):
    (tmp_path / "ui.js").write_text("window.QwenPaw.chat.composer.read();")
    report = package(tmp_path, "", "1.0")
    assert report.ok
    assert any(
        "qwenpaw-sdk-check" in limitation for limitation in report.uncovered
    )


def test_existing_methods_remain_compatible(tmp_path):
    report = package(
        tmp_path,
        (
            "from qwenpaw.plugins.resources import ResourceScope\n"
            "async def f(r: ResourceScope):\n"
            "    await r.close()\n"
        ),
        "1.0",
    )
    assert report.ok, report.findings
    entry = next(e for e in API_EXPORTS if e.symbol == "ResourceScope")
    assert entry.since == "1.0.0"
    assert ("process.tree", "1.2.0") in entry.members


def test_existing_prompt_text_remains_compatible(tmp_path):
    report = package(
        tmp_path,
        (
            "from qwenpaw.plugins.prompts import PromptSpec\n"
            "first = PromptSpec('name', 'text')\n"
            "second = PromptSpec(name='name', text='text')\n"
        ),
        "1.0",
    )
    assert report.ok, report.findings
    assert report.rules_version == "1.2.0"


def test_private_context_remains_forbidden(tmp_path):
    report = package(tmp_path, "def f(ctx):\n    return ctx._api\n", "1.2")
    assert any(f.code == "private-context" for f in report.findings)


def test_explicit_public_protocol_is_not_private(tmp_path):
    report = package(
        tmp_path,
        (
            "from qwenpaw.plugins.resources import ResourceScope as Scope\n"
            "async def f(call: Scope):\n"
            "    await Scope.__aenter__(call)\n"
            "    await call.__aexit__(None, None, None)\n"
        ),
        "1.2",
    )
    assert report.ok, report.findings
    assert not report.uncovered


def test_protocol_exception_does_not_allow_private_methods(tmp_path):
    report = package(
        tmp_path,
        (
            "from qwenpaw.plugins.resources import ResourceScope\n"
            "async def f(call: ResourceScope):\n"
            "    call._guard()\n"
            "    ResourceScope._guard(call)\n"
        ),
        "1.2",
    )
    assert {f.code for f in report.findings} >= {
        "private-context",
        "private-member",
    }
