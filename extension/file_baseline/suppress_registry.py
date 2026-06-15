# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SuppressEntry:
    agent_id: str
    path: str
    sha256: str
    expires_at: float


class SuppressRegistry:
    """Ignore watch events shortly after operator approve/restore."""

    def __init__(self) -> None:
        self._entries: list[SuppressEntry] = []

    def register(
        self,
        *,
        agent_id: str,
        path: str,
        sha256: str,
        ttl_seconds: float = 2.0,
    ) -> None:
        self._prune()
        self._entries.append(
            SuppressEntry(
                agent_id=agent_id,
                path=path,
                sha256=sha256,
                expires_at=time.time() + ttl_seconds,
            ),
        )

    def should_ignore(
        self,
        *,
        agent_id: str,
        path: str,
        content: bytes,
    ) -> bool:
        self._prune()
        current_sha = hashlib.sha256(content).hexdigest()
        for entry in self._entries:
            if (
                entry.agent_id == agent_id
                and entry.path == path
                and entry.sha256 == current_sha
                and entry.expires_at >= time.time()
            ):
                return True
        return False

    def clear_path(self, agent_id: str, path: str) -> None:
        self._entries = [
            entry
            for entry in self._entries
            if not (entry.agent_id == agent_id and entry.path == path)
        ]

    def _prune(self) -> None:
        now = time.time()
        self._entries = [entry for entry in self._entries if entry.expires_at >= now]
