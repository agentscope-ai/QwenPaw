# -*- coding: utf-8 -*-
"""Make kb-quality-eval / prd-kb-ingest skill scripts importable for tests.

These skills ship as standalone script dirs (not packages) loaded via
``sys.path`` at runtime. Tests need the same path setup before importing
``catalog``, ``checks_*``, ``water_level`` and the ingest ``granularity``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SKILL = _REPO / ".cursor" / "skills" / "kb-quality-eval" / "scripts"
_INGEST = _REPO / ".cursor" / "skills" / "prd-kb-ingest" / "scripts"
_DERIVE = _REPO / ".cursor" / "skills" / "kb-test-derive" / "scripts"

for _p in (_SKILL, _INGEST, _DERIVE):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
