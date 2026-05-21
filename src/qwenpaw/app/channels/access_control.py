# -*- coding: utf-8 -*-
"""Unified access control store for channel whitelist/blacklist management.

Persists per-channel whitelist, blacklist, and pending approval entries
to a JSON file under the working directory.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)

ACCESS_CONTROL_FILE = "access_control.json"


class PendingEntry:
    """A user who messaged the bot but is not yet on any list."""

    __slots__ = ("user_id", "channel", "timestamp", "first_message", "remark")

    def __init__(
        self,
        user_id: str,
        channel: str,
        timestamp: float,
        first_message: str = "",
        remark: str = "",
    ):
        self.user_id = user_id
        self.channel = channel
        self.timestamp = timestamp
        self.first_message = first_message
        self.remark = remark

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "channel": self.channel,
            "timestamp": self.timestamp,
            "first_message": self.first_message,
            "remark": self.remark,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PendingEntry:
        return cls(
            user_id=data["user_id"],
            channel=data["channel"],
            timestamp=data.get("timestamp", 0.0),
            first_message=data.get("first_message", ""),
            remark=data.get("remark", ""),
        )


class ChannelACL:
    """Access control data for a single channel.

    whitelist / blacklist are stored as Dict[str, str] mapping
    user_id -> remark for human-readable identification.
    """

    def __init__(
        self,
        whitelist: Optional[Dict[str, str]] = None,
        blacklist: Optional[Dict[str, str]] = None,
        pending: Optional[List[PendingEntry]] = None,
    ):
        self.whitelist: Dict[str, str] = whitelist or {}
        self.blacklist: Dict[str, str] = blacklist or {}
        self.pending: List[PendingEntry] = pending or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "whitelist": self.whitelist,
            "blacklist": self.blacklist,
            "pending": [p.to_dict() for p in self.pending],
        }

    @classmethod
    def _parse_list_or_dict(cls, raw: Any) -> Dict[str, str]:
        """Parse whitelist/blacklist — supports legacy list format."""
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        if isinstance(raw, list):
            # Legacy format: ["user1", "user2"] -> {"user1": "", "user2": ""}
            return {str(item): "" for item in raw}
        return {}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChannelACL:
        return cls(
            whitelist=cls._parse_list_or_dict(data.get("whitelist", {})),
            blacklist=cls._parse_list_or_dict(data.get("blacklist", {})),
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

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {k: v.to_dict() for k, v in self._data.items()}
            self._path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._last_mtime = self._path.stat().st_mtime
        except Exception:
            logger.exception(
                "Failed to save access control data to %s",
                self._path,
            )

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
    ) -> None:
        with self._lock:
            acl = self._acl(channel)
            acl.whitelist[user_id] = remark
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
            # Preserve existing remarks for users that stay
            new_wl = {uid: acl.whitelist.get(uid, "") for uid in user_ids}
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
                acl.whitelist[user_id] = remark
                self._save()
                return True
            if user_id in acl.blacklist:
                acl.blacklist[user_id] = remark
                self._save()
                return True
            return False

    # ── Blacklist ───────────────────────────────────────────────────────

    def add_to_blacklist(
        self,
        channel: str,
        user_id: str,
        remark: str = "",
    ) -> None:
        with self._lock:
            acl = self._acl(channel)
            acl.blacklist[user_id] = remark
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
            new_bl = {uid: acl.blacklist.get(uid, "") for uid in user_ids}
            acl.blacklist = new_bl
            self._save()

    # ── Pending ─────────────────────────────────────────────────────────

    def add_pending(
        self,
        channel: str,
        user_id: str,
        first_message: str = "",
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
        """
        with self._lock:
            acl = self._acl(channel)
            # Find existing remark from pending entry as fallback
            effective_remark = remark
            if not effective_remark:
                for entry in acl.pending:
                    if entry.user_id == user_id and entry.channel == channel:
                        effective_remark = entry.remark
                        break
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            acl.whitelist[user_id] = effective_remark
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
        """
        with self._lock:
            acl = self._acl(channel)
            effective_remark = remark
            if not effective_remark:
                for entry in acl.pending:
                    if entry.user_id == user_id and entry.channel == channel:
                        effective_remark = entry.remark
                        break
            acl.pending = [
                p
                for p in acl.pending
                if not (p.user_id == user_id and p.channel == channel)
            ]
            acl.blacklist[user_id] = effective_remark
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
    ) -> None:
        """Import a set of user IDs into the whitelist for a channel.

        Called by the one-time startup migration. Does NOT check whether
        the file already existed — that guard lives in the migration caller.
        """
        if not allow_from:
            return
        with self._lock:
            acl = self._acl(channel)
            for uid in allow_from:
                if uid not in acl.whitelist:
                    acl.whitelist[uid] = ""
            self._save()
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
