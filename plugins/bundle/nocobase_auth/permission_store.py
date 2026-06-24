# -*- coding: utf-8 -*-
"""Local permission cache synced from NocoBase."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from qwenpaw.constant import WORKING_DIR

logger = logging.getLogger(__name__)

PERMISSION_STORE_FILE = "nocobase_permissions.json"


class PermissionStore:
    """Thread-safe JSON cache of NocoBase user permissions.

    Mirrors NocoBase users/roles so channel access decisions can be made
    locally without hitting NocoBase on every message.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or WORKING_DIR / PERMISSION_STORE_FILE
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = self._default_data()
        self._last_mtime: float = 0.0
        self._load()

    @staticmethod
    def _default_data() -> Dict[str, Any]:
        return {
            "users": {},  # sender_id -> {id, email, nickname, roles}
            "roles": {},  # role_name -> {id, title}
            "role_channel_map": {},  # role_name -> {allowed: [], denied: []}
            "last_sync_at": 0.0,
            "last_sync_error": "",
        }

    # ── Persistence ─────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            self._last_mtime = self._path.stat().st_mtime
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {**self._default_data(), **raw}
            else:
                logger.warning(
                    "Permission store has invalid format; resetting",
                )
                self._data = self._default_data()
        except Exception:
            logger.exception(
                "Failed to load permission store from %s",
                self._path,
            )
            self._data = self._default_data()

    def _reload_if_stale(self) -> None:
        try:
            if not self._path.exists():
                return
            current_mtime = self._path.stat().st_mtime
            if current_mtime > self._last_mtime:
                self._load()
        except OSError:
            pass

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass
            self._last_mtime = self._path.stat().st_mtime
        except Exception:
            logger.exception(
                "Failed to save permission store to %s",
                self._path,
            )

    # ── Public API ──────────────────────────────────────────────────────

    def update_from_sync(
        self,
        users: List[Dict[str, Any]],
        roles: List[Dict[str, Any]],
        role_channel_map: Optional[Dict[str, Dict[str, List[str]]]] = None,
        error: str = "",
    ) -> None:
        """Replace cached users/roles after a successful sync.

        Note: we intentionally do NOT call ``_reload_if_stale`` here.
        Concurrent writers within the same process should build on the
        current in-memory state rather than overwrite it with a possibly
        stale on-disk snapshot.
        """
        with self._lock:
            self._data["users"] = {
                str(user.get("sender_id", "")): user
                for user in users
                if user.get("sender_id")
            }
            self._data["roles"] = {
                str(role.get("name", "")): role
                for role in roles
                if role.get("name")
            }
            if role_channel_map is not None:
                self._data["role_channel_map"] = role_channel_map
            self._data["last_sync_at"] = time.time()
            self._data["last_sync_error"] = error
            self._save()

    def get_user(self, sender_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._reload_if_stale()
            return self._data["users"].get(sender_id)

    def get_role_channel_map(self) -> Dict[str, Dict[str, List[str]]]:
        with self._lock:
            self._reload_if_stale()
            return dict(self._data.get("role_channel_map", {}))

    def set_role_channel_map(
        self,
        role_channel_map: Dict[str, Dict[str, List[str]]],
    ) -> None:
        with self._lock:
            self._reload_if_stale()
            self._data["role_channel_map"] = role_channel_map
            self._save()

    def list_users(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._reload_if_stale()
            return list(self._data["users"].values())

    def list_roles(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._reload_if_stale()
            return list(self._data["roles"].values())

    def get_last_sync_status(self) -> Dict[str, Any]:
        with self._lock:
            self._reload_if_stale()
            return {
                "last_sync_at": self._data.get("last_sync_at", 0.0),
                "last_sync_error": self._data.get("last_sync_error", ""),
                "user_count": len(self._data.get("users", {})),
                "role_count": len(self._data.get("roles", {})),
            }

    def clear(self) -> None:
        with self._lock:
            self._data = self._default_data()
            self._save()

    # ── Permission evaluation ───────────────────────────────────────────

    def is_channel_allowed(
        self,
        sender_id: str,
        channel_key: str,
    ) -> Optional[bool]:
        """Return True/False if NocoBase has an opinion, None otherwise.

        - User not in cache -> None (fall through to native ACL).
        - Any role explicitly denies the channel -> False.
        - Any role explicitly allows the channel -> True.
        - No role mentions the channel -> None (fall through).
        """
        user = self.get_user(sender_id)
        if user is None:
            return None

        role_map = self.get_role_channel_map()
        allowed = False
        denied = False

        for role_name in user.get("roles", []):
            mapping = role_map.get(role_name)
            if not mapping:
                continue
            if channel_key in mapping.get("denied", []):
                denied = True
            if channel_key in mapping.get("allowed", []):
                allowed = True

        # Deny takes precedence over allow.
        if denied:
            return False
        if allowed:
            return True
        return None
