# -*- coding: utf-8 -*-
"""Persistence helpers for the WeCom custom channel plugin."""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional

from .schema import WeComRoute, route_from_dict, route_to_dict


class ProcessedMessageStore:
    """Keep a bounded set of processed message ids with JSON persistence."""

    def __init__(self, path: Optional[Path], max_items: int = 1024):
        self.path = Path(path) if path else None
        self.max_items = max(1, int(max_items))
        self._seen: "OrderedDict[str, None]" = OrderedDict()
        self.load()

    def load(self) -> None:
        """Load previously seen ids from disk."""

        if self.path is None or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            message_id = str(item or "").strip()
            if not message_id:
                continue
            self._seen[message_id] = None
        self._trim()

    def mark_seen(self, message_id: str) -> bool:
        """Return True when the message id already exists."""

        key = str(message_id or "").strip()
        if not key:
            raise ValueError("message_id is required")
        existed = key in self._seen
        if existed:
            self._seen.move_to_end(key)
            return True
        self._seen[key] = None
        self._trim()
        self.dump()
        return False

    def dump(self) -> None:
        """Persist current ids to disk."""

        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(list(self._seen.keys()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _trim(self) -> None:
        while len(self._seen) > self.max_items:
            self._seen.popitem(last=False)


class RouteStore:
    """Persist session to target route mappings as JSON."""

    def __init__(self, path: Optional[Path]):
        self.path = Path(path) if path else None
        self._routes: Dict[str, WeComRoute] = {}
        self.load()

    def load(self) -> None:
        """Load route mappings from disk."""

        if self.path is None or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(raw, dict):
            return
        routes: Dict[str, WeComRoute] = {}
        for session_id, payload in raw.items():
            route = route_from_dict(
                {"session_id": session_id, **dict(payload or {})},
            )
            if route is not None:
                routes[route.session_id] = route
        self._routes = routes

    def save_route(self, route: WeComRoute) -> None:
        """Insert or replace a route and persist it."""

        self._routes[route.session_id] = route
        self.dump()

    def get_route(self, session_id: str) -> Optional[WeComRoute]:
        """Return a persisted route by session id."""

        return self._routes.get(str(session_id or "").strip())

    def dump(self) -> None:
        """Persist all route mappings to disk."""

        payload = {
            session_id: route_to_dict(route)
            for session_id, route in self._routes.items()
        }
        for item in payload.values():
            item.pop("session_id", None)
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
