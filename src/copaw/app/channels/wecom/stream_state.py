# -*- coding: utf-8 -*-
"""State store for WeCom intelligent-bot stream replies."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class WeComStreamState:
    """Mutable stream snapshot returned to WeCom polling callbacks."""

    stream_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished: bool = False
    content: str = ""
    error: str = ""
    msg_id: str = ""

    def append_text(self, text: str) -> None:
        chunk = (text or "").strip()
        if not chunk:
            return
        if self.content:
            self.content = f"{self.content}\n{chunk}"
        else:
            self.content = chunk
        self.updated_at = time.time()

    def mark_finished(self, *, error: str = "") -> None:
        self.finished = True
        if error:
            self.error = error.strip()
            if not self.content:
                self.content = self.error
        self.updated_at = time.time()


class WeComStreamStore:
    """In-memory stream registry for WeCom intelligent-bot polling."""

    def __init__(self, ttl_seconds: float = 600.0) -> None:
        self.ttl_seconds = max(float(ttl_seconds or 600.0), 30.0)
        self._streams: dict[str, WeComStreamState] = {}
        self._msgid_to_stream_id: dict[str, str] = {}

    def create(self, *, msg_id: str = "") -> WeComStreamState:
        self.prune()
        stream_id = secrets.token_hex(12)
        state = WeComStreamState(stream_id=stream_id, msg_id=(msg_id or "").strip())
        self._streams[stream_id] = state
        if state.msg_id:
            self._msgid_to_stream_id[state.msg_id] = stream_id
        return state

    def get(self, stream_id: str) -> WeComStreamState | None:
        self.prune()
        return self._streams.get((stream_id or "").strip())

    def get_by_msg_id(self, msg_id: str) -> WeComStreamState | None:
        self.prune()
        sid = self._msgid_to_stream_id.get((msg_id or "").strip())
        if not sid:
            return None
        return self._streams.get(sid)

    def prune(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        expired = [
            stream_id
            for stream_id, state in self._streams.items()
            if state.updated_at < cutoff
        ]
        for stream_id in expired:
            state = self._streams.pop(stream_id, None)
            if state and state.msg_id:
                self._msgid_to_stream_id.pop(state.msg_id, None)
