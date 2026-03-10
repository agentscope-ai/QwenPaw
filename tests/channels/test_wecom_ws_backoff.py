# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.ws_client import next_backoff_seconds


def test_backoff_is_bounded() -> None:
    assert next_backoff_seconds(1, 1, 30) == 1
    assert next_backoff_seconds(2, 1, 30) == 2
    assert next_backoff_seconds(100, 1, 30) == 30
