# -*- coding: utf-8 -*-
"""Build grouping JSON and write + print per bi-clustering skill contract."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np


def jsonify_scalar(v: Any) -> Any:
    """Make a value JSON-serializable (numpy/pandas scalars)."""
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if hasattr(v, "item") and callable(getattr(v, "item")):
        try:
            return jsonify_scalar(v.item())
        except Exception:
            pass
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        if np.isnan(v):
            return None
        return float(v)
    return str(v)


def build_json_from_labels(ids: Sequence[Any], labels: Sequence[int]) -> Dict[str, List[Any]]:
    """
    Cluster labels as from sklearn: 0..K-1 -> keys \"cluster 1\"..\"cluster K\"; -1 -> \"noise\".
    Keys ordered cluster 1, cluster 2, ... then noise.
    """
    from collections import defaultdict

    buckets: Dict[str, List[Any]] = defaultdict(list)
    for rid, lab in zip(ids, labels):
        lab_i = int(lab)
        if lab_i < 0:
            key = "noise"
        else:
            key = f"cluster {lab_i + 1}"
        buckets[key].append(jsonify_scalar(rid))

    ordered: Dict[str, List[Any]] = {}
    ckeys = sorted(
        (k for k in buckets if k.startswith("cluster ")),
        key=lambda x: int(x.split(maxsplit=1)[1]),
    )
    for k in ckeys:
        ordered[k] = buckets[k]
    if "noise" in buckets:
        ordered["noise"] = buckets["noise"]
    return ordered


def write_print_json(output_path: str, payload: Mapping[str, List[Any]]) -> str:
    """Write JSON to output_path, print payload JSON to stdout, relative path to stderr."""
    abs_path = os.path.abspath(output_path)
    d = os.path.dirname(abs_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        json.dump(dict(payload), f, ensure_ascii=False, indent=2)

    printed = json.dumps(dict(payload), ensure_ascii=False, indent=2)
    print(printed)
    rel = os.path.relpath(abs_path)
    print(rel, file=sys.stderr)
    return rel
