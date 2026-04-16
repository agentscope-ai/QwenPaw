#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check that all Channel subclasses have Contract test coverage.

Usage:
    python scripts/check_channel_contracts.py

Notes:
    - Static scan, no dependencies required (including pytest)
    - Compares Channel classes in src/ with test files in tests/contract/

CI Integration (future):
    - Run on PR to ensure new Channels have contract tests
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def get_all_channel_classes() -> set[str]:
    """Scan all Channel subclasses from source code (non-runtime)."""
    src_dir = Path(__file__).parent.parent / "src"
    channels_dir = src_dir / "qwenpaw" / "app" / "channels"
    classes = set()

    for channel_file in channels_dir.rglob("channel.py"):
        content = channel_file.read_text()
        # Match class XXXChannel(BaseChannel)
        matches = re.findall(
            r"class\s+(\w+Channel)\s*\(\s*BaseChannel\s*\)",
            content,
        )
        classes.update(matches)

    return classes


def get_tested_channels_from_content() -> set[str]:
    """Read actual tested channel class names from test files."""
    contract_dir = (
        Path(__file__).parent.parent / "tests" / "contract" / "channels"
    )
    tested = set()

    if not contract_dir.exists():
        return tested

    for test_file in contract_dir.glob("test_*_contract.py"):
        content = test_file.read_text()
        # Find from XXXXX import YYYYChannel
        # Or find in create_instance return XXXXChannel(...)
        # Match common channel import patterns
        import_matches = re.findall(
            r"from\s+[\w.]+\s+import\s+(\w+Channel)",
            content,
        )
        # Also directly instantiated in create_instance
        instance_matches = re.findall(
            r"return\s+(\w+Channel)\s*\(",
            content,
        )
        tested.update(import_matches)
        tested.update(instance_matches)

    return tested


def main() -> int:
    all_channels = get_all_channel_classes()
    tested = get_tested_channels_from_content()
    untested = all_channels - tested

    print("\n📊 Channel Contract Coverage")
    print(f"   Total channels: {len(all_channels)}")
    print(f"   With tests:     {len(tested)}")
    print(f"   Missing:        {len(untested)}")

    if tested:
        print(f"\n✅ Tested: {', '.join(sorted(tested))}")

    if untested:
        print("\n❌ Missing contract tests:")
        for name in sorted(untested):
            # Convert to snake_case for filename suggestion
            snake = (
                re.sub(r"(?<!^)(?=[A-Z])", "_", name)
                .lower()
                .replace("_channel", "")
            )
            print(f"   - {name}")
            print(f"     👉 tests/contract/channels/test_{snake}_contract.py")
        print(
            "\n💡 Based on existing patterns, copy "
            "tests/contract/channels/test_console_contract.py",
        )
        return 1

    print("\n🎉 All channels have contract tests!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
