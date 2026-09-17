# -*- coding: utf-8 -*-
"""Import raw ``sessions/*.json`` conversation history into ``history.db``.

Conversations are saved one-file-per-session under ``{workspace}/sessions/``.
Under the ``scroll`` strategy, durable recall lives in ``history.db``,
populated live by :class:`ScrollContextManager`. Messages from before scroll
was enabled (or that never write-through'd) exist *only* in the session file,
invisible to recall.

On startup we scan every scroll-enabled agent's ``sessions/`` directory and
import each session's saved messages into its ``history.db``. The import is:

* **Non-destructive** — session files are read-only; we only write
  ``history.db`` and the ``.synced.json`` manifest.
* **Idempotent** — synced rows use the same ``(session_id, dedup_key)`` the
  live writer uses (``ScrollContextManager._persist_new``), so re-runs and
  concurrent live writes collide on the DB's ``ux_dedup`` UNIQUE index and add
  nothing. The ``.synced.json`` manifest also lets re-runs skip unchanged
  files without re-reading them.
* **Faithful** — conversion uses the live path's serializer
  (:func:`msg_to_entries`), so a synced row matches what the agent would have
  written itself.

When ``chats.json`` maps a session file, its chat ``session_id`` is canonical,
so synced rows land under the same conversation id the live Scroll writer
uses. Files not registered there are reported as orphans and not imported.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from agentscope.message import Msg

from .serialize import msg_to_entries

if TYPE_CHECKING:
    from .history import HistoryStore

logger = logging.getLogger(__name__)

MANIFEST_NAME = ".synced.json"
_MANIFEST_VERSION = 2
_SESSION_PREFIX = "sync:"


@dataclass
class FileResult:
    """Outcome of syncing one ``sessions/*.json`` file."""

    filename: str  # path relative to sessions_dir
    session_id: str = ""
    messages: int = 0  # messages read from the session state
    unparseable: int = 0  # messages that were not a decodable Msg
    aged_out: int = 0  # messages skipped as older than the retention window
    rows_processed: int = 0  # LogEntry rows attempted
    rows_inserted: int = 0  # rows actually new (delta of history.count)
    skipped: bool = False  # short-circuited via manifest (already synced)
    orphaned: bool = False  # not referenced by the supplied chat registry
    blocked: bool = False  # registry unavailable; source left untouched
    errored: bool = False  # file unreadable / not a recognizable session
    rows_rekeyed: int = 0
    rows_deduplicated: int = 0
    agent_rows_claimed: int = 0
    legacy_session_ids: list[str] = field(default_factory=list)


@dataclass
class SyncReport:
    """Aggregate outcome the caller can surface in a startup log line."""

    files: list[FileResult] = field(default_factory=list)
    registry_error: str | None = None

    @property
    def sessions(self) -> int:
        return len(
            {
                f.session_id
                for f in self.files
                if not f.skipped
                and not f.orphaned
                and not f.blocked
                and not f.errored
                and f.session_id
            },
        )

    @property
    def rows_inserted(self) -> int:
        # Rows inserted *this run* — skipped files don't count (their rows were
        # inserted on an earlier run).
        return sum(
            f.rows_inserted
            for f in self.files
            if not f.skipped
            and not f.orphaned
            and not f.blocked
            and not f.errored
        )

    @property
    def synced_files(self) -> int:
        return sum(
            1
            for f in self.files
            if not f.skipped
            and not f.orphaned
            and not f.blocked
            and not f.errored
        )

    @property
    def skipped_files(self) -> int:
        return sum(1 for f in self.files if f.skipped)

    @property
    def errored_files(self) -> int:
        return sum(1 for f in self.files if f.errored)

    @property
    def orphaned_files(self) -> int:
        return sum(1 for f in self.files if f.orphaned)

    @property
    def unparseable(self) -> int:
        return sum(f.unparseable for f in self.files)

    @property
    def aged_out(self) -> int:
        return sum(f.aged_out for f in self.files)

    def summary(self) -> str:
        if self.registry_error:
            return (
                "migration blocked: "
                f"{self.registry_error}; {len(self.files)} session file(s) "
                "left untouched"
            )
        if not self.files:
            return "no sessions to sync"
        parts = [
            f"imported {self.rows_inserted} rows from "
            f"{self.synced_files}/{len(self.files)} file(s) into "
            f"{self.sessions} session(s)",
        ]
        if self.skipped_files:
            parts.append(f"{self.skipped_files} unchanged")
        if self.orphaned_files:
            parts.append(f"{self.orphaned_files} orphaned")
        if self.aged_out:
            parts.append(
                f"{self.aged_out} message(s) older than retention",
            )
        if self.unparseable:
            parts.append(f"{self.unparseable} message(s) unparseable")
        if self.errored_files:
            parts.append(f"{self.errored_files} file(s) errored")
        return "; ".join(parts)


@dataclass(frozen=True)
class ChatRegistry:
    """Canonical session mapping plus an explicit load-health signal."""

    mapping: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    has_registered_chats: bool = False

    @property
    def available(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class SyncPreflight:
    """Read-only migration inputs resolved before opening ``history.db``."""

    session_files: tuple[tuple[Path, str], ...] = ()
    registry: ChatRegistry = field(default_factory=ChatRegistry)
    registry_error: str | None = None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest(manifest_path: Path) -> dict:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": _MANIFEST_VERSION, "files": {}}
    if not isinstance(data, dict) or data.get("version") not in {
        1,
        _MANIFEST_VERSION,
    }:
        return {"version": _MANIFEST_VERSION, "files": {}}
    # Keep v1 provenance long enough to reconcile any legacy session ID.
    # Dropping the whole manifest on a version bump would lose the only source
    # for rows imported under an arbitrary (non-synthetic) ID.
    data["version"] = _MANIFEST_VERSION
    data.setdefault("files", {})
    return data


def _save_manifest(manifest_path: Path, manifest: dict) -> None:
    try:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning(
            "session-sync: could not write manifest %s: %s",
            manifest_path,
            exc,
        )


def _extract_session(
    data: dict,
    session_id: str,
) -> tuple[str, list[Msg], int, str]:
    """Extract canonical messages plus any legacy embedded session ID.

    Handles both on-disk shapes ``QwenPawAgent.load_state_dict`` accepts: the
    2.0 ``{"state": {...}}`` and the 1.x legacy ``{"memory": {...}}``. The
    caller supplies the canonical registry ID. An embedded ID is returned only
    as migration provenance and never overrides the registry.
    """
    agent = data.get("agent")
    if not isinstance(agent, dict):
        # Tolerate a bare module dict that isn't nested under "agent".
        agent = data

    raw_msgs: list = []
    embedded_session_id = ""
    state = agent.get("state")
    if isinstance(state, dict):
        raw_embedded_id = state.get("session_id")
        if isinstance(raw_embedded_id, str):
            embedded_session_id = raw_embedded_id
        ctx = state.get("context")
        if isinstance(ctx, list):
            raw_msgs = ctx
    else:
        memory = agent.get("memory")
        if isinstance(memory, dict):
            # 1.x legacy: content is [[msg_dict, marks], ...]; keep the
            # payload, drop the marks (unused by the new schema).
            for item in memory.get("content") or []:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    raw_msgs.append(item[0])
                else:
                    raw_msgs.append(item)

    messages: list[Msg] = []
    unparseable = 0
    for item in raw_msgs:
        try:
            messages.append(
                (
                    item if isinstance(item, Msg) else Msg.from_dict(item)
                ),  # type: ignore[attr-defined]
            )
        except Exception as exc:  # noqa: BLE001 - tolerate any bad message
            unparseable += 1
            logger.warning(
                "session-sync: skipping bad message for %s: %s",
                session_id,
                exc,
            )
    return session_id, messages, unparseable, embedded_session_id


# The error-isolation and retention paths are intentionally kept together so
# one source file has one auditable migration boundary.
# pylint: disable=too-many-branches
def _sync_file(
    history: "HistoryStore",
    path: Path,
    rel_name: str,
    *,
    session_id: str,
    agent_id: str | None = None,
    dry_run: bool = False,
    cutoff: str | None = None,
    legacy_session_ids: set[str] | None = None,
) -> FileResult:
    """Import one ``sessions/*.json`` file into ``conversation_history``.

    Dedup keys mirror ``ScrollContextManager._persist_new`` exactly: a turn
    keys on its ``msg.id``; a tool result keys on its ``tool_call_id``, or — if
    it has none — on its position within the owning Msg.

    With a ``cutoff`` (ISO-8601 instant), messages older than it are skipped:
    they fall outside the retention window, so importing them would only
    resurrect rows the same-boot purge deletes. Messages with no ``created_at``
    are kept (purge skips NULL timestamps too, so the two stay consistent).
    """
    res = FileResult(filename=rel_name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - tolerate any unreadable file
        res.errored = True
        logger.warning("session-sync: unreadable session %s: %s", path, exc)
        return res
    if not isinstance(data, dict):
        res.errored = True
        return res

    try:
        (
            session_id,
            messages,
            unparseable,
            embedded_session_id,
        ) = _extract_session(data, session_id)
    except Exception as exc:  # noqa: BLE001 - one bad file must not abort sync
        res.errored = True
        logger.warning(
            "session-sync: could not parse session %s: %s",
            rel_name,
            exc,
        )
        return res
    res.session_id = session_id
    res.messages = len(messages)
    res.unparseable = unparseable

    pending_entries = []
    for row_index, msg in enumerate(messages):
        # Skip messages older than the retention window so we don't import rows
        # the same-boot purge would immediately delete. NULL timestamps are
        # kept (purge skips them too).
        created_at = getattr(msg, "created_at", None)
        if cutoff and created_at and created_at < cutoff:
            res.aged_out += 1
            continue
        # Fallback id from row position: a re-run derives the same key (unlike
        # id(msg)), keeping dedup stable.
        mid = getattr(msg, "id", None) or f"{session_id}#row{row_index}"
        anon_pos = 0
        try:
            entries = list(msg_to_entries(msg))
        except Exception as exc:  # noqa: BLE001 - tolerate a bad message
            res.unparseable += 1
            logger.warning(
                "session-sync: could not serialize message in %s: %s",
                rel_name,
                exc,
            )
            continue
        for entry in entries:
            if entry.kind == "tool_result":
                dedup_key = entry.tool_call_id or f"{mid}#anon{anon_pos}"
                anon_pos += 1
            else:
                dedup_key = mid
            res.rows_processed += 1
            if not dry_run:
                pending_entries.append((entry, dedup_key))

    source_ids = set(legacy_session_ids or ())
    if embedded_session_id and embedded_session_id != session_id:
        source_ids.add(embedded_session_id)
    res.legacy_session_ids = sorted(source_ids)

    if not dry_run:
        dedup_keys = {
            str(dedup_key)
            for _entry, dedup_key in pending_entries
            if dedup_key
        }
        (
            res.rows_rekeyed,
            res.rows_deduplicated,
            res.agent_rows_claimed,
        ) = history.reconcile_session_rows(
            source_ids,
            session_id,
            dedup_keys,
            agent_id=agent_id,
        )
        if res.rows_rekeyed or res.rows_deduplicated:
            logger.info(
                "session-sync: reconciled %s -> %s "
                "(%d moved, %d deduplicated)",
                sorted(source_ids),
                session_id,
                res.rows_rekeyed,
                res.rows_deduplicated,
            )

        # One transaction per source file. The old per-row append path
        # committed every event independently, making migration time
        # proportional to disk fsync latency.
        res.rows_inserted = history.append_many(
            session_id=session_id,
            agent_id=agent_id,
            entries=pending_entries,
        )
    return res


def _skip_is_safe(history: "HistoryStore", prior: dict) -> bool:
    """Whether a manifest hit can be trusted to skip re-reading the file.

    The DB can be rebuilt under the manifest: ``HistoryStore`` quarantines a
    corrupt ``history.db`` and opens a fresh empty one, while ``.synced.json``
    survives. A blind hash-skip would then leave the session missing from the
    rebuilt DB. So we verify: skip is safe only if the session still has rows
    in *this* DB. A manifest with no rows is trivially safe; an empty session
    that should have rows means the DB was reset — re-sync (the UNIQUE index
    dedups, so a healthy DB only pays a re-read)."""
    expected_rows = int(
        prior.get("rows_processed", prior.get("rows_inserted", 0)),
    )
    if expected_rows <= 0:
        return True
    session_id = prior.get("session_id") or ""
    if not session_id:
        return False
    try:
        return history.count(session_id) > 0
    except Exception:  # noqa: BLE001 - if the count fails, re-sync to be safe
        return False


def _iter_session_files(sessions_path: Path):
    """Yield ``*.json`` session files, recursing into channel subdirs.

    Any path with a dotted component (the ``.weixin-legacy`` archive, this
    manifest, etc.) is excluded.
    """
    for path in sorted(sessions_path.rglob("*.json")):
        rel = path.relative_to(sessions_path)
        if any(part.startswith(".") for part in rel.parts):
            continue
        yield path, rel.as_posix()


def _load_chat_session_id_map(
    chats_path: str | Path | None,
) -> ChatRegistry:
    """Map session file paths to canonical ids from ``chats.json``.

    ``SafeJSONSession`` stores a chat at
    ``<channel>/<safe_user>_<safe_session>.json`` (or without the user prefix
    when both ids are equal). Older releases also stored the same filename at
    the sessions root, so both relative paths are indexed. A filename
    collision between different session ids is treated as ambiguous and
    omitted rather than guessing.
    """
    if chats_path is None:
        error = "chat registry path was not supplied"
        logger.error("session-sync: %s; no history was imported", error)
        return ChatRegistry(error=error)

    path = Path(chats_path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        error = f"cannot read chat registry {path}: {exc}"
        logger.error(
            "session-sync: %s; no history was imported",
            error,
        )
        return ChatRegistry(error=error)
    try:
        from ....app.chats.models import ChatsFile

        registry_file = ChatsFile.model_validate(data)
    except (TypeError, ValueError) as exc:
        error = f"invalid chat registry {path}"
        logger.error(
            "session-sync: %s (%s); no history was imported",
            error,
            exc,
        )
        return ChatRegistry(error=error)

    from ....app.chats.session import session_relative_paths

    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    registered = 0
    for chat in registry_file.chats:
        session_id = chat.session_id
        if not session_id:
            continue
        registered += 1
        try:
            rel_names = session_relative_paths(
                session_id,
                chat.user_id,
                chat.channel,
            )
        except ValueError as exc:
            error = f"invalid chat registry {path}: {exc}"
            logger.error(
                "session-sync: %s; no history was imported",
                error,
            )
            return ChatRegistry(error=error)
        for rel_name in rel_names:
            previous = mapping.get(rel_name)
            if previous is not None and previous != session_id:
                ambiguous.add(rel_name)
                mapping.pop(rel_name, None)
            elif rel_name not in ambiguous:
                mapping[rel_name] = session_id

    if ambiguous:
        logger.warning(
            "session-sync: ignored %d ambiguous chat/session filename(s) "
            "in %s",
            len(ambiguous),
            path,
        )
    return ChatRegistry(
        mapping=mapping,
        has_registered_chats=registered > 0,
    )


def preflight_sessions(
    sessions_dir: str | Path,
    chats_path: str | Path | None,
) -> SyncPreflight:
    """Resolve files and registry health without opening ``history.db``."""
    sessions_path = Path(sessions_dir).expanduser()
    if not sessions_path.is_dir():
        return SyncPreflight()

    session_files = tuple(_iter_session_files(sessions_path))
    if not session_files:
        return SyncPreflight(session_files=session_files)
    registry = _load_chat_session_id_map(chats_path)
    registry_error = registry.error
    if (
        registry.available
        and session_files
        and not registry.has_registered_chats
    ):
        registry_error = f"chat registry {chats_path} has no registered chats"
        logger.error(
            "session-sync: found %d legacy session file(s), but %s; "
            "migration was not performed and source files were left untouched",
            len(session_files),
            registry_error,
        )
    return SyncPreflight(
        session_files=session_files,
        registry=registry,
        registry_error=registry_error,
    )


def _report_orphan(
    report: SyncReport,
    rel_name: str,
) -> None:
    """Record a session file that is absent from the chat registry."""
    report.files.append(FileResult(filename=rel_name, orphaned=True))


# pylint: disable=too-many-branches,too-many-statements
def sync_sessions_to_history(
    *,
    history: "HistoryStore",
    sessions_dir: str | Path,
    chats_path: str | Path | None = None,
    agent_id: str | None = None,
    dry_run: bool = False,
    use_manifest: bool = True,
    retention_days: int = 0,
    preflight: SyncPreflight | None = None,
) -> SyncReport:
    """Import every ``sessions/*.json`` under *sessions_dir* into *history*.

    Returns a :class:`SyncReport`. Safe to call repeatedly: unchanged files are
    skipped via the manifest and the DB's UNIQUE index makes re-appends no-ops.
    Never deletes or rewrites the source session files.

    ``retention_days`` (0 = keep forever) skips messages older than the window,
    so we don't import rows the same-boot purge would delete. A fully aged-out
    session imports 0 rows, and its manifest entry lets later boots skip it.
    ``chats_path`` is the authoritative registry: only session files with an
    exact chat mapping are imported. Unreferenced files are reported as
    orphans and left untouched. A missing or invalid registry blocks the whole
    import with an explicit report; silently falling back to filenames could
    resurrect session files left behind by a user-visible chat deletion.
    """
    sessions_path = Path(sessions_dir).expanduser()
    report = SyncReport()
    if not sessions_path.is_dir():
        return report

    cutoff = (
        (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        if retention_days > 0
        else None
    )

    manifest_path = sessions_path / MANIFEST_NAME
    manifest = _load_manifest(manifest_path) if use_manifest else {"files": {}}
    files_meta: dict = manifest["files"]
    resolved = preflight or preflight_sessions(sessions_path, chats_path)
    session_files = list(resolved.session_files)
    if resolved.registry_error:
        report.registry_error = resolved.registry_error
        report.files.extend(
            FileResult(filename=rel_name, blocked=True)
            for _path, rel_name in session_files
        )
        return report

    canonical_ids = resolved.registry.mapping
    stem_counts = Counter(path.stem for path, _rel_name in session_files)
    dirty = False

    for path, rel_name in session_files:
        canonical_id = canonical_ids.get(rel_name)
        if canonical_id is None:
            _report_orphan(report, rel_name)
            continue

        try:
            digest = _sha256(path)
        except OSError as exc:
            report.files.append(
                FileResult(filename=rel_name, errored=True),
            )
            logger.warning("session-sync: cannot read %s: %s", path, exc)
            continue

        prior = files_meta.get(rel_name)
        manifest_matches = bool(
            use_manifest and prior and prior.get("sha256") == digest,
        )
        canonical_matches = bool(
            prior and prior.get("session_id") == canonical_id,
        )
        if not dry_run:
            history.claim_session(canonical_id, agent_id)
        should_skip = False
        if manifest_matches and canonical_matches:
            assert prior is not None
            should_skip = _skip_is_safe(history, prior)
        if should_skip:
            assert prior is not None
            report.files.append(
                FileResult(
                    filename=rel_name,
                    session_id=prior.get("session_id", ""),
                    rows_inserted=int(prior.get("rows_inserted", 0)),
                    skipped=True,
                ),
            )
            continue

        legacy_session_ids: set[str] = set()
        prior_session_id = str(prior.get("session_id") or "") if prior else ""
        if prior_session_id and prior_session_id != canonical_id:
            legacy_session_ids.add(prior_session_id)
        if prior:
            legacy_session_ids.update(
                str(source_id)
                for source_id in prior.get("legacy_session_ids_checked", ())
                if source_id
            )
        if stem_counts[path.stem] == 1:
            legacy_session_ids.add(f"{_SESSION_PREFIX}{path.stem}")

        res = _sync_file(
            history,
            path,
            rel_name,
            session_id=canonical_id,
            agent_id=agent_id,
            dry_run=dry_run,
            cutoff=cutoff,
            legacy_session_ids=legacy_session_ids,
        )
        report.files.append(res)
        if res.errored:
            continue
        logger.debug(
            "session-sync: %s -> %s (%d inserted, %d processed, %d bad)",
            rel_name,
            res.session_id,
            res.rows_inserted,
            res.rows_processed,
            res.unparseable,
        )
        if use_manifest and not dry_run:
            files_meta[rel_name] = {
                "sha256": digest,
                "session_id": res.session_id,
                "messages": res.messages,
                "aged_out": res.aged_out,
                "rows_processed": res.rows_processed,
                "rows_inserted": res.rows_inserted,
                "legacy_session_ids_checked": res.legacy_session_ids,
            }
            dirty = True

    if report.orphaned_files:
        logger.warning(
            "session-sync: skipped %d orphaned session file(s) not registered "
            "in %s; no history was imported from those files. Restore their "
            "chat registry entries to migrate them",
            report.orphaned_files,
            chats_path,
        )

    if use_manifest and not dry_run and dirty:
        _save_manifest(manifest_path, manifest)

    return report


# pylint: enable=too-many-branches,too-many-statements


def _purge_old_history(
    history: HistoryStore,
    retention_days: int,
    agent_id: str | None = None,
) -> None:
    """Drop history rows older than ``retention_days`` (0 = keep forever).

    Runs on every startup so the store still shrinks even if the agent was
    killed before its teardown purge could run. Best-effort: a failure is
    logged and never aborts the sync.
    """
    if retention_days <= 0:
        return
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=retention_days)
    ).isoformat()
    try:
        removed = history.purge(before=cutoff)
    except Exception as exc:  # noqa: BLE001 - retention must never break boot
        logger.warning(
            "session-sync[%s]: retention purge failed: %s",
            agent_id,
            exc,
        )
        return
    if removed:
        logger.info(
            "session-sync[%s]: purged %d row(s) older than %dd",
            agent_id,
            removed,
            retention_days,
        )


def sync_all_scroll_agents() -> None:
    """Sync every scroll-enabled agent's ``sessions/*.json`` into its history.

    Called once at server startup. Fully guarded: any failure is logged and
    isolated so it can never block boot. Native-strategy agents are skipped —
    their ``history.db`` is never read, so populating it would just orphan a
    file.
    """
    try:
        _sync_all_scroll_agents()
    except Exception:  # noqa: BLE001 - sync must never break startup
        logger.warning("session-sync: aborted unexpectedly", exc_info=True)


# Keep the preflight-before-DB-open ordering visible in one startup flow.  In
# particular, moving DB construction into a generic helper would make it much
# easier to accidentally mutate/quarantine history before registry validation.
# pylint: disable=too-many-statements
def _sync_all_scroll_agents() -> None:
    # Imported lazily to keep this module importable without the app config.
    from ....config import load_config
    from ....config.config import load_agent_config
    from .history import HistoryStore

    config = load_config()
    total_rows = 0
    total_sessions = 0
    synced_agents = 0

    for agent_id, agent_ref in config.agents.profiles.items():
        try:
            agent_config = load_agent_config(agent_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "session-sync[%s]: config load failed: %s",
                agent_id,
                exc,
            )
            continue

        try:
            lcc = agent_config.running.light_context_config
            strategy = getattr(lcc, "strategy", "native")
        except Exception:  # noqa: BLE001
            continue
        if strategy != "scroll":
            continue

        # Use the profile ref's path (each id -> its own dir), NOT
        # ``agent_config.workspace_dir``: that field is baked into agent.json
        # at clone time, so every clone points back at the original and they'd
        # all collapse onto one workspace.
        workspace_dir = Path(agent_ref.workspace_dir).expanduser()
        sessions_dir = workspace_dir / "sessions"
        chats_path = workspace_dir / "chats.json"
        if not sessions_dir.is_dir():
            logger.info("session-sync[%s]: no sessions to sync", agent_id)
            continue
        resolved = preflight_sessions(sessions_dir, chats_path)
        if resolved.registry_error:
            blocked = SyncReport(registry_error=resolved.registry_error)
            blocked.files.extend(
                FileResult(filename=rel_name, blocked=True)
                for _path, rel_name in resolved.session_files
            )
            logger.error(
                "session-sync[%s]: %s",
                agent_id,
                blocked.summary(),
            )
            continue

        # First-run notice (no manifest yet): warn BEFORE the import so the
        # one-time migration isn't a silent stall. Later startups have a
        # manifest and skip straight through.
        if not (sessions_dir / MANIFEST_NAME).exists():
            pending = sum(
                1
                for _path, rel_name in resolved.session_files
                if rel_name in resolved.registry.mapping
            )
            if pending:
                logger.warning(
                    "session-sync[%s]: first run — importing %d registered "
                    "session "
                    "file(s) into history.db. This one-time migration may "
                    "take a moment; later startups skip unchanged files.",
                    agent_id,
                    pending,
                )

        db_path = workspace_dir / lcc.scroll_config.db_filename
        retention_days = lcc.scroll_config.history_retention_days
        history = HistoryStore(db_path)
        try:
            report = sync_sessions_to_history(
                history=history,
                sessions_dir=sessions_dir,
                agent_id=agent_id,
                retention_days=retention_days,
                chats_path=chats_path,
                preflight=resolved,
            )
            _purge_old_history(history, retention_days, agent_id)
        except Exception as exc:  # noqa: BLE001 - isolate one agent's failure
            logger.warning(
                "session-sync[%s]: failed: %s",
                agent_id,
                exc,
                exc_info=True,
            )
            continue
        finally:
            history.close()

        logger.info("session-sync[%s]: %s", agent_id, report.summary())
        if history.degraded:
            logger.warning(
                "session-sync[%s]: history store DEGRADED during sync; "
                "durability not guaranteed",
                agent_id,
            )
        synced_agents += 1
        total_rows += report.rows_inserted
        total_sessions += report.sessions

    if synced_agents:
        logger.info(
            "session-sync: done — %d row(s) into %d session(s) across "
            "%d scroll agent(s)",
            total_rows,
            total_sessions,
            synced_agents,
        )
