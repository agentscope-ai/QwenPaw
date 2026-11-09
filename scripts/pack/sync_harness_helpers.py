#!/usr/bin/env python3
"""Vendor the canonical IO helper into the two official Harness plugins."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

VENDORS = ("codex", "qoder")
HEADER = (
    "# Generated from plugins/harness/_shared/io_helpers.py; do not edit.\n"
    "# Update the shared source, then run:\n"
    "# python scripts/pack/sync_harness_helpers.py --write\n"
)


def expected_helper(harness_root: Path) -> str:
    """Keep the encoding pragma first and preserve canonical implementation."""
    source = (harness_root / "_shared" / "io_helpers.py").read_text(encoding="utf-8")
    pragma, implementation = source.split("\n", 1)
    return pragma + "\n" + HEADER + implementation


def check_helper(plugin_dir: Path) -> None:
    """Fail for a missing or manually changed generated official helper."""
    target = plugin_dir / "io_helpers.py"
    expected = expected_helper(plugin_dir.parent)
    if not target.is_file() or target.read_text(encoding="utf-8") != expected:
        raise ValueError(
            f"{target}: generated Harness helper is out of sync; "
            "run python scripts/pack/sync_harness_helpers.py --write"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--plugin", choices=VENDORS, action="append")
    args = parser.parse_args()
    harness_root = Path(__file__).resolve().parents[2] / "plugins" / "harness"
    # A source checkout may contain only one of the independently built plugins.
    vendors = args.plugin if args.plugin is not None else [
        vendor for vendor in VENDORS if (harness_root / vendor).is_dir()
    ]
    try:
        for vendor in vendors:
            plugin_dir = harness_root / vendor
            if not plugin_dir.is_dir():
                raise ValueError(f"Harness plugin directory is missing: {plugin_dir}")
            if args.write:
                (plugin_dir / "io_helpers.py").write_text(
                    expected_helper(harness_root), encoding="utf-8", newline="\n"
                )
            else:
                check_helper(plugin_dir)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
