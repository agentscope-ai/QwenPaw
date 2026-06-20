# -*- coding: utf-8 -*-
"""Migrate legacy file-based offload memory into the scroll ``history.db``.

The ``native`` strategy archived evicted context to date-grouped JSONL files
(``{workspace}/dialog/{YYYY-MM-DD}.jsonl``), one serialized AgentScope ``Msg``
per line (see :class:`qwenpaw.agents.offloader.QwenPawOffloader`). The
``scroll`` strategy keeps a durable ``conversation_history`` table. This module
converts the former into the latter so a user flipped onto ``scroll`` keeps
their past memory.

Design guarantees:

* **Non-destructive.** The source ``dialog/*.jsonl`` files are never modified
  or deleted, so flipping ``strategy`` back to ``native`` is lossless.
* **Idempotent.** Rows carry the same ``(session_id, dedup_key)`` identity the
  live writer uses, so re-running collides on ``ux_dedup`` and inserts nothing
  new — the DB's UNIQUE index is the ultimate safety net. A ``.migrated.json``
  manifest additionally lets a re-run skip already-converted files without
  re-reading them.
* **Faithful.** Conversion reuses the exact serialization the live path uses
  (:func:`msg_to_entries`), so a migrated row is indistinguishable from one the
  agent would have written itself.

The legacy offloader discarded ``session_id`` (it archived every session into
shared per-date files), so it cannot be recovered. Each date-file is mapped to
one synthetic session, ``legacy:{YYYY-MM-DD}``, preserving the day-grouped
timeline the legacy design was built around.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from agentscope.message import Msg

from .serialize import msg_to_entries

if TYPE_CHECKING:
    from .history import HistoryStore

logger = logging.getLogger(__name__)

MANIFEST_NAME = ".migrated.json"
_MANIFEST_VERSION = 1
_SESSION_PREFIX = "legacy:"


@dataclass
class FileResult:
    """Outcome of migrating one ``dialog/*.jsonl`` file."""

    filename: str
    session_id: str
    lines: int = 0  # non-blank lines read
    unparseable: int = 0  # lines that were not a decodable Msg
    rows_processed: int = 0  # LogEntry rows attempted
    rows_inserted: int = 0  # rows actually new (delta of history.count)
    skipped: bool = False  # short-circuited via manifest (already migrated)


@dataclass
class MigrationReport:
    """Aggregate outcome the caller can surface (e.g. a first-run notice)."""

    files: list[FileResult] = field(default_factory=list)
    orphan_tool_results: int = 0  # anonymous tool_results/*.txt, NOT imported

    @property
    def sessions(self) -> int:
        return len({f.session_id for f in self.files if not f.skipped})

    @property
    def rows_inserted(self) -> int:
        # Rows actually inserted *this run* — a skipped file contributes the
        # historical count from its manifest entry, not a fresh insert.
        return sum(f.rows_inserted for f in self.files if not f.skipped)

    @property
    def migrated_files(self) -> int:
        return sum(1 for f in self.files if not f.skipped)

    def summary(self) -> str:
        if not self.files and not self.orphan_tool_results:
            return "no legacy offload memory found"
        skipped = sum(1 for f in self.files if f.skipped)
        if not self.migrated_files:
            extra = f" ({skipped} file(s) already migrated)" if skipped else ""
            parts = ["nothing new" + extra]
        else:
            parts = [
                f"migrated {self.rows_inserted} rows from "
                f"{self.migrated_files} file(s) into {self.sessions} "
                f"session(s)",
            ]
            if skipped:
                parts.append(f"{skipped} file(s) already migrated")
        unparseable = sum(f.unparseable for f in self.files)
        if unparseable:
            parts.append(f"{unparseable} line(s) unparseable")
        if self.orphan_tool_results:
            parts.append(
                f"{self.orphan_tool_results} orphan tool-result file(s) "
                "left in place (unlinkable, not imported)",
            )
        return "; ".join(parts)


def _session_id_for(path: Path) -> str:
    """``dialog/2026-06-12.jsonl`` -> ``legacy:2026-06-12``."""
    return f"{_SESSION_PREFIX}{path.stem}"


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
            "migrate: could not write manifest %s: %s",
            manifest_path,
            exc,
        )


def _migrate_file(
    history: "HistoryStore",
    path: Path,
    *,
    agent_id: str | None,
    dry_run: bool,
) -> FileResult:
    """Convert one date-file into ``conversation_history`` rows.

    Dedup keys mirror the live manager exactly (see
    ``ScrollContextManager._persist_new``): a turn keys on its source
    ``msg.id``; a tool result keys on its ``tool_call_id``, or — for the rare
    result with no call id — on its fixed position within the owning Msg.
    """
    session_id = _session_id_for(path)
    res = FileResult(filename=path.name, session_id=session_id)
    before = 0 if dry_run else history.count(session_id)

    msg_index = 0
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            res.lines += 1
            try:
                msg = Msg.from_dict(json.loads(line))
            except Exception as exc:  # noqa: BLE001 - tolerate any bad line
                res.unparseable += 1
                logger.warning(
                    "migrate: skipping bad line in %s: %s",
                    path.name,
                    exc,
                )
                continue

            # Stable fallback id: the line's position is a fixed function of
            # the file, so a re-run re-derives the same key (unlike id(msg)).
            mid = getattr(msg, "id", None) or f"{session_id}#row{msg_index}"
            anon_pos = 0
            for entry in msg_to_entries(msg, msg_index):
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
            msg_index += 1

    res.rows_inserted = 0 if dry_run else history.count(session_id) - before
    return res


def _count_orphan_tool_results(tool_results_dir: Path | None) -> int:
    """Count anonymous ``tool_results/*.txt`` files (reported, never imported).

    These were written with random UUID names and the in-context pointer that
    referenced them was evicted, so they cannot be linked back to a
    ``tool_call_id``. The bulk of tool output is already inline in the dialog
    JSONL (full Msgs were offloaded), so importing these unlinkable blobs would
    add noise without recall value. We count them so the drop is never silent.
    """
    if tool_results_dir is None or not tool_results_dir.is_dir():
        return 0
    return sum(1 for _ in tool_results_dir.glob("*.txt"))


def migrate_dialog_to_history(
    *,
    history: "HistoryStore",
    dialog_dir: str | Path,
    tool_results_dir: str | Path | None = None,
    agent_id: str | None = None,
    dry_run: bool = False,
    use_manifest: bool = True,
) -> MigrationReport:
    """Convert every ``dialog/*.jsonl`` under *dialog_dir* into *history*.

    Returns a :class:`MigrationReport`. Safe to call repeatedly:
    already-migrated files are skipped via the manifest, and the DB's UNIQUE
    index makes re-appends no-ops. Never deletes or rewrites the source files.
    """
    dialog_path = Path(dialog_dir).expanduser()
    report = MigrationReport()
    report.orphan_tool_results = _count_orphan_tool_results(
        Path(tool_results_dir).expanduser() if tool_results_dir else None,
    )

    if not dialog_path.is_dir():
        return report

    manifest_path = dialog_path / MANIFEST_NAME
    manifest = _load_manifest(manifest_path) if use_manifest else {"files": {}}
    files_meta: dict = manifest["files"]

    for path in sorted(dialog_path.glob("*.jsonl")):
        digest = _sha256(path)
        prior = files_meta.get(path.name)
        if use_manifest and prior and prior.get("sha256") == digest:
            report.files.append(
                FileResult(
                    filename=path.name,
                    session_id=_session_id_for(path),
                    rows_inserted=int(prior.get("rows_inserted", 0)),
                    skipped=True,
                ),
            )
            continue

        res = _migrate_file(history, path, agent_id=agent_id, dry_run=dry_run)
        report.files.append(res)
        logger.info(
            "migrate: %s -> %s (%d inserted, %d processed, %d unparseable)",
            path.name,
            res.session_id,
            res.rows_inserted,
            res.rows_processed,
            res.unparseable,
        )
        if use_manifest and not dry_run:
            files_meta[path.name] = {
                "sha256": digest,
                "session_id": res.session_id,
                "lines": res.lines,
                "rows_processed": res.rows_processed,
                "rows_inserted": res.rows_inserted,
            }

    if use_manifest and not dry_run and report.migrated_files:
        _save_manifest(manifest_path, manifest)

    return report
