# -*- coding: utf-8 -*-
"""Valid public Python protocols must not be called private by runtime checks."""

import json

import pytest

from qwenpaw.plugins.check import _runtime
from qwenpaw.plugins.compliance import check_plugin


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_runtime_allows_resource_scope_async_context_protocol(
    tmp_path,
    explicit,
):
    (tmp_path / "plugin.json").write_text(
        json.dumps(
            {
                "id": "scope-protocol",
                "version": "1.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.2.0", "capabilities": ["resources"]},
            },
        ),
    )
    operation = (
        """
            owned = ctx.resources.child()
            entered = await ResourceScope.__aenter__(owned)
            try:
                await entered.run_sync(str, 42)
            finally:
                await owned.__aexit__(None, None, None)
"""
        if explicit
        else """
            async with ctx.resources.child() as resources:
                await resources.run_sync(str, 42)
"""
    )
    (tmp_path / "main.py").write_text(
        """
from qwenpaw.plugins.resources import ResourceScope
class Plugin:
    def register(self, ctx):
        async def activate(call):
"""
        + operation
        + """
        ctx.on_activate(activate)
plugin = Plugin()
""",
    )
    static = check_plugin(tmp_path)
    assert static.ok, static.findings
    report = await _runtime(tmp_path, static)
    assert report.ok, report.findings
    assert report.runtime_checked
    assert "cleanup:passed" in report.lifecycle_checks
