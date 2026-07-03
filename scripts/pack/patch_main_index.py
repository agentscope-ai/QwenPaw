#!/usr/bin/env python3
"""Patch the main OSS metadata index to advertise the plugins product.

Ensures the top-level ``metadata/index.json`` has a ``products.plugins``
entry pointing to the plugins sub-index.

Usage::

    python scripts/pack/patch_main_index.py \
        --index main-index.json \
        --out   main-index.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def patch_index(index: dict) -> dict:
    """Add/update the ``plugins`` product entry (mutates *index*)."""
    index.setdefault("products", {})
    index["products"]["plugins"] = {
        "name": {"zh-CN": "插件", "en-US": "Plugins"},
        "index_url": "/metadata/plugins/index.json",
    }
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    return index


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Patch main metadata index with plugins product entry.",
    )
    parser.add_argument(
        "--index",
        required=True,
        type=Path,
        help="Path to the main index.json",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output path for the patched index.json",
    )
    args = parser.parse_args(argv)

    with open(args.index, encoding="utf-8") as f:
        index = json.load(f)

    patched = patch_index(index)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(patched, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
