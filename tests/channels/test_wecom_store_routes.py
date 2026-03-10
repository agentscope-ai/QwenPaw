# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.schema import WeComRoute
from copaw.app.channels.wecom.store import RouteStore


def test_route_store_roundtrip(tmp_path) -> None:
    store = RouteStore(tmp_path / "routes.json")
    route = WeComRoute(
        session_id="wecom:user:alice",
        target_type="user",
        target_id="alice",
        chat_type="single",
        last_seen_at=1,
    )

    store.save_route(route)
    loaded = store.get_route("wecom:user:alice")

    assert loaded is not None
    assert loaded.target_id == "alice"
