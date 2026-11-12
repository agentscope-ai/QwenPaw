# -*- coding: utf-8 -*-
"""One-time host attestation for otherwise unowned Azure conversation refs."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import uuid

from .install_lock import InstallLockError
from .legacy_capture import capture_once, read_json_snapshot as _snapshot

_INVALID = "AZURE_LEGACY_CAPTURE_INVALID"
_OWNER_KEYS = {"workspace_dir", "app_id", "tenant_id"}
_AUTH_KEYS = {"schema_version", "capture_id", "owner", "refs_sha256"}
_EMPTY_CAPTURE = "0" * 32


class AzureLegacyError(ValueError):
    """Fixed diagnostics without configuration, routes or credential values."""


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8"),
    ).hexdigest()


def _hex(value, length):
    return (
        isinstance(value, str)
        and len(value) == length
        and all(char in "0123456789abcdef" for char in value)
    )


def _owner_valid(owner):
    return (
        isinstance(owner, dict)
        and set(owner) == _OWNER_KEYS
        and all(isinstance(value, str) and value for value in owner.values())
        and Path(owner["workspace_dir"]).is_absolute()
        and str(Path(owner["workspace_dir"]).resolve())
        == owner["workspace_dir"]
    )


def _manifest_path(root):
    return Path(root) / "channel_state" / "azure_bot" / "legacy-capture.json"


def _validate(capture):
    if (
        not isinstance(capture, Mapping)
        or set(capture)
        != {
            "schema_version",
            "capture_id",
            "entries",
            "unresolved",
        }
        or type(capture["schema_version"]) is not int
        or capture["schema_version"] != 1
        or not _hex(capture["capture_id"], 32)
        or not isinstance(capture["entries"], list)
        or not isinstance(capture["unresolved"], list)
    ):
        raise AzureLegacyError(_INVALID)
    owners = []
    for entry in capture["entries"]:
        if (
            not isinstance(entry, dict)
            or set(entry)
            != {
                "owner",
                "source",
                "config_source",
                "refs",
                "refs_sha256",
            }
            or not _owner_valid(entry["owner"])
            or entry["owner"] in owners
            or not isinstance(entry["refs"], dict)
            or any(
                not isinstance(key, str) or not isinstance(route, dict)
                for key, route in entry["refs"].items()
            )
            or entry["refs_sha256"] != _digest(entry["refs"])
        ):
            raise AzureLegacyError(_INVALID)
        owners.append(entry["owner"])
        for key in ("source", "config_source"):
            source = entry[key]
            if (
                not isinstance(source, dict)
                or set(source) != {"path", "sha256"}
                or not isinstance(source["path"], str)
                or not Path(source["path"]).is_absolute()
                or not _hex(source["sha256"], 64)
            ):
                raise AzureLegacyError(_INVALID)
    for item in capture["unresolved"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"reason_code", "source_path", "workspace_dir"}
            or item["reason_code"] != "AZURE_LEGACY_OWNER_UNVERIFIED"
            or not isinstance(item["source_path"], str)
            or not Path(item["source_path"]).is_absolute()
            or (
                item["workspace_dir"] is not None
                and (
                    not isinstance(item["workspace_dir"], str)
                    or not Path(item["workspace_dir"]).is_absolute()
                )
            )
        ):
            raise AzureLegacyError(_INVALID)
    return capture


def load_azure_legacy(*, legacy_state_dir: Path) -> dict | None:
    """Read the fixed capture only; never reinterpret later legacy files."""
    try:
        snapshot = _snapshot(_manifest_path(legacy_state_dir))
        return None if snapshot is None else dict(_validate(snapshot[0]))
    except (OSError, ValueError, TypeError, RecursionError):
        raise AzureLegacyError(_INVALID) from None


def _account(data, workspace):
    channels = data.get("channels")
    account = channels.get("azure_bot") if isinstance(channels, dict) else None
    if not isinstance(account, dict) or not account.get("app_id"):
        return None
    owner = {
        "workspace_dir": str(workspace),
        "app_id": account["app_id"],
        "tenant_id": account.get("tenant_id") or "botframework.com",
    }
    return owner if _owner_valid(owner) else None


def capture_azure_legacy(
    *,
    config_path: Path,
    legacy_state_dir: Path,
    working_dir: Path,
) -> dict:
    """Capture persisted old account/workspace attribution exactly once."""

    def absolute(value):
        path = Path(value).expanduser()
        return (path if path.is_absolute() else working_dir / path).resolve()

    try:
        root = absolute(legacy_state_dir)
        path = _manifest_path(root)

        def build():
            global_snapshot = _snapshot(absolute(config_path))
            capture = {
                "schema_version": 1,
                "capture_id": uuid.uuid4().hex,
                "entries": [],
                "unresolved": [],
            }
            if global_snapshot is not None:
                _capture_sources(capture, global_snapshot, root, absolute)
            elif (root / "azure_bot_refs.json").exists():
                capture["unresolved"].append(
                    {
                        "reason_code": "AZURE_LEGACY_OWNER_UNVERIFIED",
                        "source_path": str(
                            (root / "azure_bot_refs.json").resolve(),
                        ),
                        "workspace_dir": None,
                    },
                )
            _validate(capture)
            return capture

        return capture_once(
            path,
            load=lambda: load_azure_legacy(legacy_state_dir=root),
            build=build,
        )
    except InstallLockError:
        raise AzureLegacyError("AZURE_LEGACY_CAPTURE_UNAVAILABLE") from None
    except (OSError, ValueError, TypeError, RecursionError):
        raise AzureLegacyError(_INVALID) from None


def _capture_sources(capture, global_snapshot, root, absolute):
    raw, global_source, _ = global_snapshot
    agents = raw.get("agents", {})
    if not isinstance(agents, dict):
        raise AzureLegacyError(_INVALID)
    profiles = agents.get(
        "profiles",
        {
            "default": {
                "workspace_dir": str(root / "workspaces" / "default"),
            },
        },
    )
    if not isinstance(profiles, dict):
        raise AzureLegacyError(_INVALID)
    candidates = []
    global_refs = root / "azure_bot_refs.json"
    global_selected = False
    for key, profile in profiles.items():
        if not isinstance(profile, dict) or not profile.get("workspace_dir"):
            continue
        workspace = absolute(profile["workspace_dir"])
        local_config = _snapshot(workspace / "agent.json")
        # The old missing-agent.json fallback inherited global channels.
        data, config_source, _ = local_config or global_snapshot
        owner = _account(data, workspace)
        source = workspace / "azure_bot_refs.json"
        if not source.exists() and key == "default":
            source = global_refs
            global_selected = True
            if owner != _account(raw, workspace):
                owner = None
            config_source = global_source
        refs = _snapshot(source)
        if refs is not None:
            candidates.append((owner, refs, config_source, str(workspace)))
    if global_refs.exists() and not global_selected:
        capture["unresolved"].append(
            {
                "reason_code": "AZURE_LEGACY_OWNER_UNVERIFIED",
                "source_path": str(global_refs.resolve()),
                "workspace_dir": None,
            },
        )
    for owner, snapshot, config_source, workspace in candidates:
        refs, source, identity = snapshot
        competing = [row[0] for row in candidates if row[1][2] == identity]
        if owner is None or any(other != owner for other in competing):
            capture["unresolved"].append(
                {
                    "reason_code": "AZURE_LEGACY_OWNER_UNVERIFIED",
                    "source_path": source["path"],
                    "workspace_dir": workspace,
                },
            )
        elif not any(row["owner"] == owner for row in capture["entries"]):
            capture["entries"].append(
                {
                    "owner": owner,
                    "source": source,
                    "config_source": config_source,
                    "refs": refs,
                    "refs_sha256": _digest(refs),
                },
            )


def project_azure_legacy(capture: Mapping | None, owner: dict) -> dict:
    """Select bounded launch authority; the snapshot never enters launch JSON."""
    try:
        if capture is None:
            return {
                "schema_version": 1,
                "capture_id": _EMPTY_CAPTURE,
                "owner": None,
                "refs_sha256": _digest({}),
            }
        _validate(capture)
        match = next(
            (row for row in capture["entries"] if row["owner"] == owner),
            None,
        )
        return {
            "schema_version": 1,
            "capture_id": capture["capture_id"],
            "owner": dict(owner) if match else None,
            "refs_sha256": match["refs_sha256"] if match else _digest({}),
        }
    except (ValueError, TypeError, RecursionError):
        raise AzureLegacyError(_INVALID) from None


def select_azure_legacy(
    capture: Mapping | None,
    authorization: Mapping,
    owner: dict,
):
    """Verify host authorization against the fixed captured snapshot."""
    try:
        if (
            not isinstance(authorization, Mapping)
            or set(authorization) != _AUTH_KEYS
            or type(authorization["schema_version"]) is not int
            or authorization["schema_version"] != 1
            or not _hex(authorization["refs_sha256"], 64)
        ):
            raise AzureLegacyError(_INVALID)
        if capture is None:
            if authorization != project_azure_legacy(None, owner):
                raise AzureLegacyError(_INVALID)
            return {}
        _validate(capture)
        if authorization["capture_id"] != capture["capture_id"]:
            raise AzureLegacyError(_INVALID)
        if authorization["owner"] is None:
            if authorization["refs_sha256"] != _digest({}):
                raise AzureLegacyError(_INVALID)
            return {}
        if authorization["owner"] != owner:
            raise AzureLegacyError("AZURE_STATE_OWNER_CONFLICT")
        selected = project_azure_legacy(capture, owner)
        if selected != authorization:
            raise AzureLegacyError(_INVALID)
        return next(
            dict(row["refs"])
            for row in capture["entries"]
            if row["owner"] == owner
        )
    except AzureLegacyError:
        raise
    except (ValueError, TypeError, RecursionError, StopIteration):
        raise AzureLegacyError(_INVALID) from None
