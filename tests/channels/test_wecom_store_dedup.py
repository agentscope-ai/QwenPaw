# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.store import ProcessedMessageStore


def test_processed_message_store_detects_duplicate(tmp_path) -> None:
    store = ProcessedMessageStore(tmp_path / "processed.json", max_items=2)

    assert store.mark_seen("m1") is False
    assert store.mark_seen("m1") is True


def test_processed_message_store_trims_oldest(tmp_path) -> None:
    store = ProcessedMessageStore(tmp_path / "processed.json", max_items=2)

    assert store.mark_seen("m1") is False
    assert store.mark_seen("m2") is False
    assert store.mark_seen("m3") is False

    reloaded = ProcessedMessageStore(tmp_path / "processed.json", max_items=2)
    assert reloaded.mark_seen("m1") is False
