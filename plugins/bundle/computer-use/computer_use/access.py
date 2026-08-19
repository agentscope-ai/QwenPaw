# -*- coding: utf-8 -*-
"""Application access decisions owned by the Computer Use plugin."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Mapping


@dataclass(frozen=True)
class AppApprovalRequest:
    """A native-resolved application identity awaiting a user decision."""

    request_id: str
    session_id: str
    canonical_app_id: str
    display_name: str
    identity_evidence: Mapping[str, str]
    risk: str = "unknown"
    warning: str = ""


@dataclass(frozen=True)
class AppAccessDecision:
    """A resolved Computer Use application access decision."""

    allowed: bool
    source: str


@dataclass(frozen=True)
class PersistentAppAccess:
    """One explicit, installation-scoped allow decision."""

    canonical_app_id: str
    display_name: str


def _normalize_app_id(app_id: str) -> str:
    """Collapse equivalent spellings of one application identifier.

    Executable identifiers can arrive as either an extended-length
    (``\\\\?\\``) path or a plain drive path, and with mixed casing across
    the discovery sources. Stripping the prefix and folding case yields a
    single key so an application is approved once per session regardless of
    the spelling that reached the store.
    """
    text = app_id.strip()
    scheme, separator, remainder = text.partition(":")
    if separator and scheme == "process":
        verbatim_prefix = "\\\\?\\"
        if remainder.startswith(verbatim_prefix):
            remainder = remainder[len(verbatim_prefix) :]
        return f"{scheme}:{remainder.lower()}"
    # Only the Windows ``process:`` scheme is case-folded, because NTFS is
    # case-insensitive. The macOS ``app:`` path is left verbatim on purpose: a
    # case-sensitive APFS volume treats two casings as two files, so folding
    # here would merge identifiers the filesystem keeps distinct -- the same
    # mistake that once left canonical bundle paths unlaunchable. The path is
    # already canonicalized at its source, so the casing is consistent without
    # folding.
    return text


def _default_persistent_path() -> Path:
    from qwenpaw.constant import WORKING_DIR

    return (
        Path(WORKING_DIR)
        / "plugin_runtime"
        / "computer-use"
        / "app_access.json"
    )


class ComputerUseAccessStore:
    """Keep session decisions in memory and explicit grants on this host."""

    def __init__(self, persistent_path: Path | None = None) -> None:
        self._lock = RLock()
        self._persistent_path = persistent_path or _default_persistent_path()
        self._session_decisions: dict[tuple[str, str], bool] = {}
        self._persistent_decisions = self._load_persistent()

    def resolve(self, request: AppApprovalRequest) -> AppAccessDecision | None:
        """Return an existing decision, or ``None`` when input is needed."""
        app_id = _normalize_app_id(request.canonical_app_id)
        session_key = (request.session_id, app_id)
        with self._lock:
            session_decision = self._session_decisions.get(session_key)
            if session_decision is not None:
                return AppAccessDecision(session_decision, "session")
            if app_id in self._persistent_decisions:
                return AppAccessDecision(True, "persistent")
        return None

    def record_session(
        self,
        request: AppApprovalRequest,
        *,
        allowed: bool,
    ) -> None:
        """Keep a decision for the current in-memory session only."""
        app_id = _normalize_app_id(request.canonical_app_id)
        with self._lock:
            self._session_decisions[(request.session_id, app_id)] = allowed

    def record_persistent(
        self,
        canonical_app_id: str,
        display_name: str,
    ) -> None:
        """Persist an explicit allow for this QwenPaw installation."""
        app_id = _normalize_app_id(canonical_app_id)
        decision = PersistentAppAccess(app_id, display_name)
        with self._lock:
            self._persistent_decisions[app_id] = decision
            self._save_persistent_locked()

    def list_persistent(self) -> list[PersistentAppAccess]:
        """List application grants shared by this installation's agents."""
        with self._lock:
            decisions = list(self._persistent_decisions.values())
        return sorted(
            decisions,
            key=lambda decision: decision.display_name.casefold(),
        )

    def revoke_persistent(self, canonical_app_id: str) -> bool:
        """Remove one persistent allow so future access asks again."""
        app_id = _normalize_app_id(canonical_app_id)
        with self._lock:
            removed = self._persistent_decisions.pop(app_id, None)
            if removed is not None:
                self._save_persistent_locked()
        return removed is not None

    def _load_persistent(self) -> dict[str, PersistentAppAccess]:
        try:
            with self._persistent_path.open(encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}
        records = payload.get("allowed_apps", [])
        if not isinstance(records, list):
            return {}
        return {
            app_id: PersistentAppAccess(app_id, display_name)
            for record in records
            if isinstance(record, dict)
            and (
                app_id := _normalize_app_id(
                    str(record.get("canonical_app_id") or "").strip(),
                )
            )
            and (
                display_name := str(
                    record.get("display_name") or app_id,
                ).strip()
            )
        }

    def _save_persistent_locked(self) -> None:
        self._persistent_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._persistent_path.with_suffix(".tmp")
        payload = {
            "allowed_apps": [
                asdict(decision) for decision in self.list_persistent()
            ],
        }
        temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary_path, self._persistent_path)


_access_store: ComputerUseAccessStore | None = None
_access_store_lock = RLock()


def get_computer_use_access_store() -> ComputerUseAccessStore:
    """Return the process-wide Computer Use plugin access authority."""
    global _access_store
    # Double-checked: the fast path skips the lock once built, and the lock
    # keeps two callers on different event-loop threads from each building a
    # store and racing to install it. Under the GIL this is belt-and-braces,
    # but the guarantee it leans on is the interpreter's, not the code's.
    if _access_store is None:
        with _access_store_lock:
            if _access_store is None:
                _access_store = ComputerUseAccessStore()
    return _access_store
