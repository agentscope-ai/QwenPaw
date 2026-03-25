# -*- coding: utf-8 -*-
"""Persistent state store for Wechat channel."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class WechatStateStore:
    """Persist get_updates_buf (long-poll sync) and context token per peer."""

    def __init__(self, state_file: Path):
        self._state_file = state_file
        self._lock = asyncio.Lock()
        self._get_updates_buf: str = ""
        self._context_tokens: Dict[str, str] = {}

    @property
    def get_updates_buf(self) -> str:
        return self._get_updates_buf

    async def load(self) -> None:
        """Load state from disk if file exists."""
        if not self._state_file.is_file():
            return
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(
                "wechat state load failed file=%s error=%s",
                self._state_file,
                exc,
            )
            return
        self._get_updates_buf = str(payload.get("get_updates_buf") or "")
        raw_tokens = payload.get("context_tokens") or {}
        if isinstance(raw_tokens, dict):
            self._context_tokens = {
                str(k): str(v)
                for k, v in raw_tokens.items()
                if isinstance(k, str) and isinstance(v, str) and v
            }

    async def set_get_updates_buf(self, get_updates_buf: str) -> None:
        """Update get_updates_buf and flush to disk."""
        async with self._lock:
            self._get_updates_buf = get_updates_buf or ""
            await self._flush_locked()

    async def set_context_token(self, peer_id: str, token: str) -> None:
        """Set per-peer context token and flush to disk."""
        if not peer_id:
            return
        async with self._lock:
            if token:
                self._context_tokens[peer_id] = token
            else:
                self._context_tokens.pop(peer_id, None)
            await self._flush_locked()

    def get_context_token(self, peer_id: str) -> Optional[str]:
        """Get per-peer context token."""
        return self._context_tokens.get(peer_id)

    async def _flush_locked(self) -> None:
        """Write state atomically to disk. Caller must hold _lock."""
        payload = {
            "get_updates_buf": self._get_updates_buf,
            "context_tokens": self._context_tokens,
        }
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_file.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self._state_file)
        except OSError as exc:
            logger.warning(
                "wechat state flush failed file=%s error=%s",
                self._state_file,
                exc,
            )
