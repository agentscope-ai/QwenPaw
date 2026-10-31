# -*- coding: utf-8 -*-
"""SDK-free, one-time attribution of Matrix's old global state directory."""

from collections.abc import Mapping
from pathlib import Path
import uuid

from .install_lock import InstallLockError
from .legacy_capture import capture_once, read_json_snapshot

_INVALID = "MATRIX_LEGACY_CAPTURE_INVALID"
_UNVERIFIED = "MATRIX_LEGACY_OWNER_UNVERIFIED"
_OWNER_KEYS = {"homeserver", "user_id", "device_id", "workspace_dir"}
_AUTH_KEYS = {"schema_version", "capture_id", "owner", "auth_sha256"}


class MatrixLegacyError(ValueError):
    """Fixed diagnostics without passwords, cached tokens or source contents."""


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
        and all(isinstance(value, str) for value in owner.values())
        and all(owner[key] for key in _OWNER_KEYS - {"device_id"})
        and Path(owner["workspace_dir"]).is_absolute()
        and str(Path(owner["workspace_dir"]).resolve())
        == owner["workspace_dir"]
        and owner["homeserver"] == owner["homeserver"].rstrip("/")
    )


def _path(root):
    return Path(root) / "channel_state" / "matrix" / "legacy-capture.json"


def _validate(capture):
    if (
        not isinstance(capture, Mapping)
        or set(capture) != _AUTH_KEYS | {"config_sources", "reason_code"}
        or type(capture["schema_version"]) is not int
        or capture["schema_version"] != 1
        or not _hex(capture["capture_id"], 32)
        or (
            capture["auth_sha256"] is not None
            and not _hex(capture["auth_sha256"], 64)
        )
        or (
            capture["owner"] is not None
            and (
                not _owner_valid(capture["owner"])
                or capture["auth_sha256"] is None
            )
        )
        or capture["reason_code"] not in (None, _UNVERIFIED)
        or not isinstance(capture["config_sources"], list)
    ):
        raise MatrixLegacyError(_INVALID)
    for source in capture["config_sources"]:
        if (
            not isinstance(source, dict)
            or set(source) != {"path", "sha256"}
            or not isinstance(source["path"], str)
            or not Path(source["path"]).is_absolute()
            or not _hex(source["sha256"], 64)
        ):
            raise MatrixLegacyError(_INVALID)
    return capture


def load_matrix_legacy(*, legacy_state_dir: Path) -> dict | None:
    """Read only the fixed capture; missing does not create a manifest."""
    try:
        snapshot = read_json_snapshot(_path(legacy_state_dir))
        return None if snapshot is None else dict(_validate(snapshot[0]))
    except (OSError, ValueError, TypeError, RecursionError):
        raise MatrixLegacyError(_INVALID) from None


def _capture(config_path, root, absolute):
    result = {
        "schema_version": 1,
        "capture_id": uuid.uuid4().hex,
        "owner": None,
        "auth_sha256": None,
        "config_sources": [],
        "reason_code": None,
    }
    auth = read_json_snapshot(root / "matrix_auth_state.json")
    if auth is None:
        if any(
            (root / name).exists()
            for name in ("matrix_sync_token", "matrix_crypto_store")
        ):
            result["reason_code"] = _UNVERIFIED
        return _validate(result)
    hint = auth[0]
    result["auth_sha256"] = auth[1]["sha256"]
    result["reason_code"] = _UNVERIFIED
    if (
        not isinstance(hint.get("user_id"), str)
        or not hint["user_id"]
        or not isinstance(hint.get("device_id", ""), str)
    ):
        return _validate(result)
    config = read_json_snapshot(config_path)
    if config is None:
        return _validate(result)
    raw, source, _ = config
    result["config_sources"].append(source)
    agents = raw.get("agents", {})
    if not isinstance(agents, dict):
        raise MatrixLegacyError(_INVALID)
    profiles = agents.get(
        "profiles",
        {
            "default": {
                "workspace_dir": str(root / "workspaces" / "default"),
            },
        },
    )
    if not isinstance(profiles, dict):
        raise MatrixLegacyError(_INVALID)
    candidates = []
    for profile in profiles.values():
        if not isinstance(profile, dict) or not profile.get("workspace_dir"):
            continue
        workspace = absolute(profile["workspace_dir"])
        local = read_json_snapshot(workspace / "agent.json")
        data, provenance, _ = local or config
        if provenance not in result["config_sources"]:
            result["config_sources"].append(provenance)
        channels = data.get("channels")
        account = (
            channels.get("matrix") if isinstance(channels, dict) else None
        )
        if not isinstance(account, dict):
            continue
        server, user = account.get("homeserver", ""), account.get(
            "user_id",
            "",
        )
        if (
            not isinstance(server, str)
            or not server.rstrip("/")
            or not isinstance(user, str)
        ):
            continue
        user = user.strip()
        # A local login alias is not guessed into an MXID. It remains a
        # possible candidate and must later authenticate as the captured hint.
        if user.startswith("@") and ":" in user and user != hint["user_id"]:
            continue
        owner = {
            "homeserver": server.rstrip("/"),
            "user_id": hint["user_id"],
            "device_id": hint.get("device_id", ""),
            "workspace_dir": str(workspace),
        }
        if owner not in candidates:
            candidates.append(owner)
    if len(candidates) == 1:
        result["owner"] = candidates[0]
        result["reason_code"] = None
    return _validate(result)


def capture_matrix_legacy(
    *,
    config_path: Path,
    legacy_state_dir: Path,
    working_dir: Path,
) -> dict:
    """Bind historical homeserver/workspace once, before config migrations."""

    def absolute(value):
        path = Path(value).expanduser()
        return (path if path.is_absolute() else working_dir / path).resolve()

    try:
        root = absolute(legacy_state_dir)
        return capture_once(
            _path(root),
            load=lambda: load_matrix_legacy(legacy_state_dir=root),
            build=lambda: _capture(absolute(config_path), root, absolute),
        )
    except InstallLockError:
        raise MatrixLegacyError("MATRIX_LEGACY_CAPTURE_UNAVAILABLE") from None
    except (OSError, ValueError, TypeError, RecursionError):
        raise MatrixLegacyError(_INVALID) from None


def project_matrix_legacy(capture, *, homeserver, workspace_dir):
    """Produce bounded authority without reading the capture or old tokens."""
    try:
        if capture is None:
            return {
                "schema_version": 1,
                "capture_id": "0" * 32,
                "owner": None,
                "auth_sha256": None,
            }
        _validate(capture)
        owner = capture["owner"]
        matched = owner is not None and (
            owner["homeserver"] == homeserver.rstrip("/")
            and workspace_dir is not None
            and owner["workspace_dir"]
            == str(Path(workspace_dir).expanduser().resolve())
        )
        return {
            "schema_version": 1,
            "capture_id": capture["capture_id"],
            "owner": dict(owner) if matched else None,
            "auth_sha256": capture["auth_sha256"] if matched else None,
        }
    except (OSError, ValueError, TypeError, RecursionError):
        raise MatrixLegacyError(_INVALID) from None


def verify_matrix_legacy(capture, authorization, owner, *, legacy_state_dir):
    """Require live authenticated identity plus unchanged captured auth bytes."""
    try:
        if (
            not isinstance(authorization, Mapping)
            or set(authorization) != _AUTH_KEYS
            or type(authorization["schema_version"]) is not int
            or authorization["schema_version"] != 1
        ):
            raise MatrixLegacyError(_INVALID)
        expected = project_matrix_legacy(
            capture,
            homeserver=owner["homeserver"],
            workspace_dir=owner["workspace_dir"],
        )
        if authorization != expected:
            raise MatrixLegacyError(_UNVERIFIED)
        if authorization["owner"] is None:
            return False
        if authorization["owner"] != owner:
            raise MatrixLegacyError(_UNVERIFIED)
        auth = read_json_snapshot(
            Path(legacy_state_dir) / "matrix_auth_state.json",
        )
        if (
            auth is None
            or auth[1]["sha256"] != authorization["auth_sha256"]
            or any(
                auth[0].get(key, "") != owner[key]
                for key in ("user_id", "device_id")
            )
        ):
            raise MatrixLegacyError(_UNVERIFIED)
        return True
    except MatrixLegacyError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise MatrixLegacyError(_INVALID) from None
