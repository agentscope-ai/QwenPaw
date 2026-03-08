#!/usr/bin/env python3
"""
测试会话打断功能
"""

import sys
sys.path.insert(0, '/Users/tingchi/copaw/src')

from copaw.agents.react_agent import CoPawAgent

# 创建 Agent 实例
agent = CoPawAgent()

# 测试打断关键词
test_cases = [
    ("stop", True),
    ("停下来", True),
    ("停下", True),
    ("停止", True),
    ("别做了", True),
    ("别继续", True),
    ("取消", True),
    ("中断", True),
    ("停下来停下来", True),
    ("先停下来", True),
    ("帮我停下来", True),
    ("继续工作", False),
    ("帮我写个文件", False),
    ("搜索新闻", False),
    ("", False),
    (None, False),
]

print("=" * 60)
print("测试会话打断功能")
print("=" * 60)

passed = 0
failed = 0

for query, expected in test_cases:
    result = agent._is_interrupt_keyword(query)
    status = "✅" if result == expected else "❌"
    
    if result == expected:
        passed += 1
    else:
        failed += 1
    
    print(f"{status} '{query}' -> {result} (期望：{expected})")

print("=" * 60)
print(f"总计：{passed} 通过，{failed} 失败")
print("=" * 60)

if failed == 0:
    print("🎉 所有测试通过！")
else:
    print(f"⚠️  有 {failed} 个测试失败")
    sys.exit(1)
