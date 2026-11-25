# -*- coding: utf-8 -*-
"""Valid public Python protocols must not be called private by runtime checks."""

import json

import pytest

from qwenpaw.plugins.check import _runtime
from qwenpaw.plugins.compliance import check_plugin


@pytest.mark.asyncio
async def test_runtime_allows_resource_scope_async_context_protocol(
    tmp_path,
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
    (tmp_path / "main.py").write_text(
        """
from qwenpaw.plugins.resources import ResourceScope as Scope
class Plugin:
    def register(self, ctx):
        async def activate(call):
            async with ctx.resources.child() as resources:
                await resources.run_sync(str, 42)

            owned = ctx.resources.child()
            entered = await Scope.__aenter__(owned)
            try:
                await entered.run_sync(str, 42)
            finally:
                await owned.__aexit__(None, None, None)
        ctx.on_activate(activate)
plugin = Plugin()
""",
    )
    static = check_plugin(tmp_path)
    assert static.ok, static.findings
    assert not static.uncovered
    report = await _runtime(tmp_path, static)
    assert report.ok, report.findings
    assert report.runtime_checked
    assert "cleanup:passed" in report.lifecycle_checks
