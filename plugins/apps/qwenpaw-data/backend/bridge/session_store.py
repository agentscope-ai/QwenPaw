# -*- coding: utf-8 -*-
"""Per-session bridge state: QwenPaw channel session → engine session."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BridgeSessionState:
    """State pinned to one QwenPaw session key (``{channel}:{sender}``)."""

    active: bool = False
    engine_session_id: str = ""
    datasource_id: Optional[str] = None
    # {chat_id, clarification_id, title, questions: [...], last_seq}
    pending_clarification: Optional[Dict[str, Any]] = None
    # [{id, name}] — numbered options offered by /datasource
    pending_datasource_choice: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BridgeSessionState":
        return cls(
            active=bool(data.get("active", False)),
            engine_session_id=str(data.get("engine_session_id", "")),
            datasource_id=data.get("datasource_id"),
            pending_clarification=data.get("pending_clarification"),
            pending_datasource_choice=data.get("pending_datasource_choice"),
        )


@dataclass
class BridgeSessionStore:
    """Synchronous JSON-backed store.

    Reads happen inside the (synchronous) middleware factory on every
    agent request, so the store keeps an in-memory cache and only touches
    disk on writes and first load. The file is tiny (one entry per active
    IM conversation); a plain threading.Lock is sufficient.
    """

    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cache: Optional[Dict[str, Dict[str, Any]]] = None

    def get(self, session_key: str) -> BridgeSessionState:
        with self._lock:
            data = self._load()
            raw = data.get(session_key)
        if raw is None:
            return BridgeSessionState()
        return BridgeSessionState.from_dict(raw)

    def set(self, session_key: str, state: BridgeSessionState) -> None:
        with self._lock:
            data = dict(self._load())
            data[session_key] = asdict(state)
            self._save(data)

    def update(self, session_key: str, **changes: Any) -> BridgeSessionState:
        with self._lock:
            data = dict(self._load())
            state = BridgeSessionState.from_dict(
                data.get(session_key) or {},
            )
            for key, value in changes.items():
                setattr(state, key, value)
            data[session_key] = asdict(state)
            if self._save(data):
                return state
            return BridgeSessionState.from_dict(
                self._load().get(session_key) or {},
            )

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        try:
            self._cache = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._cache = {}
        except (ValueError, OSError):
            logger.warning(
                "bridge session store unreadable, starting fresh: %s",
                self.path,
                exc_info=True,
            )
            self._cache = {}
        return self._cache

    def _save(self, data: Dict[str, Dict[str, Any]]) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except OSError:
            logger.warning(
                "bridge session store write failed: %s",
                self.path,
                exc_info=True,
            )
            return False
        self._cache = data
        return True
