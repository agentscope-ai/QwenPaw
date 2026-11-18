#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare optional Harness plugins before restarting an upgraded host."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--working-dir", required=True, type=Path)
    parser.add_argument("--plugin-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    # Constants must see the selected existing directory on their first import.
    os.environ["QWENPAW_WORKING_DIR"] = str(args.working_dir.resolve())
    source = Path(__file__).resolve().parents[2] / "src"
    if source.is_dir():
        sys.path.insert(0, str(source))
    from qwenpaw.plugins.harness_migration import migrate_legacy_harnesses

    report = asyncio.run(
        migrate_legacy_harnesses(args.plugin_dir, apply=args.apply),
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
