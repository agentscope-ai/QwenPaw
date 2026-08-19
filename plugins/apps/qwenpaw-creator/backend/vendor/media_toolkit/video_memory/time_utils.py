# -*- coding: utf-8 -*-
"""Time string utilities for the graph-memory build pipeline.

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/skill/script/build_memory/time_utils.py).
License: Apache-2.0; see backend/vendor/NOTICE.md. Unmodified.
"""


def time_str_to_sec(t: str) -> float:
    parts = t.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(t)


def sec_to_time_str(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
