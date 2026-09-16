# -*- coding: utf-8 -*-
"""Mail access control store for per-agent sender
whitelist/blacklist management.

Persists per-agent mail ACL (whitelist, blacklist, pending approval) entries
to a JSON file under the working directory.  Supports domain-wildcard entries
(e.g. ``*@example.com``) for bulk allow/deny by domain.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ...constant import WORKING_DIR
from ...utils.io_utils import write_json_atomic

logger = logging.getLogger(__name__)

MAIL_ACCESS_CONTROL_FILE = "mail_access_control.json"

# Regex for validating domain part after *@
_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)+$",
)

# Simple sanity check for plain (non-wildcard) email addresses.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailPendingEntry:
    """A sender who emailed the agent but is not yet on any list."""

    __slots__ = (
        "sender_address",
        "agent_id",
        "display_name",
        "subject",
        "body_preview",
        "timestamp",
        "remark",
        "uid",
        "date",
        "messages",
    )

    def __init__(
        self,
        sender_address: str,
        agent_id: str,
        display_name: str = "",
        subject: str = "",
        body_preview: str = "",
        timestamp: float = 0.0,
        remark: str = "",
        uid: int = 0,
        date: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ):
        self.sender_address = sender_address
        self.agent_id = agent_id
        self.display_name = display_name
        self.subject = subject
        self.body_preview = body_preview
        self.timestamp = timestamp
        self.remark = remark
        self.uid = uid
        self.date = date
        self.messages: List[Dict[str, Any]] = []
        if messages:
            for message in messages:
                if isinstance(message, dict):
                    self._append_message_dict(message)
        if not self.messages:
            # Backward compatibility: legacy entries stored only one message
            # in the sender-level fields.
            self.append_message(
                display_name=display_name,
                subject=subject,
                body_preview=body_preview,
                uid=uid,
                date=date,
                timestamp=timestamp,
            )

    def _append_message_dict(self, message: Dict[str, Any]) -> bool:
        try:
            uid = int(message.get("uid", 0) or 0)
        except (TypeError, ValueError):
            uid = 0
        try:
            timestamp = float(message.get("timestamp", 0.0) or 0.0)
        except (TypeError, ValueError):
            timestamp = 0.0
        return self.append_message(
            display_name=str(message.get("display_name", "")),
            subject=str(message.get("subject", "")),
            body_preview=str(message.get("body_preview", "")),
            uid=uid,
            date=str(message.get("date", "")),
            timestamp=timestamp,
        )

    def append_message(
        self,
        *,
        display_name: str = "",
        subject: str = "",
        body_preview: str = "",
        uid: int = 0,
        date: str = "",
        timestamp: float = 0.0,
    ) -> bool:
        """Record one blocked message, deduplicated by mailbox UID."""
        if uid and any(message.get("uid") == uid for message in self.messages):
            return False
        if not uid:
            identity = (subject, date, body_preview)
            if any(
                (
                    message.get("subject", ""),
                    message.get("date", ""),
                    message.get("body_preview", ""),
                )
                == identity
                for message in self.messages
            ):
                return False
        self.messages.append(
            {
                "display_name": display_name[:200],
                "subject": subject[:200],
                "body_preview": body_preview[:500],
                "timestamp": timestamp or time.time(),
                "uid": uid,
                "date": date,
            },
        )
        return True

    def merge_from(self, other: MailPendingEntry) -> None:
        """Merge another sender entry without duplicating mailbox UIDs."""
        for message in other.messages:
            self._append_message_dict(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender_address": self.sender_address,
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "subject": self.subject,
            "body_preview": self.body_preview,
            "timestamp": self.timestamp,
            "remark": self.remark,
            "uid": self.uid,
            "date": self.date,
            "messages": [dict(message) for message in self.messages],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MailPendingEntry:
        return cls(
            sender_address=data.get("sender_address", ""),
            agent_id=data.get("agent_id", ""),
            display_name=data.get("display_name", ""),
            subject=data.get("subject", ""),
            body_preview=data.get("body_preview", ""),
            timestamp=data.get("timestamp", 0.0),
            remark=data.get("remark", ""),
            uid=data.get("uid", 0),
            date=data.get("date", ""),
            messages=data.get("messages"),
        )


class MailUserInfo:
    """Per-address metadata stored in whitelist/blacklist."""

    __slots__ = ("remark", "display_name")

    def __init__(self, remark: str = "", display_name: str = ""):
        self.remark = remark
        self.display_name = display_name

    def to_dict(self) -> Dict[str, str]:
        return {"remark": self.remark, "display_name": self.display_name}

    @classmethod
    def from_dict(cls, data: Any) -> MailUserInfo:
        if isinstance(data, dict):
            return cls(
                remark=str(data.get("remark", "")),
                display_name=str(data.get("display_name", "")),
            )
        return cls(remark=str(data) if data else "")


class AgentMailACL:
    """Access control data for a single agent's mail."""

    def __init__(
        self,
        whitelist: Optional[Dict[str, MailUserInfo]] = None,
        blacklist: Optional[Dict[str, MailUserInfo]] = None,
        pending: Optional[List[MailPendingEntry]] = None,
        approved_replay: Optional[List[MailPendingEntry]] = None,
    ):
        self.whitelist: Dict[str, MailUserInfo] = whitelist or {}
        self.blacklist: Dict[str, MailUserInfo] = blacklist or {}
        self.pending: List[MailPendingEntry] = pending or []
        # Approved messages awaiting agent handling are deliberately separate
        # from the user-visible approval queue.  Keeping them in ``pending``
        # made an accepted row reappear until the asynchronous wake completed
        # and allowed repeated clicks to dispatch the same UID again.
        self.approved_replay: List[MailPendingEntry] = approved_replay or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "whitelist": {k: v.to_dict() for k, v in self.whitelist.items()},
            "blacklist": {k: v.to_dict() for k, v in self.blacklist.items()},
            "pending": [p.to_dict() for p in self.pending],
            "approved_replay": [p.to_dict() for p in self.approved_replay],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentMailACL:
        whitelist: Dict[str, MailUserInfo] = {}
        for k, v in data.get("whitelist", {}).items():
            whitelist[k] = MailUserInfo.from_dict(v)
        blacklist: Dict[str, MailUserInfo] = {}
        for k, v in data.get("blacklist", {}).items():
            blacklist[k] = MailUserInfo.from_dict(v)
        pending = [
            MailPendingEntry.from_dict(p) for p in data.get("pending", [])
        ]
        approved_replay = [
            MailPendingEntry.from_dict(p)
            for p in data.get("approved_replay", [])
        ]

        # Migrate files written by the old approval flow.  It deliberately
        # retained an approved sender in ``pending`` until wake success, which
        # is exactly the state that made the UI row impossible to dismiss.
        visible_pending: List[MailPendingEntry] = []
        for entry in pending:
            if entry.sender_address in whitelist:
                if not any(message.get("uid") for message in entry.messages):
                    continue
                existing = next(
                    (
                        item
                        for item in approved_replay
                        if item.sender_address == entry.sender_address
                    ),
                    None,
                )
                if existing is None:
                    approved_replay.append(entry)
                else:
                    existing.merge_from(entry)
            else:
                visible_pending.append(entry)
        return cls(
            whitelist=whitelist,
            blacklist=blacklist,
            pending=visible_pending,
            approved_replay=approved_replay,
        )


class MailAccessControlStore:  # pylint: disable=too-many-public-methods
    """Thread-safe persistent store for per-agent mail access control lists."""

    _MAX_PENDING = 500

    def __init__(self, path: Optional[Path] = None):
        self._path = path or WORKING_DIR / MAIL_ACCESS_CONTROL_FILE
        self._lock = threading.RLock()
        self._data: Dict[str, AgentMailACL] = {}
        self._last_mtime: float = 0.0
        # Domain wildcard caches
        self._domain_whitelist: Dict[str, Set[str]] = {}
        self._domain_blacklist: Dict[str, Set[str]] = {}
        self._load()

    # ── Persistence ─────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            mtime = self._path.stat().st_mtime
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._data = {k: AgentMailACL.from_dict(v) for k, v in raw.items()}
            self._rebuild_domain_sets()
            # Only remember the mtime after a successful parse so that a
            # corrupted file keeps triggering reload attempts and is picked
            # up again by _reload_if_stale once it has been repaired.
            self._last_mtime = mtime
        except Exception:
            logger.exception(
                "Failed to load mail access control data from %s",
                self._path,
            )

    def _reload_if_stale(self) -> None:
        """Reload from disk if the file was updated since last load."""
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
            # Atomic replace (temp file + rename) so a crash mid-write can
            # never leave a truncated/corrupted ACL file behind.
            write_json_atomic(self._path, payload)
            self._last_mtime = self._path.stat().st_mtime
            self._rebuild_domain_sets()
        except Exception as exc:
            logger.exception(
                "Failed to save mail access control data to %s",
                self._path,
            )
            # Roll back the mutable in-memory snapshot as well. Otherwise a
            # retry in the same process could observe an unsaved ``pending``
            # entry, treat it as durable, and advance the mailbox watermark.
            self._data = {}
            self._domain_whitelist = {}
            self._domain_blacklist = {}
            self._last_mtime = 0.0
            self._load()
            # Callers such as the IMAP monitor must not advance their UID
            # watermark when an approval/deny state only exists in memory.
            raise RuntimeError(
                f"Could not persist mail access control data to {self._path}",
            ) from exc

    def _acl(self, agent_id: str) -> AgentMailACL:
        if agent_id not in self._data:
            self._data[agent_id] = AgentMailACL()
        return self._data[agent_id]

    def _rebuild_domain_sets(self) -> None:
        """Rebuild domain wildcard caches from current data."""
        dw: Dict[str, Set[str]] = {}
        db: Dict[str, Set[str]] = {}
        for agent_id, acl in self._data.items():
            wset: Set[str] = set()
            for addr in acl.whitelist:
                if addr.startswith("*@"):
                    domain = addr[2:].lower()
                    wset.add(domain)
            if wset:
                dw[agent_id] = wset

            bset: Set[str] = set()
            for addr in acl.blacklist:
                if addr.startswith("*@"):
                    domain = addr[2:].lower()
                    bset.add(domain)
            if bset:
                db[agent_id] = bset
        self._domain_whitelist = dw
        self._domain_blacklist = db

    # ── Query ───────────────────────────────────────────────────────────

    def check_sender(self, agent_id: str, sender_email: str) -> str:
        # pylint: disable=too-many-return-statements
        """Check sender status.

        Returns "allow", "deny", "pending", or "unknown".
        """
        with self._lock:
            self._reload_if_stale()
            acl = self._data.get(agent_id)
            if acl is None:
                return "unknown"

            sender_lower = sender_email.lower().strip()

            # Explicit allow/deny decisions take precedence.  Approval keeps
            # blocked UIDs in a separate durable replay outbox, while new mail
            # from that sender is allowed immediately after the decision.
            if sender_lower in acl.whitelist:
                return "allow"

            if sender_lower in acl.blacklist:
                return "deny"

            domain = self._extract_domain(sender_lower)
            if domain:
                wset = self._domain_whitelist.get(agent_id)
                if wset and domain in wset:
                    return "allow"

                bset = self._domain_blacklist.get(agent_id)
                if bset and domain in bset:
                    return "deny"

            for entry in acl.pending:
                if entry.sender_address == sender_lower:
                    return "pending"

            return "unknown"

    @staticmethod
    def _extract_domain(email: str) -> str:
        """Extract domain from an email address."""
        at_idx = email.rfind("@")
        if at_idx < 0:
            return ""
        return email[at_idx + 1 :]

    def get_acl(self, agent_id: str) -> Dict[str, Any]:
        with self._lock:
            self._reload_if_stale()
            return self._acl(agent_id).to_dict()

    def get_all_acls(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            self._reload_if_stale()
            return {k: v.to_dict() for k, v in self._data.items()}

    # ── Whitelist ───────────────────────────────────────────────────────

    def add_to_whitelist(
        self,
        agent_id: str,
        address: str,
        remark: str = "",
        display_name: str = "",
    ) -> None:
        self.add_many_to_whitelist(
            agent_id,
            [(address, remark, display_name)],
        )

    def add_many_to_whitelist(
        self,
        agent_id: str,
        entries: List[Tuple[str, str, str]],
    ) -> int:
        """Apply a whitelist batch with one lock and one durable write."""
        normalized = []
        for address, remark, display_name in entries:
            address = address.lower().strip()
            self._validate_wildcard(address)
            normalized.append((address, remark, display_name))
        if not normalized:
            return 0
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            for address, remark, display_name in normalized:
                existing = acl.whitelist.get(address)
                acl.whitelist[address] = MailUserInfo(
                    remark=remark or (existing.remark if existing else ""),
                    display_name=display_name
                    or (existing.display_name if existing else ""),
                )
                acl.blacklist.pop(address, None)
                acl.pending = [
                    p for p in acl.pending if p.sender_address != address
                ]
            self._save()
        return len(normalized)

    def remove_from_whitelist(self, agent_id: str, address: str) -> None:
        self.remove_many_from_whitelist(agent_id, [address])

    def remove_many_from_whitelist(
        self,
        agent_id: str,
        addresses: List[str],
    ) -> int:
        normalized = [address.lower().strip() for address in addresses]
        if not normalized:
            return 0
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            for address in normalized:
                acl.whitelist.pop(address, None)
            self._save()
        return len(normalized)

    # ── Blacklist ───────────────────────────────────────────────────────

    def add_to_blacklist(
        self,
        agent_id: str,
        address: str,
        remark: str = "",
        display_name: str = "",
    ) -> None:
        self.add_many_to_blacklist(
            agent_id,
            [(address, remark, display_name)],
        )

    def add_many_to_blacklist(
        self,
        agent_id: str,
        entries: List[Tuple[str, str, str]],
    ) -> int:
        """Apply a blacklist batch with one lock and one durable write."""
        normalized = []
        for address, remark, display_name in entries:
            address = address.lower().strip()
            self._validate_wildcard(address)
            normalized.append((address, remark, display_name))
        if not normalized:
            return 0
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            for address, remark, display_name in normalized:
                existing = acl.blacklist.get(address)
                acl.blacklist[address] = MailUserInfo(
                    remark=remark or (existing.remark if existing else ""),
                    display_name=display_name
                    or (existing.display_name if existing else ""),
                )
                acl.whitelist.pop(address, None)
                acl.pending = [
                    p for p in acl.pending if p.sender_address != address
                ]
                acl.approved_replay = [
                    p
                    for p in acl.approved_replay
                    if p.sender_address != address
                ]
            self._save()
        return len(normalized)

    def remove_from_blacklist(self, agent_id: str, address: str) -> None:
        self.remove_many_from_blacklist(agent_id, [address])

    def remove_many_from_blacklist(
        self,
        agent_id: str,
        addresses: List[str],
    ) -> int:
        normalized = [address.lower().strip() for address in addresses]
        if not normalized:
            return 0
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            for address in normalized:
                acl.blacklist.pop(address, None)
            self._save()
        return len(normalized)

    # ── Pending ─────────────────────────────────────────────────────────

    def add_pending(
        self,
        agent_id: str,
        sender_address: str,
        display_name: str = "",
        subject: str = "",
        body_preview: str = "",
        uid: int = 0,
        date: str = "",
    ) -> None:
        sender_address = sender_address.lower().strip()
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            # Keep one approval row per sender, but retain every blocked
            # message inside that row.  The monitor watermark may advance past
            # these UIDs, so this durable list is the replay source on approve.
            for existing in acl.pending:
                if existing.sender_address == sender_address:
                    if existing.append_message(
                        display_name=display_name,
                        subject=subject,
                        body_preview=body_preview,
                        uid=uid,
                        date=date,
                    ):
                        self._save()
                    return
            # Enforce max pending limit
            if len(acl.pending) >= self._MAX_PENDING:
                acl.pending.sort(key=lambda p: p.timestamp)
                acl.pending.pop(0)
            acl.pending.append(
                MailPendingEntry(
                    sender_address=sender_address,
                    agent_id=agent_id,
                    display_name=display_name[:200],
                    subject=subject[:200],
                    body_preview=body_preview[:500],
                    timestamp=time.time(),
                    uid=uid,
                    date=date,
                ),
            )
            self._save()

    def get_pending_entry(
        self,
        agent_id: str,
        sender_address: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the pending entry dict for a sender, or None."""
        sender_address = sender_address.lower().strip()
        with self._lock:
            self._reload_if_stale()
            for entry in self._acl(agent_id).pending:
                if entry.sender_address == sender_address:
                    return entry.to_dict()
            return None

    def get_all_pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._reload_if_stale()
            result: List[Dict[str, Any]] = []
            for acl in self._data.values():
                result.extend(p.to_dict() for p in acl.pending)
            result.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            return result

    def get_pending_count(self) -> int:
        with self._lock:
            self._reload_if_stale()
            return sum(len(acl.pending) for acl in self._data.values())

    def approve_pending(
        self,
        agent_id: str,
        sender_address: str,
        remark: str = "",
    ) -> bool:
        """Move a pending sender to the whitelist."""
        self.approve_many(agent_id, [(sender_address, remark)])
        return True

    def approve_many(
        self,
        agent_id: str,
        entries: List[Tuple[str, str]],
    ) -> List[Optional[Dict[str, Any]]]:
        """Atomically approve senders and enqueue every blocked message.

        The returned snapshots contain only entries newly moved by this call.
        A repeated approval therefore cannot enqueue or dispatch the same UIDs
        again.  Replay durability is independent of the visible pending list.
        """
        normalized = [
            (sender_address.lower().strip(), remark)
            for sender_address, remark in entries
        ]
        if not normalized:
            return []
        snapshots: List[Optional[Dict[str, Any]]] = []
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            for sender_address, remark in normalized:
                effective_remark = remark
                display_name = ""
                pending_entry = next(
                    (
                        item
                        for item in acl.pending
                        if item.sender_address == sender_address
                    ),
                    None,
                )
                snapshots.append(
                    pending_entry.to_dict() if pending_entry else None,
                )
                if pending_entry is not None:
                    if not effective_remark:
                        effective_remark = pending_entry.remark
                    display_name = pending_entry.display_name
                    if any(
                        message.get("uid")
                        for message in pending_entry.messages
                    ):
                        existing_replay = next(
                            (
                                item
                                for item in acl.approved_replay
                                if item.sender_address == sender_address
                            ),
                            None,
                        )
                        if existing_replay is None:
                            acl.approved_replay.append(pending_entry)
                        else:
                            existing_replay.merge_from(pending_entry)
                acl.pending = [
                    item
                    for item in acl.pending
                    if item.sender_address != sender_address
                ]
                acl.whitelist[sender_address] = MailUserInfo(
                    remark=effective_remark,
                    display_name=display_name,
                )
                acl.blacklist.pop(sender_address, None)
            self._save()
        return snapshots

    def get_approved_replay(
        self,
        agent_id: str,
    ) -> List[Dict[str, Any]]:
        """Return a snapshot of approved messages awaiting agent handling."""
        with self._lock:
            self._reload_if_stale()
            return [
                entry.to_dict()
                for entry in self._acl(agent_id).approved_replay
            ]

    def ack_approved_replay_messages(
        self,
        agent_id: str,
        sender_address: str,
        uids: List[int],
    ) -> int:
        """Remove successfully replayed UIDs, preserving any failed ones."""
        sender_address = sender_address.lower().strip()
        acknowledged = {int(uid) for uid in uids if uid}
        if not acknowledged:
            return 0
        removed = 0
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            for replay_entry in list(acl.approved_replay):
                if replay_entry.sender_address != sender_address:
                    continue
                before = len(replay_entry.messages)
                replay_entry.messages = [
                    message
                    for message in replay_entry.messages
                    if message.get("uid") not in acknowledged
                ]
                removed = before - len(replay_entry.messages)
                if not replay_entry.messages:
                    acl.approved_replay.remove(replay_entry)
                else:
                    first = replay_entry.messages[0]
                    replay_entry.display_name = first.get("display_name", "")
                    replay_entry.subject = first.get("subject", "")
                    replay_entry.body_preview = first.get("body_preview", "")
                    replay_entry.timestamp = first.get("timestamp", 0.0)
                    replay_entry.uid = first.get("uid", 0)
                    replay_entry.date = first.get("date", "")
                break
            if removed:
                self._save()
        return removed

    def deny_pending(
        self,
        agent_id: str,
        sender_address: str,
        remark: str = "",
    ) -> bool:
        """Move a pending sender to the blacklist."""
        self.deny_many(agent_id, [(sender_address, remark)])
        return True

    def deny_many(
        self,
        agent_id: str,
        entries: List[Tuple[str, str]],
    ) -> int:
        """Deny pending senders with one lock and one durable write."""
        normalized = [
            (sender_address.lower().strip(), remark)
            for sender_address, remark in entries
        ]
        if not normalized:
            return 0
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            for sender_address, remark in normalized:
                effective_remark = remark
                display_name = ""
                pending_entry = next(
                    (
                        item
                        for item in acl.pending
                        if item.sender_address == sender_address
                    ),
                    None,
                )
                if pending_entry is not None:
                    if not effective_remark:
                        effective_remark = pending_entry.remark
                    display_name = pending_entry.display_name
                acl.pending = [
                    item
                    for item in acl.pending
                    if item.sender_address != sender_address
                ]
                acl.approved_replay = [
                    item
                    for item in acl.approved_replay
                    if item.sender_address != sender_address
                ]
                acl.blacklist[sender_address] = MailUserInfo(
                    remark=effective_remark,
                    display_name=display_name,
                )
                acl.whitelist.pop(sender_address, None)
            self._save()
        return len(normalized)

    def dismiss_pending(self, agent_id: str, sender_address: str) -> bool:
        """Remove from pending without adding to any list."""
        return bool(self.dismiss_many(agent_id, [sender_address]))

    def dismiss_many(self, agent_id: str, sender_addresses: List[str]) -> int:
        """Dismiss pending senders with one lock and one durable write."""
        normalized = [address.lower().strip() for address in sender_addresses]
        if not normalized:
            return 0
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            before = len(acl.pending)
            acl.pending = [
                item
                for item in acl.pending
                if item.sender_address not in set(normalized)
            ]
            removed = before - len(acl.pending)
            if removed:
                self._save()
            return removed

    def update_pending_remark(
        self,
        agent_id: str,
        sender_address: str,
        remark: str,
    ) -> bool:
        """Update the remark on a pending entry."""
        sender_address = sender_address.lower().strip()
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            for entry in acl.pending:
                if entry.sender_address == sender_address:
                    entry.remark = remark
                    self._save()
                    return True
            return False

    def update_remark(
        self,
        agent_id: str,
        address: str,
        remark: str,
    ) -> bool:
        """Update the remark for an address in whitelist or blacklist."""
        address = address.lower().strip()
        with self._lock:
            self._reload_if_stale()
            acl = self._acl(agent_id)
            if address in acl.whitelist:
                acl.whitelist[address].remark = remark
                self._save()
                return True
            if address in acl.blacklist:
                acl.blacklist[address].remark = remark
                self._save()
                return True
            return False

    # ── Validation helpers ──────────────────────────────────────────────

    @staticmethod
    def _validate_wildcard(address: str) -> None:
        """Validate wildcard address format."""
        if not address.startswith("*@"):
            return
        domain = address[2:]
        if not domain or domain == "*":
            raise ValueError(
                f"Invalid wildcard address {address!r}: "
                "domain must be a valid domain name, '*@*' is not allowed.",
            )
        if not _DOMAIN_RE.match(domain):
            raise ValueError(
                f"Invalid wildcard address {address!r}: "
                f"{domain!r} is not a valid domain format.",
            )


def validate_acl_address(address: str) -> None:
    """Validate an ACL address (plain email or ``*@domain`` wildcard).

    Raises:
        ValueError: if the address is malformed.
    """
    address = (address or "").lower().strip()
    if address.startswith("*@"):
        # pylint: disable-next=protected-access
        MailAccessControlStore._validate_wildcard(address)
        return
    if not _EMAIL_RE.match(address):
        raise ValueError(
            f"Invalid email address {address!r}: expected "
            "'user@domain' or a '*@domain' wildcard.",
        )


# Per-workspace store registry keyed by resolved workspace directory path.
_stores: Dict[str, MailAccessControlStore] = {}
_stores_lock = threading.Lock()


def get_mail_access_control_store(
    workspace_dir: Optional[Path] = None,
) -> MailAccessControlStore:
    """Get (or create) the MailAccessControlStore for a workspace.

    Args:
        workspace_dir: Workspace directory. If None, uses WORKING_DIR fallback.
    """
    with _stores_lock:
        if workspace_dir:
            key = str(Path(workspace_dir).resolve())
        else:
            key = str(Path(WORKING_DIR).resolve())
        if key not in _stores:
            path = Path(key) / MAIL_ACCESS_CONTROL_FILE
            _stores[key] = MailAccessControlStore(path)
        return _stores[key]
