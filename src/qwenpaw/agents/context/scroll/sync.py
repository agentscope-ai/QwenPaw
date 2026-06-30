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

The session ``state`` embeds the real ``session_id``, so synced rows land under
the same conversation id the live agent uses.
"""

from __future__ import annotations

import hashlib
import json
import logging
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
_MANIFEST_VERSION = 1
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
    errored: bool = False  # file unreadable / not a recognizable session


@dataclass
class SyncReport:
    """Aggregate outcome the caller can surface in a startup log line."""

    files: list[FileResult] = field(default_factory=list)

    @property
    def sessions(self) -> int:
        return len(
            {
                f.session_id
                for f in self.files
                if not f.skipped and not f.errored and f.session_id
            },
        )

    @property
    def rows_inserted(self) -> int:
        # Rows inserted *this run* — skipped files don't count (their rows were
        # inserted on an earlier run).
        return sum(
            f.rows_inserted
            for f in self.files
            if not f.skipped and not f.errored
        )

    @property
    def synced_files(self) -> int:
        return sum(1 for f in self.files if not f.skipped and not f.errored)

    @property
    def skipped_files(self) -> int:
        return sum(1 for f in self.files if f.skipped)

    @property
    def errored_files(self) -> int:
        return sum(1 for f in self.files if f.errored)

    @property
    def unparseable(self) -> int:
        return sum(f.unparseable for f in self.files)

    @property
    def aged_out(self) -> int:
        return sum(f.aged_out for f in self.files)

    def summary(self) -> str:
        if not self.files:
            return "no sessions to sync"
        parts = [
            f"imported {self.rows_inserted} rows from "
            f"{self.synced_files}/{len(self.files)} file(s) into "
            f"{self.sessions} session(s)",
        ]
        if self.skipped_files:
            parts.append(f"{self.skipped_files} unchanged")
        if self.aged_out:
            parts.append(
                f"{self.aged_out} message(s) older than retention",
            )
        if self.unparseable:
            parts.append(f"{self.unparseable} message(s) unparseable")
        if self.errored_files:
            parts.append(f"{self.errored_files} file(s) errored")
        return "; ".join(parts)


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
    if not isinstance(data, dict) or data.get("version") != _MANIFEST_VERSION:
        return {"version": _MANIFEST_VERSION, "files": {}}
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


def _extract_session(data: dict, stem: str) -> tuple[str, list[Msg], int]:
    """Pull ``(session_id, messages, unparseable)`` from a session state dict.

    Handles both on-disk shapes ``QwenPawAgent.load_state_dict`` accepts: the
    2.0 ``{"state": {...}}`` (where the real ``session_id`` lives) and the 1.x
    legacy ``{"memory": {...}}``. Both reduce to a flat list of payloads, then
    a tolerant decode loop: a payload the current ``Msg`` schema can't validate
    is counted unparseable and skipped, never aborting the file.
    """
    agent = data.get("agent")
    if not isinstance(agent, dict):
        # Tolerate a bare module dict that isn't nested under "agent".
        agent = data

    raw_msgs: list = []
    session_id = ""

    state = agent.get("state")
    if isinstance(state, dict):
        # 2.0 format — session_id lives here.
        session_id = state.get("session_id") or ""
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

    if not session_id:
        session_id = f"{_SESSION_PREFIX}{stem}"

    messages: list[Msg] = []
    unparseable = 0
    for item in raw_msgs:
        try:
            messages.append(
                item if isinstance(item, Msg) else Msg.from_dict(item),
            )
        except Exception as exc:  # noqa: BLE001 - tolerate any bad message
            unparseable += 1
            logger.warning(
                "session-sync: skipping bad message in %s: %s",
                stem,
                exc,
            )
    return session_id, messages, unparseable


def _sync_file(
    history: "HistoryStore",
    path: Path,
    rel_name: str,
    *,
    agent_id: str | None,
    dry_run: bool,
    cutoff: str | None = None,
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
        session_id, messages, unparseable = _extract_session(data, path.stem)
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

    before = 0 if dry_run else history.count(session_id)
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
                history.append(
                    session_id=session_id,
                    agent_id=agent_id,
                    entry=entry,
                    dedup_key=dedup_key,
                )

    res.rows_inserted = 0 if dry_run else history.count(session_id) - before
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
    if int(prior.get("rows_inserted", 0)) <= 0:
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


def sync_sessions_to_history(
    *,
    history: "HistoryStore",
    sessions_dir: str | Path,
    agent_id: str | None = None,
    dry_run: bool = False,
    use_manifest: bool = True,
    retention_days: int = 0,
) -> SyncReport:
    """Import every ``sessions/*.json`` under *sessions_dir* into *history*.

    Returns a :class:`SyncReport`. Safe to call repeatedly: unchanged files are
    skipped via the manifest and the DB's UNIQUE index makes re-appends no-ops.
    Never deletes or rewrites the source session files.

    ``retention_days`` (0 = keep forever) skips messages older than the window,
    so we don't import rows the same-boot purge would delete. A fully aged-out
    session imports 0 rows, and its manifest entry lets later boots skip it.
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
    dirty = False

    for path, rel_name in _iter_session_files(sessions_path):
        try:
            digest = _sha256(path)
        except OSError as exc:
            report.files.append(
                FileResult(filename=rel_name, errored=True),
            )
            logger.warning("session-sync: cannot read %s: %s", path, exc)
            continue

        prior = files_meta.get(rel_name)
        if (
            use_manifest
            and prior
            and prior.get("sha256") == digest
            and _skip_is_safe(history, prior)
        ):
            report.files.append(
                FileResult(
                    filename=rel_name,
                    session_id=prior.get("session_id", ""),
                    rows_inserted=int(prior.get("rows_inserted", 0)),
                    skipped=True,
                ),
            )
            continue

        res = _sync_file(
            history,
            path,
            rel_name,
            agent_id=agent_id,
            dry_run=dry_run,
            cutoff=cutoff,
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
            }
            dirty = True

    if use_manifest and not dry_run and dirty:
        _save_manifest(manifest_path, manifest)

    return report


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
        if not sessions_dir.is_dir():
            logger.info("session-sync[%s]: no sessions to sync", agent_id)
            continue

        # First-run notice (no manifest yet): warn BEFORE the import so the
        # one-time migration isn't a silent stall. Later startups have a
        # manifest and skip straight through.
        if not (sessions_dir / MANIFEST_NAME).exists():
            pending = sum(1 for _ in _iter_session_files(sessions_dir))
            if pending:
                logger.warning(
                    "session-sync[%s]: first run — importing %d session "
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
