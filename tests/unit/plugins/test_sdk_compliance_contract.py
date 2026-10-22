# -*- coding: utf-8 -*-
"""Dependency checker never executes static inputs and reports honest
coverage.
"""

import json
import os
import subprocess
import sys
import threading

import pytest

from .sdk_author_fixture import make_plugin


@pytest.mark.parametrize(
    "code",
    [
        "from qwenpaw.plugins import PluginApi",
        "from qwenpaw.plugins import *",
        "from qwenpaw.runtime.hooks import HookContext",
        "import qwenpaw.plugins as public; public.PluginLoader()",
        "def handler(ctx):\n    getattr(ctx, '_api')",
        (
            "class Plugin:\n    def register(self, author):\n      "
            "  alias = author\n        alias._loader"
        ),
    ],
)
def test_checker_rejects_private_imports_context_aliases_and_wildcards(
    tmp_path,
    code,
):
    from qwenpaw.plugins.compliance import check_plugin

    report = check_plugin(make_plugin(tmp_path, code, []))
    assert not report.ok and report.findings
    assert any(row.code.startswith("private-") for row in report.findings)
    assert not report.runtime_checked


def test_static_checker_does_not_execute_and_reports_dynamic_unknown(tmp_path):
    from qwenpaw.plugins.compliance import check_plugin

    marker = tmp_path / "executed"
    source = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).touch()\n"
        "from qwenpaw.plugins.tools import ToolSpec\n"
        "import httpx\n"
        "def handler(ctx, field):\n"
        "    return getattr(ctx, field)\n"
    )
    report = check_plugin(make_plugin(tmp_path, source, ["tools"]))
    assert report.ok and not marker.exists()
    assert "httpx" in report.dependencies
    assert report.uncovered and not report.runtime_checked


def test_checker_does_not_report_aliased_dynamic_import_as_fully_checked(
    tmp_path,
):
    from qwenpaw.plugins.compliance import check_plugin

    report = check_plugin(
        make_plugin(
            tmp_path,
            (
                "import importlib\nload = importlib.import_module\nload"
                '("qwenpaw.plugins.loader")\n'
            ),
            [],
        ),
    )
    assert not report.ok or report.uncovered


def runtime_state():
    return (
        sys.getprofile(),
        threading.getprofile(),
        os.environ.get("QWENPAW_WORKING_DIR"),
        tuple(sys.path),
        {k: v for k, v in sys.modules.items() if k.startswith("plugin_")},
    )


def runtime_report(plugin, capsys=None):
    args = [str(plugin), "--runtime"]
    if capsys is None:
        result = subprocess.run(
            [sys.executable, "-m", "qwenpaw.plugins.check", *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        code, output = result.returncode, result.stdout
    else:
        from qwenpaw.plugins.check import main

        # These trusted fixtures close their host; CLI process isolation is
        # still covered by one successful and one rejected plugin below.
        before = runtime_state()
        code = main(args)
        assert runtime_state() == before
        output = capsys.readouterr().out
    report = json.loads(output)
    assert report["runtime_checked"] is True
    return code, report


def test_runtime_checker_accepts_public_sdk_host_delegation(tmp_path):
    plugin = make_plugin(
        tmp_path,
        """
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, ctx):
        async def tool(call, arguments):
            return ToolResult.text("ok")

        ctx.register_tool(
            ToolSpec(
                "checked_tool", "Checked", {"type": "object"}, tool
            )
        )
        ctx.on_activate(
            lambda call: call.storage.write_json(
                "activation.json", True
            )
        )


plugin = Plugin()
""",
        ["tools", "storage"],
    )
    code, report = runtime_report(plugin)
    assert code == 0 and report["ok"] and not report["findings"]
    assert any("uncalled" in item for item in report["uncovered"])


@pytest.mark.parametrize("cleanup", [False, True])
def test_runtime_checker_detects_private_same_named_type_and_cleanup(
    tmp_path,
    cleanup,
    capsys,
):
    source = """
import importlib


class Plugin:
    def register(self, ctx):
        def private():
            module = importlib.import_module(
                "qwenpaw." + "runtime.hooks"
            )
            hook = module.HookContext(
                request=None,
                session_id="probe",
                agent_id="probe",
                root_session_id="probe",
                root_agent_id="probe",
                workspace_dir=None,
                workspace=None,
                app_services=None,
            )
            hook.inject_context("private data")

        def activate(call):
            __ACTION__

        ctx.on_activate(activate)


plugin = Plugin()
""".replace(
        "__ACTION__",
        "call.resources.defer(private)" if cleanup else "private()",
    )
    plugin = make_plugin(tmp_path, source, ["resources"])
    code, report = runtime_report(plugin, capsys)
    assert code == 1 and not report["ok"]
    assert any(
        row["code"] == "runtime-private-call"
        and "HookContext.inject_context" in row["message"]
        for row in report["findings"]
    )


def test_checker_report_is_bound_to_bytes_versions_and_executed_scope(
    tmp_path,
    capsys,
):
    from datetime import datetime
    from qwenpaw.plugins import SDK_VERSION
    from qwenpaw.plugins.compliance import check_plugin

    plugin = make_plugin(
        tmp_path,
        (
            "class Plugin:\n    def register(self, ctx):\n        "
            "pass\nplugin = Plugin()\n"
        ),
        ["tools"],
    )
    before = check_plugin(plugin)
    assert before.ok and len(before.package_hash) == 64
    assert before.sdk_version == SDK_VERSION and before.rules_version
    assert datetime.fromisoformat(before.checked_at).tzinfo is not None
    assert before.plugin_id == "extension-contract"
    assert before.declared_sdk_version == "1.0"
    assert before.capabilities == ("tools",)
    assert not before.runtime_checked
    entry = plugin / "main.py"
    entry.write_text(entry.read_text() + "\n# changed author source\n")
    after = check_plugin(plugin)
    assert after.package_hash != before.package_hash
    code, executed = runtime_report(plugin, capsys)
    assert code == 0 and executed["package_hash"] == after.package_hash
    assert executed["runtime_checked"]
    assert any("uncalled" in item for item in executed["uncovered"])


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        {"sdk": {"version": "1.0", "capabilities": None}},
        {"sdk": {"version": "1.0"}, "permissions": None},
    ],
)
def test_checker_malformed_declarations_report_failure_without_crashing(
    tmp_path,
    manifest,
):
    from qwenpaw.plugins.compliance import check_plugin

    (tmp_path / "plugin.json").write_text(json.dumps(manifest))
    report = check_plugin(tmp_path)
    assert not report.ok and report.findings
    assert not report.runtime_checked


def test_runtime_checker_attributes_executed_dynamic_private_import(tmp_path):
    plugin = make_plugin(
        tmp_path,
        """
import importlib
class Plugin:
    def register(self, ctx):
        target = ".".join(("qwenpaw", "plugins", "loader"))
        importlib.import_module(target)
plugin = Plugin()
""",
        [],
    )
    code, report = runtime_report(plugin)
    assert code == 1 and not report["ok"]
    assert any(
        row["code"].startswith("runtime-private")
        and "qwenpaw.plugins.loader" in row["message"]
        for row in report["findings"]
    )


def test_runtime_checker_accepts_public_registration_context_manager(
    tmp_path,
    capsys,
):
    plugin = make_plugin(
        tmp_path,
        """
class Plugin:
    def register(self, ctx):
        async def activate(call):
            async with call.resources.defer(
                lambda: call.storage.write_json("closed.json", True)
            ):
                pass
            assert call.storage.read_json("closed.json") is True

        ctx.on_activate(activate)


plugin = Plugin()
""",
        ["resources", "storage"],
    )
    code, report = runtime_report(plugin, capsys)
    assert code == 0 and report["ok"] and not report["findings"]
