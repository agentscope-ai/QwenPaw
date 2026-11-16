# -*- coding: utf-8 -*-
"""Explicit source-plugin setup for legacy import algorithm tests."""

import pytest

# Reuse the real loader and its isolated registry; no availability bypass.
# pylint: disable-next=unused-import
from tests.unit.plugins.conftest import fresh_registry

# pylint: disable-next=unused-import
from tests.unit.plugins.test_sdk_entry_contract import (
    plugin_loader,
    write_plugin,
)


@pytest.fixture()
async def matching_harness_plugins(loader, tmp_path):
    """Activate the Codex and Qoder Harnesses used by marked import tests."""
    for source in ("codex", "qoder"):
        root = tmp_path / "plugins" / f"qwenpaw-harness-{source}"
        body = (
            "from qwenpaw.plugins.harnesses import "
            "HarnessCapabilities, HarnessSpec\n"
            "class Plugin:\n"
            "    def register(self, context):\n"
            "        context.register_harness(HarnessSpec(\n"
            f"            {source!r}, {source!r}, "
            "lambda context, settings: None, "
            "HarnessCapabilities()))\n"
            "plugin = Plugin()\n"
        )
        manifest = write_plugin(
            root,
            body,
            sdk={"version": "1.1.0", "capabilities": ["harnesses"]},
            meta={"harnesses": [{"id": source, "label": source}]},
        )
        record = await loader.load_plugin(manifest, root, {})
        assert record.status == "active"
    yield
