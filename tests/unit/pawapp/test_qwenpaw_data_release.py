"""Release contract for the qwenpaw-data app's bundled Context console."""

from __future__ import annotations

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPOSITORY_ROOT / "plugins" / "apps" / "qwenpaw-data"
MANIFEST = PLUGIN_DIR / "plugin.json"
CONTEXT_BRIDGE = PLUGIN_DIR / "scripts" / "context-console" / "paw-bridge.js"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "qwenpaw-data-release.yml"

# The 0.3.4 Context console imports @ant-design/v5-patch-for-react-19.
# Without it, React 19 silently drops antd's static message/modal renderer.
MIN_CONTEXT_CONSOLE_VERSION = (0, 3, 4)


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_context_console_includes_react19_antd_static_fix() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    runtime_dependencies = manifest["meta"]["runtime_dependencies"]

    assert _version_tuple(runtime_dependencies["minimum_version"]) >= (
        MIN_CONTEXT_CONSOLE_VERSION
    )


def test_release_workflow_uses_manifest_context_console_ref() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert (
        "context_console_ref: ${{ steps.version.outputs.context_console_ref }}"
        in workflow
    )
    assert (
        "ref: ${{ github.event.inputs.data_ref || "
        "needs.check-version.outputs.context_console_ref }}"
    ) in workflow


def test_context_console_bridge_routes_requests_through_the_app_gateway() -> None:
    bridge = CONTEXT_BRIDGE.read_text(encoding="utf-8")

    assert 'var GATEWAY_BASE = "/api/qwenpaw-data/context";' in bridge
    assert "window.QWENPAW_DATA_CONSOLE = consoleConfig;" in bridge
    assert (
        "dataBridgeConfig.api_base_url = "
        "dataBridgeConfig.api_base_url || GATEWAY_BASE;"
    ) in bridge
