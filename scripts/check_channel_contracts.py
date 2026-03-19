#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查所有 Channel 子类是否有 Contract 测试覆盖。

用法:
    python scripts/check_channel_contracts.py

说明:
    - 静态扫描，无需安装依赖（包括 pytest）
    - 对比 src/ 中的 Channel 类和 tests/contract/ 中的测试文件

CI 集成（未来）:
    - 在 PR 时运行，确保新 Channel 有 contract 测试
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def get_all_channel_classes() -> set[str]:
    """从源码中扫描所有 Channel 子类（非运行时）."""
    src_dir = Path(__file__).parent.parent / "src"
    channels_dir = src_dir / "copaw" / "app" / "channels"
    classes = set()

    for channel_file in channels_dir.rglob("channel.py"):
        content = channel_file.read_text()
        # 匹配 class XXXChannel(BaseChannel)
        matches = re.findall(
            r"class\s+(\w+Channel)\s*\(\s*BaseChannel\s*\)", content
        )
        classes.update(matches)

    return classes


def get_tested_channels_from_content() -> set[str]:
    """从测试文件中读取实际测试的 channel 类名."""
    contract_dir = (
        Path(__file__).parent.parent / "tests" / "contract" / "channels"
    )
    tested = set()

    if not contract_dir.exists():
        return tested

    for test_file in contract_dir.glob("test_*_contract.py"):
        content = test_file.read_text()
        # 查找 from XXXXX import YYYYChannel
        # 或查找 create_instance 中的 return XXXXChannel(...)
        # 匹配常见的 channel 导入模式
        import_matches = re.findall(
            r"from\s+[\w.]+\s+import\s+(\w+Channel)",
            content,
        )
        # 还有可能在 create_instance 中直接实例化
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

    print(f"\n📊 Channel Contract Coverage")
    print(f"   Total channels: {len(all_channels)}")
    print(f"   With tests:     {len(tested)}")
    print(f"   Missing:        {len(untested)}")

    if tested:
        print(f"\n✅ Tested: {', '.join(sorted(tested))}")

    if untested:
        print(f"\n❌ Missing contract tests:")
        for name in sorted(untested):
            # 转换为 snake_case 用于文件名建议
            snake = (
                re.sub(r"(?<!^)(?=[A-Z])", "_", name)
                .lower()
                .replace("_channel", "")
            )
            print(f"   - {name}")
            print(f"     👉 tests/contract/channels/test_{snake}_contract.py")
        print(
            f"\n💡 基于现有模式，复制 tests/contract/channels/test_dingtalk_contract.py"
        )
        return 1

    print(f"\n🎉 All channels have contract tests!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
