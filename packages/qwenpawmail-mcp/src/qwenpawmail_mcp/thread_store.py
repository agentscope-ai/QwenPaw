# -*- coding: utf-8 -*-
"""Thread index + custom label store persisted as JSON under a state directory.

This module deliberately does NOT import anything from the ``mcp`` package so
it can be unit-tested independently of the MCP server layer.

Persistence layout (inside the state directory):
    threads.json   thread index: folders' last_seen_uid,
                   threads, message-id index
    labels.json    thread_id -> list of custom labels

Both files are written atomically (temp file + os.replace).

Threading algorithm:
    * A message with a References / In-Reply-To chain is anchored on the root
      Message-ID of the chain: ``thread_id = sha1(root_message_id)[:16]``.
    * A headless message (no References / In-Reply-To) falls back to grouping
      by normalized subject (Re:/Fwd:/回复:/转发: prefixes stripped, case
      insensitive, stackable) + participant intersection.
    * A message-id index links out-of-order arrivals (reply seen before root).

System labels ``inbox`` / ``sent`` / ``spam`` / ``trash`` are derived from the
folder a message lives in. They are read-only and can never be added/removed.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import os
import re
import statistics
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

from .errors import MailError

SYSTEM_LABELS = frozenset({"inbox", "sent", "spam", "trash"})

STATE_DIR_ENV = "QWENPAWMAIL_STATE_DIR"

_PROCESS_LOCK_FILE = ".thread_store.lock"
_LOCK_REGION_SIZE = 1

_Method = TypeVar("_Method", bound=Callable[..., Any])


def _synchronized(method: _Method) -> _Method:
    """Hold one store's re-entrant lock for a complete public operation."""

    @wraps(method)
    def wrapper(self: "ThreadStore", *args: Any, **kwargs: Any) -> Any:
        # pylint: disable=protected-access
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(_Method, wrapper)


#: First-sync window: newest 500 messages within the last 90 days.
FIRST_SYNC_DAYS = 90
FIRST_SYNC_LIMIT = 500

_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:(?:re|fw|fwd|aw|sv)\s*(?:\[\d+\])?\s*[:：]"
    r"|回复\s*[:：]|答复\s*[:：]|转发\s*[:：])\s*",
    re.IGNORECASE,
)

_MSGID_RE = re.compile(r"<[^<>\s]+>")


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def resolve_state_dir(
    email_address: str | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Resolve the state directory.

    Uses the QWENPAWMAIL_STATE_DIR environment variable when set (qwenpaw
    injects it, pointing at the agent workspace mail_state/ directory);
    otherwise falls back to ``~/.qwenpawmail-mcp/state/<email>/``.
    """
    env = dict(os.environ) if env is None else env
    raw = (env.get(STATE_DIR_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser()
    safe = re.sub(r"[^A-Za-z0-9@._+-]", "_", email_address or "default")
    return Path.home() / ".qwenpawmail-mcp" / "state" / safe


def normalize_subject(subject: str | None) -> str:
    """Strip stacked Re:/Fwd:/回复:/转发: prefixes; lowercase for matching."""
    text = (subject or "").strip()
    while True:
        stripped = _SUBJECT_PREFIX_RE.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped.strip()
    return text.lower()


def parse_message_ids(value: str | None) -> list[str]:
    """Extract all ``<...>`` message-ids from a header value."""
    return _MSGID_RE.findall(value or "")


def parse_timestamp(date_header: str | None) -> float | None:
    """Parse an RFC 2822 Date header to a unix timestamp (None on failure)."""
    if not date_header:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(date_header)
        if dt is None:
            return None
        return dt.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def extract_addresses(*header_values: str | None) -> list[str]:
    """Extract lowercase email addresses from From/To style header values."""
    pairs = email.utils.getaddresses([v for v in header_values if v])
    return [addr.lower() for _, addr in pairs if addr and "@" in addr]


_SENT_PAT = re.compile(r"sent|已发送|发件", re.IGNORECASE)
_TRASH_PAT = re.compile(r"trash|deleted|已删除|回收站", re.IGNORECASE)
_SPAM_PAT = re.compile(r"junk|spam|垃圾|广告|订阅", re.IGNORECASE)
_DRAFT_PAT = re.compile(r"draft|草稿", re.IGNORECASE)


def classify_folder(name: str, flags: list[str] | None = None) -> str:
    """Classify a folder as inbox/sent/trash/spam/drafts/other."""
    flag_text = " ".join(flags or []).lower()
    if name.upper() == "INBOX":
        return "inbox"
    if "\\sent" in flag_text or _SENT_PAT.search(name):
        return "sent"
    if "\\trash" in flag_text or _TRASH_PAT.search(name):
        return "trash"
    if "\\junk" in flag_text or _SPAM_PAT.search(name):
        return "spam"
    if "\\drafts" in flag_text or _DRAFT_PAT.search(name):
        return "drafts"
    return "other"


def detect_special_folders(folders: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect sent/trash/spam folders from a ``list_folders()`` result."""
    sent: list[str] = []
    trash: list[str] = []
    spam: list[str] = []
    for f in folders:
        name = f.get("name", "")
        kind = classify_folder(name, f.get("flags"))
        if kind == "sent":
            sent.append(name)
        elif kind == "trash":
            trash.append(name)
        elif kind == "spam":
            spam.append(name)
    # Prefer well-known trash names when several candidates exist.
    preferred = (
        "已删除",
        "Trash",
        "Deleted Messages",
        "Deleted Items",
        "回收站",
    )
    trash_folder = None
    for cand in preferred:
        if cand in trash:
            trash_folder = cand
            break
    if trash_folder is None and trash:
        trash_folder = trash[0]
    return {"sent": sent, "trash": trash_folder, "spam": spam}


def _thread_id_for(anchor: str) -> str:
    return hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:16]


def _date_to_ts(value: str | None, end_of_day: bool = False) -> float | None:
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.timestamp()


# ---------------------------------------------------------------------------
# ThreadStore
# ---------------------------------------------------------------------------


class ThreadStore:
    """JSON-persisted thread index (threads.json)
    + custom labels (labels.json)."""

    def __init__(self, state_dir: Path) -> None:
        self._lock = threading.RLock()
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._threads_path = self.state_dir / "threads.json"
        self._labels_path = self.state_dir / "labels.json"
        self._data: dict[str, Any] = self._load(self._threads_path) or {
            "version": 1,
            "folders": {},
            "threads": {},
            "msg_index": {},
        }
        self._labels: dict[str, list[str]] = (
            self._load(self._labels_path) or {}
        )

    @classmethod
    def for_email(cls, state_dir: Path, email_address: str) -> "ThreadStore":
        """Create a ThreadStore namespaced by email address.

        Stores data under state_dir/<sanitized_email>/ so that switching
        mailboxes does not corrupt thread indices.
        """
        safe = email_address.replace("@", "_at_")
        safe = re.sub(r"[^A-Za-z0-9._+-]", "_", safe)
        namespaced = Path(state_dir) / safe
        namespaced.mkdir(parents=True, exist_ok=True)
        return cls(namespaced)

    # -- persistence -------------------------------------------------------

    @staticmethod
    def _load(path: Path) -> Any:
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _atomic_write(path: Path, obj: Any) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=path.name,
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _reload_unlocked(self) -> None:
        """Refresh both in-memory snapshots while the caller owns the lock."""
        self._data = self._load(self._threads_path) or {
            "version": 1,
            "folders": {},
            "threads": {},
            "msg_index": {},
        }
        self._labels = self._load(self._labels_path) or {}

    @contextmanager
    def process_transaction(self) -> Iterator[None]:
        """Serialize and refresh a complete transaction across processes.

        QwenPaw's build-before-swap driver reload briefly runs the old and new
        stdio MCP processes together.  The OS lock prevents those processes
        from committing stale JSON snapshots over one another.  The in-process
        re-entrant lock also keeps direct worker-thread callers serialized.
        """
        with self._lock:
            lock_path = self.state_dir / _PROCESS_LOCK_FILE
            with open(lock_path, "a+b") as lock_file:
                self._acquire_process_lock(lock_file)
                try:
                    self._reload_unlocked()
                    yield
                finally:
                    self._release_process_lock(lock_file)

    @staticmethod
    def _acquire_process_lock(lock_file: Any) -> None:
        if os.name == "nt":  # pragma: no cover - exercised on Windows CI
            import msvcrt

            if os.fstat(lock_file.fileno()).st_size == 0:
                lock_file.seek(0)
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            while True:
                try:
                    msvcrt.locking(
                        lock_file.fileno(),
                        msvcrt.LK_NBLCK,
                        _LOCK_REGION_SIZE,
                    )
                    break
                except OSError:
                    time.sleep(0.05)
            return

        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

    @staticmethod
    def _release_process_lock(lock_file: Any) -> None:
        if os.name == "nt":  # pragma: no cover - exercised on Windows CI
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(
                lock_file.fileno(),
                msvcrt.LK_UNLCK,
                _LOCK_REGION_SIZE,
            )
            return

        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @_synchronized
    def save(self) -> None:
        self._atomic_write(self._threads_path, self._data)
        self._atomic_write(self._labels_path, self._labels)

    # -- thread building -----------------------------------------------------

    @_synchronized
    def add_message(
        self,
        envelope: dict[str, Any],
        folder: str,
        system_label: str,
    ) -> str:
        """Index one envelope into a thread; returns the thread_id."""
        mids = parse_message_ids(envelope.get("message_id"))
        mid = mids[0] if mids else None
        refs = parse_message_ids(envelope.get("references"))
        irt = parse_message_ids(envelope.get("in_reply_to"))
        chain = refs + [i for i in irt if i not in refs]

        threads = self._data["threads"]
        index = self._data["msg_index"]

        tid = None
        if mid and mid in index and index[mid] in threads:
            tid = index[mid]
        if tid is None:
            for ref in chain:
                if ref in index and index[ref] in threads:
                    tid = index[ref]
                    break
        if tid is None and chain:
            tid = _thread_id_for(chain[0])  # root of the References chain
        if tid is None:
            tid = self._headless_thread_id(envelope)

        thread = threads.setdefault(
            tid,
            {
                "thread_id": tid,
                "messages": [],
            },
        )
        key = f"{folder}\x00{envelope.get('uid')}"
        existing_keys = {
            f"{m['folder']}\x00{m['uid']}" for m in thread["messages"]
        }
        if key not in existing_keys:
            thread["messages"].append(
                {
                    "uid": envelope.get("uid"),
                    "folder": folder,
                    "system_label": system_label,
                    "subject": envelope.get("subject", ""),
                    "from": envelope.get("from", ""),
                    "to": envelope.get("to", ""),
                    "date": envelope.get("date", ""),
                    "timestamp": parse_timestamp(envelope.get("date")),
                    "message_id": mid or "",
                    "in_reply_to": envelope.get("in_reply_to", ""),
                    "references": envelope.get("references", ""),
                    "seen": bool(envelope.get("seen")),
                    "flagged": bool(envelope.get("flagged")),
                    "size": envelope.get("size"),
                },
            )
        for known in ([mid] if mid else []) + chain:
            index[known] = tid
        return tid

    def _headless_thread_id(self, envelope: dict[str, Any]) -> str:
        """Fallback grouping: normalized subject + participant intersection."""
        norm = normalize_subject(envelope.get("subject"))
        participants = set(
            extract_addresses(envelope.get("from"), envelope.get("to")),
        )
        for tid, thread in self._data["threads"].items():
            for m in thread["messages"]:
                if normalize_subject(m.get("subject")) != norm:
                    continue
                other = set(extract_addresses(m.get("from"), m.get("to")))
                if participants & other:
                    return tid
        anchor = "subject:" + norm + "|" + "|".join(sorted(participants))
        return _thread_id_for(anchor)

    # -- incremental sync ------------------------------------------------

    @_synchronized
    def sync(
        self,
        client: Any,
        folders: list[str] | None = None,
    ) -> dict[str, Any]:
        """Incrementally sync new envelopes from INBOX + detected sent folders.

        Per folder only UIDs greater than the recorded ``last_seen_uid`` are
        fetched. First sync is limited to the last 90 days / newest 500
        messages (whichever is smaller). Spam/trash/drafts folders are never
        synced.

        UIDVALIDITY awareness: the per-folder UIDVALIDITY reported by the
        server is persisted alongside ``last_seen_uid``. When it changes
        (folder rebuilt/migrated) the recorded UIDs are meaningless, so the
        baseline is dropped, the folder's stale indexed messages are purged
        (no zombie UIDs) and a fresh first-sync window is performed.
        """
        folder_infos = client.list_folders()
        special = detect_special_folders(folder_infos)
        if folders is None:
            folders = ["INBOX"] + special["sent"]
        new_count = 0
        for folder in folders:
            label = "sent" if folder in special["sent"] else "inbox"
            state = self._data["folders"].setdefault(folder, {})
            last_seen = state.get("last_seen_uid")
            stored_validity = state.get("uidvalidity")
            envelopes = None
            uidvalidity = None
            if last_seen:
                envelopes, uidvalidity = client.fetch_envelopes_after(
                    folder,
                    last_seen_uid=last_seen,
                )
                if (
                    stored_validity is not None
                    and uidvalidity is not None
                    and uidvalidity != stored_validity
                ):
                    # UIDVALIDITY reset: drop the baseline, purge stale
                    # messages and redo the first-sync window below.
                    self._purge_folder_messages(folder)
                    last_seen = None
                    envelopes = None
            if envelopes is None:
                since = (
                    date.today() - timedelta(days=FIRST_SYNC_DAYS)
                ).isoformat()
                envelopes, uidvalidity = client.fetch_envelopes_after(
                    folder,
                    since=since,
                    limit=FIRST_SYNC_LIMIT,
                )
            max_uid = last_seen or 0
            for env in envelopes:
                self.add_message(env, folder, label)
                try:
                    max_uid = max(max_uid, int(env.get("uid", 0)))
                except (TypeError, ValueError):
                    pass
            state["last_seen_uid"] = max_uid
            if uidvalidity is not None:
                state["uidvalidity"] = uidvalidity
            new_count += len(envelopes)
        self.save()
        return {
            "synced_folders": list(folders),
            "new_messages": new_count,
            "sent_folders": special["sent"],
            "trash_folder": special["trash"],
        }

    def _purge_folder_messages(self, folder: str) -> None:
        """Drop every indexed message of *folder* (UIDVALIDITY reset).

        Threads left empty are removed together with their custom labels;
        msg_index entries pointing at removed threads are cleaned up.
        The caller is responsible for saving.
        """
        threads = self._data["threads"]
        empty: list[str] = []
        for tid, thread in threads.items():
            thread["messages"] = [
                m for m in thread["messages"] if m.get("folder") != folder
            ]
            if not thread["messages"]:
                empty.append(tid)
        for tid in empty:
            del threads[tid]
            self._labels.pop(tid, None)
        index = self._data["msg_index"]
        stale = [mid for mid, tid in index.items() if tid not in threads]
        for mid in stale:
            del index[mid]

    # -- queries -------------------------------------------------------------

    def _thread_sorted_messages(
        self,
        thread: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return sorted(
            thread["messages"],
            key=lambda m: m.get("timestamp") or 0.0,
        )

    @_synchronized
    def system_labels_for(self, thread: dict[str, Any]) -> list[str]:
        return sorted(
            {m.get("system_label", "inbox") for m in thread["messages"]},
        )

    @_synchronized
    def custom_labels_for(self, thread_id: str) -> list[str]:
        return list(self._labels.get(thread_id, []))

    @_synchronized
    def thread_summary(self, thread_id: str) -> dict[str, Any]:
        thread = self._data["threads"][thread_id]
        msgs = self._thread_sorted_messages(thread)
        first, last = msgs[0], msgs[-1]
        participants = sorted(
            {
                a
                for m in msgs
                for a in extract_addresses(m.get("from"), m.get("to"))
            },
        )
        labels = sorted(
            set(self.system_labels_for(thread))
            | set(self.custom_labels_for(thread_id)),
        )
        return {
            "thread_id": thread_id,
            "subject": first.get("subject", ""),
            "participants": participants,
            "message_count": len(msgs),
            "latest_date": last.get("date", ""),
            "latest_timestamp": last.get("timestamp"),
            "labels": labels,
            "unread_count": sum(1 for m in msgs if not m.get("seen")),
        }

    @_synchronized
    def list_threads(
        self,
        labels: list[str] | None = None,
        sender: str | None = None,
        recipient: str | None = None,
        subject: str | None = None,
        before: str | None = None,
        after: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        before_ts = _date_to_ts(before)
        after_ts = _date_to_ts(after)
        summaries = []
        for tid, thread in self._data["threads"].items():
            summ = self.thread_summary(tid)
            if labels and not {lbl.lower() for lbl in labels} <= {
                lbl.lower() for lbl in summ["labels"]
            }:
                continue
            if sender and not any(
                sender.lower() in (m.get("from") or "").lower()
                for m in thread["messages"]
            ):
                continue
            if recipient and not any(
                recipient.lower() in (m.get("to") or "").lower()
                for m in thread["messages"]
            ):
                continue
            if subject and subject.lower() not in summ["subject"].lower():
                continue
            ts = summ["latest_timestamp"] or 0.0
            if before_ts is not None and ts >= before_ts:
                continue
            if after_ts is not None and ts < after_ts:
                continue
            summaries.append(summ)
        summaries.sort(
            key=lambda s: s["latest_timestamp"] or 0.0,
            reverse=True,
        )
        total = len(summaries)
        page = summaries[offset : offset + limit]
        for s in page:
            s.pop("latest_timestamp", None)
        return {"threads": page, "total": total}

    @_synchronized
    def get_thread(self, thread_id: str) -> dict[str, Any]:
        thread = self._data["threads"].get(thread_id)
        if thread is None:
            raise MailError(
                f"Thread {thread_id!r} not found. Use list_threads to see "
                "available thread ids.",
            )
        msgs = self._thread_sorted_messages(thread)
        summ = self.thread_summary(thread_id)
        summ.pop("latest_timestamp", None)
        return {
            **summ,
            "messages": [
                {k: v for k, v in m.items() if k != "timestamp"} for m in msgs
            ],
        }

    @_synchronized
    def thread_for_message_id(self, message_id: str) -> str | None:
        tid = self._data["msg_index"].get(message_id)
        return tid if tid in self._data["threads"] else None

    @_synchronized
    def thread_for_uid(self, folder: str, uid: str) -> str | None:
        for tid, thread in self._data["threads"].items():
            for m in thread["messages"]:
                if m.get("folder") == folder and m.get("uid") == uid:
                    return tid
        return None

    @_synchronized
    def timestamp_for_message_id(self, message_id: str) -> float | None:
        tid = self.thread_for_message_id(message_id)
        if tid is None:
            return None
        for m in self._data["threads"][tid]["messages"]:
            if m.get("message_id") == message_id:
                return m.get("timestamp")
        return None

    @_synchronized
    def thread_messages(self, thread_id: str) -> list[dict[str, Any]]:
        thread = self._data["threads"].get(thread_id)
        if thread is None:
            raise MailError(
                f"Thread {thread_id!r} not found. Use list_threads to see "
                "available thread ids.",
            )
        return [
            dict(message) for message in self._thread_sorted_messages(thread)
        ]

    # -- labels ---------------------------------------------------------------

    @_synchronized
    def update_labels(
        self,
        thread_id: str,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> list[str]:
        if thread_id not in self._data["threads"]:
            raise MailError(
                f"Thread {thread_id!r} not found. Use list_threads to see "
                "available thread ids.",
            )
        for label in list(add or []) + list(remove or []):
            if label.strip().lower() in SYSTEM_LABELS:
                raise MailError(
                    f"Label {label!r} is a reserved system label "
                    "(inbox/sent/spam/trash) derived from message folders; "
                    "it cannot be added or removed.",
                )
        current = list(self._labels.get(thread_id, []))
        for label in add or []:
            label = label.strip()
            if label and label not in current:
                current.append(label)
        for label in remove or []:
            label = label.strip()
            if label in current:
                current.remove(label)
        if current:
            self._labels[thread_id] = current
        else:
            self._labels.pop(thread_id, None)
        self.save()
        return current

    # -- deletion ----------------------------------------------------------

    @_synchronized
    def remove_messages(
        self,
        thread_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Remove indexed folder/UID pairs while preserving the thread."""
        thread = self._data["threads"].get(thread_id)
        if thread is None:
            return
        removed = {
            (str(message.get("folder")), str(message.get("uid")))
            for message in messages
        }
        thread["messages"] = [
            message
            for message in thread["messages"]
            if (str(message.get("folder")), str(message.get("uid")))
            not in removed
        ]
        if not thread["messages"]:
            self.remove_thread(thread_id)
        else:
            self.save()

    @_synchronized
    def remove_thread(self, thread_id: str) -> None:
        self._data["threads"].pop(thread_id, None)
        self._labels.pop(thread_id, None)
        stale = [
            mid
            for mid, tid in self._data["msg_index"].items()
            if tid == thread_id
        ]
        for mid in stale:
            del self._data["msg_index"][mid]
        self.save()

    # -- stats helpers -------------------------------------------------------

    @_synchronized
    def pending_reply_count(self) -> int:
        """Threads whose latest message is inbound and unread or flagged."""
        count = 0
        for thread in self._data["threads"].values():
            msgs = self._thread_sorted_messages(thread)
            if not msgs:
                continue
            last = msgs[-1]
            if last.get("system_label") == "inbox" and (
                not last.get("seen") or last.get("flagged")
            ):
                count += 1
        return count


# ---------------------------------------------------------------------------
# mailbox statistics aggregation (server.py only orchestrates)
# ---------------------------------------------------------------------------


def _top_counter(
    entries: list[tuple[str, str]],
    top_n: int = 10,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for name, addr in entries:
        addr = addr.lower()
        counts[addr] = counts.get(addr, 0) + 1
        if name and not names.get(addr):
            names[addr] = name
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return [
        {"address": addr, "name": names.get(addr, ""), "count": n}
        for addr, n in ranked
    ]


def compute_mailbox_stats(
    inbox_envelopes: list[dict[str, Any]],
    sent_envelopes: list[dict[str, Any]],
    days: int,
    store: ThreadStore | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    """Aggregate envelope scans into mailbox statistics."""
    inbox_by_mid: dict[str, float] = {}
    daily: dict[str, dict[str, int]] = {}

    def _day(env: dict[str, Any]) -> str | None:
        ts = parse_timestamp(env.get("date"))
        if ts is None:
            return None
        return datetime.fromtimestamp(ts).date().isoformat()

    sender_entries: list[tuple[str, str]] = []
    for env in inbox_envelopes:
        for mid in parse_message_ids(env.get("message_id")):
            ts = parse_timestamp(env.get("date"))
            if ts is not None:
                inbox_by_mid[mid] = ts
        name, addr = email.utils.parseaddr(env.get("from") or "")
        if addr:
            sender_entries.append((name, addr))
        day = _day(env)
        if day:
            daily.setdefault(day, {"received": 0, "sent": 0})["received"] += 1

    recipient_entries: list[tuple[str, str]] = []
    response_hours: list[float] = []
    for env in sent_envelopes:
        for name, addr in email.utils.getaddresses([env.get("to") or ""]):
            if addr:
                recipient_entries.append((name, addr))
        day = _day(env)
        if day:
            daily.setdefault(day, {"received": 0, "sent": 0})["sent"] += 1
        irt = parse_message_ids(env.get("in_reply_to"))
        if irt:
            orig_ts = inbox_by_mid.get(irt[0])
            if orig_ts is None and store is not None:
                orig_ts = store.timestamp_for_message_id(irt[0])
            sent_ts = parse_timestamp(env.get("date"))
            if (
                orig_ts is not None
                and sent_ts is not None
                and sent_ts >= orig_ts
            ):
                response_hours.append((sent_ts - orig_ts) / 3600.0)

    all_envs = list(inbox_envelopes) + list(sent_envelopes)
    largest = sorted(
        (e for e in all_envs if e.get("size")),
        key=lambda e: e["size"],
        reverse=True,
    )[:5]

    return {
        "days": days,
        "total_received": len(inbox_envelopes),
        "total_sent": len(sent_envelopes),
        "unread_count": sum(1 for e in inbox_envelopes if not e.get("seen")),
        "flagged_count": sum(1 for e in inbox_envelopes if e.get("flagged")),
        "top_senders": _top_counter(sender_entries),
        "top_recipients": _top_counter(recipient_entries),
        "daily_trend": [{"date": d, **daily[d]} for d in sorted(daily)],
        "avg_response_time_hours": {
            "mean": (
                round(statistics.mean(response_hours), 2)
                if response_hours
                else None
            ),
            "median": (
                round(statistics.median(response_hours), 2)
                if response_hours
                else None
            ),
            "samples": len(response_hours),
        },
        "pending_replies": (
            store.pending_reply_count() if store is not None else None
        ),
        "attachment_count": sum(
            1 for e in all_envs if e.get("has_attachment")
        ),
        "largest_messages": [
            {
                "uid": e.get("uid"),
                "folder": e.get("folder"),
                "subject": e.get("subject"),
                "size": e.get("size"),
            }
            for e in largest
        ],
        "truncated": truncated,
    }
