# -*- coding: utf-8 -*-
"""Unified access control store for channel whitelist/blacklist management.

Persists per-channel whitelist, blacklist, and pending approval entries
to a JSON file under the working directory.
"""
from __future__ import annotations

import copy
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ...constant import WORKING_DIR
from ...utils.io_utils import write_json_atomic

logger = logging.getLogger(__name__)

ACCESS_CONTROL_FILE = "access_control.json"
_MIGRATION_SOURCE_KEY = "_migration_source"
_MIGRATION_TARGET_KEY = "_migration_target"


class PendingEntry:
    """A user who messaged the bot but is not yet on any list."""

    __slots__ = (
        "user_id",
        "channel",
        "timestamp",
        "first_message",
        "remark",
        "username",
    )

    def __init__(
        self,
        user_id: str,
        channel: str,
        timestamp: float,
        first_message: str = "",
        remark: str = "",
        username: str = "",
    ):
        self.user_id = user_id
        self.channel = channel
        self.timestamp = timestamp
        self.first_message = first_message
        self.remark = remark
        self.username = username

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "channel": self.channel,
            "timestamp": self.timestamp,
            "first_message": self.first_message,
            "remark": self.remark,
            "username": self.username,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PendingEntry:
        return cls(
            user_id=data["user_id"],
            channel=data["channel"],
            timestamp=data.get("timestamp", 0.0),
            first_message=data.get("first_message", ""),
            remark=data.get("remark", ""),
            username=data.get("username", ""),
        )


class UserInfo:
    """Per-user metadata stored in whitelist/blacklist."""

    __slots__ = (
        "remark",
        "username",
        "migration_source",
        "migration_target",
    )

    def __init__(
        self,
        remark: str = "",
        username: str = "",
        migration_source: str = "",
        migration_target: str = "",
    ):
        self.remark = remark
        self.username = username
        self.migration_source = migration_source
        self.migration_target = migration_target

    def to_dict(self) -> Dict[str, str]:
        payload = {"remark": self.remark, "username": self.username}
        if self.migration_source:
            payload[_MIGRATION_SOURCE_KEY] = self.migration_source
        if self.migration_target:
            payload[_MIGRATION_TARGET_KEY] = self.migration_target
        return payload

    @classmethod
    def from_dict(cls, data: Any) -> UserInfo:
        if isinstance(data, dict):
            return cls(
                remark=str(data.get("remark", "")),
                username=str(data.get("username", "")),
                migration_source=str(data.get(_MIGRATION_SOURCE_KEY, "")),
                migration_target=str(data.get(_MIGRATION_TARGET_KEY, "")),
            )
        # Legacy format: plain string = remark only
        return cls(remark=str(data) if data else "")


# Type alias for whitelist / blacklist: user_id -> UserInfo
UserMap = Dict[str, UserInfo]


class ChannelACL:
    """Access control data for a single channel.

    whitelist / blacklist map user_id -> UserInfo (remark + username).
    """

    def __init__(
        self,
        whitelist: Optional[UserMap] = None,
        blacklist: Optional[UserMap] = None,
        pending: Optional[List[PendingEntry]] = None,
    ):
        self.whitelist: UserMap = whitelist or {}
        self.blacklist: UserMap = blacklist or {}
        self.pending: List[PendingEntry] = pending or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "whitelist": {k: v.to_dict() for k, v in self.whitelist.items()},
            "blacklist": {k: v.to_dict() for k, v in self.blacklist.items()},
            "pending": [p.to_dict() for p in self.pending],
        }

    @classmethod
    def _parse_user_map(cls, raw: Any) -> UserMap:
        """Parse whitelist/blacklist with backward compatibility.

        Supported formats:
        - dict with string values (legacy): {"user1": "remark"}
        - dict with dict values (current):
          {"user1": {"remark": "", "username": ""}}
        """
        if isinstance(raw, list):
            return {str(item): UserInfo() for item in raw}
        if not isinstance(raw, dict):
            return {}
        result: UserMap = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                result[str(key)] = UserInfo.from_dict(value)
            else:
                result[str(key)] = UserInfo(
                    remark=str(value) if value else "",
                )
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChannelACL:
        return cls(
            whitelist=cls._parse_user_map(data.get("whitelist", {})),
            blacklist=cls._parse_user_map(data.get("blacklist", {})),
            pending=[
                PendingEntry.from_dict(p) for p in data.get("pending", [])
            ],
        )


class AccessControlStore:
    """Thread-safe persistent store for per-channel access control lists."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or WORKING_DIR / ACCESS_CONTROL_FILE
        self._lock = threading.Lock()
        self._data: Dict[str, ChannelACL] = {}
        self._last_mtime: float = 0.0
        self._load()

    # ── Persistence ─────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            self._last_mtime = self._path.stat().st_mtime
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._data = {k: ChannelACL.from_dict(v) for k, v in raw.items()}
        except Exception:
            logger.exception(
                "Failed to load access control data from %s",
                self._path,
            )

    def _reload_if_stale(self) -> None:
        """Reload from disk if the file was updated since last load.

        Needed because workspace hot-reload may re-create the store while
        channels continue to write via a previous reference.
        """
        try:
            if not self._path.exists():
                return
            current_mtime = self._path.stat().st_mtime
            if current_mtime > self._last_mtime:
                self._load()
        except OSError:
            pass

    def _save(self) -> bool:
        try:
            payload = {k: v.to_dict() for k, v in self._data.items()}
            write_json_atomic(self._path, payload)
            self._last_mtime = self._path.stat().st_mtime
            return True
        except Exception:
            logger.exception(
                "Failed to save access control data to %s",
                self._path,
            )
            return False

    def _acl(self, channel: str) -> ChannelACL:
        if channel not in self._data:
            self._data[channel] = ChannelACL()
        return self._data[channel]

    # ── Query ───────────────────────────────────────────────────────────

    def is_whitelisted(self, channel: str, user_id: str) -> bool:
        with self._lock:
            self._reload_if_stale()
            return user_id in self._acl(channel).whitelist

    def is_blacklisted(self, channel: str, user_id: str) -> bool:
        with self._lock:
            self._reload_if_stale()
            return user_id in self._acl(channel).blacklist

    def get_acl(self, channel: str) -> Dict[str, Any]:
        with self._lock:
            self._reload_if_stale()
            return self._acl(channel).to_dict()

    def get_all_acls(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            self._reload_if_stale()
            return {k: v.to_dict() for k, v in self._data.items()}

    # ── Whitelist ───────────────────────────────────────────────────────

    def add_to_whitelist(
        self,
        channel: str,
        user_id: str,
        remark: str = "",
        username: str = "",
    ) -> None:
        with self._lock:
            acl = self._acl(channel)
            existing = acl.whitelist.get(user_id)
            acl.whitelist[user_id] = UserInfo(
                remark=remark or (existing.remark if existing else ""),
                username=username or (existing.username if existing else ""),
            )
            acl.blacklist.pop(user_id, None)
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            self._save()

    def remove_from_whitelist(self, channel: str, user_id: str) -> None:
        with self._lock:
            self._acl(channel).whitelist.pop(user_id, None)
            self._save()

    def set_whitelist(self, channel: str, user_ids: List[str]) -> None:
        with self._lock:
            acl = self._acl(channel)
            new_wl = {
                uid: acl.whitelist.get(uid, UserInfo()) for uid in user_ids
            }
            acl.whitelist = new_wl
            self._save()

    def update_remark(
        self,
        channel: str,
        user_id: str,
        remark: str,
    ) -> bool:
        """Update the remark for a user in whitelist or blacklist."""
        with self._lock:
            acl = self._acl(channel)
            if user_id in acl.whitelist:
                acl.whitelist[user_id].remark = remark
                self._save()
                return True
            if user_id in acl.blacklist:
                acl.blacklist[user_id].remark = remark
                self._save()
                return True
            return False

    def update_username(
        self,
        channel: str,
        user_id: str,
        username: str,
    ) -> bool:
        """Update the username for a user (whitelist, blacklist or pending)."""
        with self._lock:
            acl = self._acl(channel)
            found = False
            if user_id in acl.whitelist:
                acl.whitelist[user_id].username = username
                found = True
            if user_id in acl.blacklist:
                acl.blacklist[user_id].username = username
                found = True
            for entry in acl.pending:
                if entry.user_id == user_id and entry.channel == channel:
                    entry.username = username
                    found = True
            if not found:
                return False
            self._save()
            return True

    # ── Blacklist ───────────────────────────────────────────────────────

    def add_to_blacklist(
        self,
        channel: str,
        user_id: str,
        remark: str = "",
        username: str = "",
    ) -> None:
        with self._lock:
            acl = self._acl(channel)
            existing = acl.blacklist.get(user_id)
            acl.blacklist[user_id] = UserInfo(
                remark=remark or (existing.remark if existing else ""),
                username=username or (existing.username if existing else ""),
            )
            acl.whitelist.pop(user_id, None)
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            self._save()

    def remove_from_blacklist(self, channel: str, user_id: str) -> None:
        with self._lock:
            self._acl(channel).blacklist.pop(user_id, None)
            self._save()

    def set_blacklist(self, channel: str, user_ids: List[str]) -> None:
        with self._lock:
            acl = self._acl(channel)
            new_bl = {
                uid: acl.blacklist.get(uid, UserInfo()) for uid in user_ids
            }
            acl.blacklist = new_bl
            self._save()

    # ── Pending ─────────────────────────────────────────────────────────

    def add_pending(
        self,
        channel: str,
        user_id: str,
        first_message: str = "",
        username: str = "",
    ) -> None:
        with self._lock:
            acl = self._acl(channel)
            for existing in acl.pending:
                if existing.user_id == user_id and existing.channel == channel:
                    return
            acl.pending.append(
                PendingEntry(
                    user_id=user_id,
                    channel=channel,
                    timestamp=time.time(),
                    first_message=first_message[:200],
                    username=username,
                ),
            )
            self._save()

    def get_all_pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            result: List[Dict[str, Any]] = []
            for acl in self._data.values():
                result.extend(p.to_dict() for p in acl.pending)
            result.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            return result

    def update_pending_remark(
        self,
        channel: str,
        user_id: str,
        remark: str,
    ) -> bool:
        """Update the remark on a pending entry. Returns True if found."""
        with self._lock:
            acl = self._acl(channel)
            for entry in acl.pending:
                if entry.user_id == user_id and entry.channel == channel:
                    entry.remark = remark
                    self._save()
                    return True
            return False

    def approve_pending(
        self,
        channel: str,
        user_id: str,
        remark: str = "",
    ) -> bool:
        """Move a pending user to the whitelist.

        If no remark is provided, carry over the remark from the pending entry.
        Username is always carried over from the pending entry.
        """
        with self._lock:
            acl = self._acl(channel)
            effective_remark = remark
            username = ""
            for entry in acl.pending:
                if entry.user_id == user_id and entry.channel == channel:
                    if not effective_remark:
                        effective_remark = entry.remark
                    username = entry.username
                    break
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            acl.whitelist[user_id] = UserInfo(
                remark=effective_remark,
                username=username,
            )
            acl.blacklist.pop(user_id, None)
            self._save()
            return True

    def deny_pending(
        self,
        channel: str,
        user_id: str,
        remark: str = "",
    ) -> bool:
        """Move a pending user to the blacklist.

        If no remark is provided, carry over the remark from the pending entry.
        Username is always carried over from the pending entry.
        """
        with self._lock:
            acl = self._acl(channel)
            effective_remark = remark
            username = ""
            for entry in acl.pending:
                if entry.user_id == user_id and entry.channel == channel:
                    if not effective_remark:
                        effective_remark = entry.remark
                    username = entry.username
                    break
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            acl.blacklist[user_id] = UserInfo(
                remark=effective_remark,
                username=username,
            )
            acl.whitelist.pop(user_id, None)
            self._save()
            return True

    def dismiss_pending(self, channel: str, user_id: str) -> bool:
        """Remove from pending without adding to any list."""
        with self._lock:
            acl = self._acl(channel)
            before = len(acl.pending)
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            if len(acl.pending) < before:
                self._save()
                return True
            return False

    # ── Migration ───────────────────────────────────────────────────────

    def import_allow_from(
        self,
        channel: str,
        allow_from: Set[str],
        source_revision: str = "",
    ) -> None:
        """Import a set of user IDs into the whitelist for a channel.

        Called by the one-time startup migration. Does NOT check whether
        the file already existed — that guard lives in the migration caller.
        """
        if not allow_from:
            return
        with self._lock:
            original_data = copy.deepcopy(self._data)
            acl = self._acl(channel)
            for uid in allow_from:
                if uid not in acl.whitelist:
                    acl.whitelist[uid] = UserInfo(
                        migration_source=source_revision,
                    )
            _persist_migration(self, original_data, "persist")
            logger.info(
                "Imported %d allow_from entries to whitelist for channel %s",
                len(allow_from),
                channel,
            )


# Per-workspace store registry keyed by resolved workspace directory path.
_stores: Dict[str, AccessControlStore] = {}
_stores_lock = threading.Lock()


def init_access_control_store(
    workspace_dir: Optional[Path] = None,
) -> AccessControlStore:
    """Create or get the store for a workspace directory."""
    with _stores_lock:
        if workspace_dir:
            key = str(workspace_dir.resolve())
        else:
            key = str(Path(WORKING_DIR).resolve())
        if key not in _stores:
            path = Path(key) / ACCESS_CONTROL_FILE
            _stores[key] = AccessControlStore(path)
        return _stores[key]


def get_access_control_store(
    workspace_dir: Optional[Path] = None,
) -> AccessControlStore:
    """Get (or create) the AccessControlStore for a workspace.

    Args:
        workspace_dir: Workspace directory. If None, uses WORKING_DIR fallback.
    """
    return init_access_control_store(workspace_dir)


def _persist_migration(
    store: AccessControlStore,
    original_data: Dict[str, ChannelACL],
    action: str,
) -> None:
    """Persist a migration change or restore its in-memory state."""
    if store._save():  # pylint: disable=protected-access
        return
    store._data = original_data  # pylint: disable=protected-access
    raise OSError(
        f"Failed to {action} access control migration at "
        f"{store._path}",  # pylint: disable=protected-access
    )


def recover_allow_from_migration(
    store: AccessControlStore,
    current_revision: str,
) -> None:
    """Finalize or roll back interrupted legacy ACL imports."""
    with store._lock:  # pylint: disable=protected-access
        changes: List[Tuple[ChannelACL, str, Optional[UserInfo]]] = []
        for acl in store._data.values():  # pylint: disable=protected-access
            for user_id, info in list(acl.whitelist.items()):
                if not info.migration_source:
                    continue
                if info.migration_target == current_revision:
                    changes.append((acl, user_id, info))
                elif info.migration_source != current_revision:
                    changes.append((acl, user_id, None))
        if not changes:
            return
        original_data = copy.deepcopy(
            store._data,  # pylint: disable=protected-access
        )
        for acl, user_id, info in changes:
            if info is None:
                del acl.whitelist[user_id]
            else:
                info.migration_source = ""
                info.migration_target = ""
        _persist_migration(store, original_data, "recover")


def prepare_allow_from_migration(
    store: AccessControlStore,
    source_revision: str,
    target_revision: str,
) -> None:
    """Record the agent revision produced by pending ACL imports."""
    with store._lock:  # pylint: disable=protected-access
        pending = [
            info
            for acl in store._data.values()  # pylint: disable=protected-access
            for info in acl.whitelist.values()
            if info.migration_source == source_revision
        ]
        if not pending:
            return
        original_data = copy.deepcopy(
            store._data,  # pylint: disable=protected-access
        )
        for info in pending:
            info.migration_target = target_revision
        _persist_migration(store, original_data, "prepare")


def finalize_allow_from_migration(
    store: AccessControlStore,
    source_revision: str,
    target_revision: str,
) -> None:
    """Remove provenance after the agent config cleanup commits."""
    with store._lock:  # pylint: disable=protected-access
        pending = [
            info
            for acl in store._data.values()  # pylint: disable=protected-access
            for info in acl.whitelist.values()
            if info.migration_source == source_revision
            and info.migration_target == target_revision
        ]
        if not pending:
            return
        original_data = copy.deepcopy(
            store._data,  # pylint: disable=protected-access
        )
        for info in pending:
            info.migration_source = ""
            info.migration_target = ""
        _persist_migration(store, original_data, "finalize")
