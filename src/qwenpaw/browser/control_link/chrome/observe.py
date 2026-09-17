# -*- coding: utf-8 -*-
"""Connection observation for the core Chrome bridge."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Query

from ....config.utils import load_config
from ....utils.io_utils import run_sync_io
from .bridge import get_nm_bridge
from . import protocol
from .protocol import NM_HOST_BASENAME, NM_HOST_WIN_SUFFIX
from .ws_handler import resolve_default_ws_url

BRIDGE_DISCONNECTED = "bridge_disconnected"
SEMANTIC_CONTROL_PENDING = "semantic_control_not_integrated"

status_router = APIRouter(prefix="/browser/chrome", tags=["browser"])


def _nm_host_path() -> Path:
    """Return the platform-specific installed Native Messaging launcher."""
    suffix = NM_HOST_WIN_SUFFIX if sys.platform == "win32" else ""
    return Path.home() / ".qwenpaw" / "bin" / (NM_HOST_BASENAME + suffix)


def _asset_manifest_path() -> Path:
    return (
        Path.home() / ".qwenpaw/chrome-extension/qwenpaw-chrome/manifest.json"
    )


def probe_nm_host(path: Path | None = None) -> dict[str, Any]:
    """Read whether the Native Messaging host binary is installed."""
    path = _nm_host_path() if path is None else path
    present = path.is_file()
    return {
        "name": "nm_host",
        "passed": present,
        "status": "passed" if present else "failed",
        "code": "nm_host_present" if present else "nm_host_missing",
        "message": "Native Messaging host is installed."
        if present
        else "Native Messaging host is missing.",
        "repair_action": "none" if present else "reinstall_nm_host",
        "metadata": {"path": str(path)},
    }


def probe_extension_assets(
    manifest_path: Path | None = None,
    last_seen_version: str = "",
) -> dict[str, Any]:
    """Compare the read-only unpacked asset version with last connection."""
    manifest_path = (
        _asset_manifest_path() if manifest_path is None else manifest_path
    )
    if not last_seen_version:
        return {
            "name": "extension_assets",
            "passed": False,
            "status": "unknown",
            "code": "extension_version_unknown",
            "message": (
                "Extension has not connected yet; asset version cannot be "
                "compared."
            ),
            "repair_action": "wait_or_restart_chrome",
            "metadata": {"path": str(manifest_path)},
        }
    try:
        disk_version = str(
            json.loads(manifest_path.read_text(encoding="utf-8"))["version"],
        )
    except (OSError, ValueError, KeyError, TypeError):
        disk_version = "missing"
    passed = disk_version == last_seen_version
    return {
        "name": "extension_assets",
        "passed": passed,
        "status": "passed" if passed else "failed",
        "code": "extension_assets_match"
        if passed
        else "extension_assets_mismatch",
        "message": (
            f"Extension asset version {disk_version} vs last connected "
            f"version {last_seen_version}."
        ),
        "repair_action": "none" if passed else "reload_unpacked_extension",
        "metadata": {
            "path": str(manifest_path),
            "disk_version": disk_version,
            "last_seen_version": last_seen_version,
        },
    }


def probe_contract_drift(reported: dict[str, object]) -> dict[str, Any]:
    """Compare a plugin's reported contract against core protocol facts."""
    expected = protocol.contract_snapshot()
    contract = reported.get("contract")
    if not isinstance(contract, dict):
        detail = "Plugin did not report contract fields."
        return {
            "name": "contract_drift",
            "passed": True,
            "status": "passed",
            "severity": "warn",
            "code": "contract_not_reported",
            "message": detail,
            "detail": detail,
            "repair_action": "reload_or_update_extension",
            "metadata": {"missing_keys": sorted(expected)},
        }

    missing_keys = [key for key in expected if key not in contract]
    mismatches = [
        f"{key}: core={value!r} plugin={contract[key]!r}"
        for key, value in expected.items()
        if key in contract and contract[key] != value
    ]
    plugin_protocol = contract.get("protocolVersion")
    try:
        protocol_too_old = (
            plugin_protocol is not None
            and int(plugin_protocol) < protocol.MIN_COMPATIBLE_PROTOCOL_VERSION
        )
    except (TypeError, ValueError):
        protocol_too_old = False
    if protocol_too_old:
        mismatches.append(
            "protocolVersion: plugin="
            f"{plugin_protocol!r} is below minimum "
            f"{protocol.MIN_COMPATIBLE_PROTOCOL_VERSION!r}",
        )
    if mismatches:
        detail = "; ".join(mismatches)
        return {
            "name": "contract_drift",
            "passed": False,
            "status": "failed",
            "severity": "error",
            "code": "contract_mismatch",
            "message": detail,
            "detail": detail,
            "repair_action": "update_extension",
            "metadata": {"missing_keys": missing_keys},
        }

    build = reported.get("build")
    built_at = ""
    if isinstance(build, dict):
        built_at = str(build.get("builtAt") or "").strip()
    warnings: list[str] = []
    if missing_keys:
        warnings.append(
            "Plugin contract is missing keys: " + ", ".join(missing_keys),
        )
    if built_at and built_at < protocol.MIN_HEALTHY_PLUGIN_BUILD:
        warnings.append(
            f"Plugin build {built_at} is older than "
            f"{protocol.MIN_HEALTHY_PLUGIN_BUILD}",
        )
    detail = "; ".join(warnings) or "Plugin contract matches core."
    return {
        "name": "contract_drift",
        "passed": True,
        "status": "passed",
        "severity": "warn" if warnings else "none",
        "code": "contract_warning" if warnings else "contract_match",
        "message": detail,
        "detail": detail,
        "repair_action": "reload_or_update_extension" if warnings else "none",
        "metadata": {"missing_keys": missing_keys, "built_at": built_at},
    }


def _snapshot() -> dict[str, Any]:
    """Read the current bridge-owned lifecycle state."""
    return get_nm_bridge().snapshot()


def probe_bridge_lifecycle(
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Report whether recent bridge lifecycle facts indicate reconnection."""
    snapshot = _snapshot() if snapshot is None else snapshot
    connected = bool(snapshot["connected"])
    return {
        "name": "bridge_lifecycle",
        "passed": connected,
        "status": "passed" if connected else "pending",
        "code": "bridge_connected" if connected else BRIDGE_DISCONNECTED,
        "message": "Bridge is connected."
        if connected
        else "Bridge is disconnected; wait for reconnect or restart Chrome.",
        "repair_action": "none" if connected else "wait_or_restart_chrome",
        "metadata": {
            "last_disconnected_at": _iso_or_none(
                snapshot["last_disconnected_at"],
            ),
            "reconnect_count": snapshot["reconnect_count"],
        },
    }


def render_repair_text(result: dict[str, Any]) -> str:
    """Render failed self-test checks as a compact user repair ladder."""
    failed = [
        check
        for check in result.get("checks", [])
        if not check.get("passed") or check.get("severity") == "warn"
    ]
    if not failed:
        return "No repair action is needed."
    return "\n".join(
        f"{index}. {check['message']} Repair: {check['repair_action']}."
        for index, check in enumerate(failed, 1)
    )


def _bridge_connected() -> bool:
    return bool(_snapshot()["connected"])


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _extension_version() -> str:
    snapshot = _snapshot()
    return str(snapshot["extension_version"]) if snapshot["connected"] else ""


def _bridge_lifecycle(snapshot: dict[str, Any]) -> dict[str, Any]:
    connected = bool(snapshot["connected"])
    return {
        "connected": connected,
        "connected_since": (
            _iso_or_none(snapshot["connected_since"]) if connected else None
        ),
        "last_connected_at": _iso_or_none(snapshot["last_connected_at"]),
        "last_disconnected_at": _iso_or_none(snapshot["last_disconnected_at"]),
        "last_disconnect_reason": snapshot["last_disconnect_reason"],
        "last_error_code": snapshot["last_error_code"],
        "last_error_message": snapshot["last_error_message"],
        "last_request_timeout_at": _iso_or_none(
            snapshot["last_request_timeout_at"],
        ),
        "reconnect_count": snapshot["reconnect_count"],
    }


def _pending_semantic_control(message: str) -> dict[str, Any]:
    return {
        "status": "pending",
        "code": SEMANTIC_CONTROL_PENDING,
        "message": message,
    }


def _collect_fs_probes(
    last_seen_version: str,
) -> tuple[list[dict[str, Any]], str]:
    """Collect filesystem-only diagnosis facts outside the event loop."""
    return (
        [
            probe_nm_host(),
            probe_extension_assets(last_seen_version=last_seen_version),
        ],
        resolve_default_ws_url(),
    )


async def collect_self_test_async() -> dict[str, Any]:
    """Report core bridge readiness without testing semantic control."""
    started = perf_counter()
    bridge = get_nm_bridge()
    snapshot = bridge.snapshot()
    fs_probes, ws_url = await run_sync_io(
        _collect_fs_probes,
        str(snapshot["extension_version"]),
    )
    connected = bool(snapshot["connected"])
    bridge_check = {
        "name": "extension_bridge",
        "passed": connected,
        "status": "passed" if connected else "pending",
        "code": "bridge_connected" if connected else BRIDGE_DISCONNECTED,
        "message": (
            "Native Messaging bridge is connected."
            if connected
            else "Native Messaging bridge is not connected."
        ),
        "repair_action": "none" if connected else "reload_extension",
        "metadata": {"ws_url": ws_url},
    }
    probes = [
        *fs_probes,
        probe_bridge_lifecycle(snapshot),
        probe_contract_drift(
            {
                "contract": snapshot.get("extension_contract", {}),
                "build": snapshot.get("extension_build", {}),
            },
        ),
    ]
    result = {
        "status": "pending",
        "checked_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((perf_counter() - started) * 1000, 3),
        "checks": [bridge_check, *probes],
    }
    bridge.record_self_test(result)
    return result


async def run_self_test() -> dict[str, Any]:
    """Collect the read-only bridge diagnosis for the async route."""
    return await collect_self_test_async()


def chrome_connection_status() -> dict[str, Any]:
    """Return connection state; installation state remains in the plugin."""
    snapshot = _snapshot()
    connected = bool(snapshot["connected"])
    contract_health = probe_contract_drift(
        {
            "contract": snapshot.get("extension_contract", {}),
            "build": snapshot.get("extension_build", {}),
        },
    )
    return {
        "connected": connected,
        "connected_since": (
            _iso_or_none(snapshot["connected_since"]) if connected else None
        ),
        "extension_version": (
            str(snapshot["extension_version"]) if connected else ""
        ),
        "bridge_lifecycle": _bridge_lifecycle(snapshot),
        "last_extension_disconnect": snapshot.get(
            "last_extension_disconnect",
            {},
        ),
        "contract_health": contract_health,
        "last_self_test": snapshot["last_self_test"],
        "readiness_state": "ready" if connected else "blocked",
        "backend": {
            "identity_config": load_config().browser.identity,
            "chrome_available": connected,
        },
    }


@status_router.get("/status")
async def _status() -> dict[str, Any]:
    return chrome_connection_status()


@status_router.post("/self-test")
async def _self_test() -> dict[str, Any]:
    return await run_self_test()


@status_router.get("/traces")
async def _traces(
    session_id: str = "",
    limit: int = Query(default=100, ge=0, le=1000),
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "limit": limit,
        "events": [],
        **_pending_semantic_control(
            "Semantic browser trace collection is not integrated yet.",
        ),
    }
