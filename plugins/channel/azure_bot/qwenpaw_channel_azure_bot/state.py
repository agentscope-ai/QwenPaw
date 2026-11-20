# -*- coding: utf-8 -*-
"""Workspace/account-owned references; legacy files are read-only evidence."""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile

from qwenpaw.plugins.install_lock import plugin_install_lock
from qwenpaw.plugins.azure_legacy import (
    AzureLegacyError,
    load_azure_legacy,
    select_azure_legacy,
)


def _read(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("AZURE_STATE_INVALID")
    return value


class AzureBotStateStore:
    def __init__(self, config):
        if not config.get("workspace_dir"):
            raise ValueError("AZURE_WORKSPACE_REQUIRED")
        self.workspace = Path(config["workspace_dir"]).expanduser().resolve()
        self.owner = {
            "app_id": config["app_id"],
            "tenant_id": config.get("tenant_id") or "botframework.com",
            "workspace_dir": str(self.workspace),
        }
        scope = hashlib.sha256(
            json.dumps(self.owner, sort_keys=True).encode(),
        ).hexdigest()
        self.directory = self.workspace / "channel_state" / "azure_bot" / scope
        self._claims = ExitStack()
        self.refs = {}
        self.legacy = {}
        self.capture_id = None
        self.authorization = config.get("legacy_reference_owner")
        self.has_authorization = "legacy_reference_owner" in config
        self.legacy_state_dir = config.get("legacy_state_dir")
        self.legacy_paths = [self.workspace / "azure_bot_refs.json"]
        if config.get("legacy_state_dir"):
            self.legacy_paths.append(
                Path(config["legacy_state_dir"]) / "azure_bot_refs.json",
            )

    def begin(self):
        self._claims.enter_context(
            plugin_install_lock(self.directory / ".active.lock", timeout=0),
        )
        data = _read(self.directory / "refs.json")
        if data and data.get("owner") != self.owner:
            raise ValueError("AZURE_STATE_OWNER_CONFLICT")
        self.refs = dict(data.get("refs", {}))
        if self.has_authorization:
            if not self.legacy_state_dir:
                raise AzureLegacyError("AZURE_LEGACY_CAPTURE_INVALID")
            capture = load_azure_legacy(legacy_state_dir=self.legacy_state_dir)
            refs = select_azure_legacy(capture, self.authorization, self.owner)
            self.capture_id = (
                self.authorization["capture_id"]
                if capture is not None
                else None
            )
            if data.get("capture_id") not in (None, self.capture_id):
                raise AzureLegacyError("AZURE_STATE_OWNER_CONFLICT")
            if capture is not None and data.get("capture_id") is None:
                self.refs = {**refs, **self.refs}
                self.save()
        else:
            for path in reversed(self.legacy_paths):
                self.legacy.update(_read(path))

    def remember(self, target, route):
        """Only authenticated ingress can authorize an unowned legacy route."""
        for old_target, old in self.legacy.items():
            if isinstance(old, dict) and all(
                old.get(k) == route.get(k)
                for k in ("service_url", "conversation_id", "bot_channel_id")
            ):
                self.refs[old_target] = dict(route)
        self.refs[target] = dict(route)
        self.save()

    def save(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".refs-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                data = {"owner": self.owner, "refs": self.refs}
                if self.capture_id is not None:
                    data["capture_id"] = self.capture_id
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.directory / "refs.json")
        finally:
            Path(name).unlink(missing_ok=True)

    def resolve(self, target, meta):
        if target in self.refs:
            return dict(self.refs[target])
        session = target.split(":", 1)[0]
        group = self.refs.get(session)
        if group and group.get("is_group"):
            return dict(group)
        # Metadata cannot manufacture a trusted destination; match a route
        # already learned from an authenticated activity under this account.
        matches = [
            r
            for r in self.refs.values()
            if all(
                meta.get(k) and meta[k] == r.get(k)
                for k in ("service_url", "conversation_id", "bot_channel_id")
            )
        ]
        if matches:
            return dict(matches[0])
        raise ValueError("AZURE_ROUTE_UNAVAILABLE")

    def close(self):
        self._claims.close()
