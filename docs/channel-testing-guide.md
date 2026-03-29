# Channel 测试指南

## 概述

本指南介绍如何测试 CoPaw 的 Channel 模块。我们采用**契约优先**的测试方式，所有 Channel 必须满足 BaseChannel 接口契约。

```
tests/
├── contract/channels/          # 契约测试（主要）⭐
│   ├── __init__.py            # ChannelContractTest 基类
│   ├── test_console_contract.py    # 官方模板：简单 Channel
│   ├── test_dingtalk_contract.py   # 官方模板：复杂 Channel
│   ├── test_feishu_contract.py     # 官方模板：复杂 Channel
│   └── test_*_contract.py          # 其余 8 个 Channel
│
└── unit/channels/              # 单元测试补充（可选）
    └── test_base_core.py        # BaseChannel 内部逻辑（防抖/合并/权限）
```

---

## 快速开始

### 运行所有 Channel 测试

```bash
# 运行所有契约测试（128 个测试，全部应通过）
pytest tests/contract/channels/ -v

# 检查契约覆盖率
make check-contracts

# 运行可选单元测试
pytest tests/unit/channels/test_base_core.py -v
```

### 检查契约覆盖率

```bash
$ make check-contracts

📊 Channel 契约测试覆盖率
   总 Channel 数: 11
   有契约测试: 12
   缺失: 0 ✅

✅ 已测试: ConsoleChannel, DingTalkChannel, FeishuChannel,
          DiscordChannel, IMessageChannel, MQTTChannel,
          MatrixChannel, MattermostChannel, QQChannel,
          TelegramChannel, VoiceChannel

🎉 所有 Channel 都有契约测试！
```

---

## 契约测试基类

`ChannelContractTest` 提供**四层防护**机制来捕获破坏性变更：

| 层级 | 测试 | 捕获问题 |
|------|------|---------|
| 1 | `test_no_abstract_methods_remaining` | BaseChannel 新增抽象方法 |
| 2 | `test_no_abstractmethods__in_instance` | 无法实例化（未实现方法） |
| 3 | `test_required_methods_not_raising_not_implemented` | 方法仍抛出 NotImplementedError |
| 4 | `test_start/stop_method_signature_compatible` | 方法签名变更破坏子类 |

---

## 添加新 Channel

### 第一步：创建契约测试（必需）

复制官方模板：

```python
# tests/contract/channels/test_yourchannel_contract.py

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from src.copaw.app.channels.base import BaseChannel


class TestYourChannelContract(ChannelContractTest):
    """
    你的 Channel 契约测试。

    验证你的 Channel 是否正确实现所有 BaseChannel 抽象方法，
    并保持接口兼容性。
    """

    def create_instance(self) -> "BaseChannel":
        """提供用于契约测试的 Channel 实例。"""
        from src.copaw.app.channels.yourchannel.channel import YourChannel

        process = AsyncMock()

        return YourChannel(
            process=process,
            enabled=True,
            bot_prefix="[Test]",
            show_tool_details=False,
            filter_tool_messages=True,
            # 添加其他必需参数
        )

    # 可选：添加 Channel 特定契约测试
    def test_your_channel_specific_feature(self, instance):
        """你的 Channel 特定：验证自定义行为。"""
        assert hasattr(instance, 'your_custom_attribute')
```

### 第二步：验证契约通过

```bash
pytest tests/contract/channels/test_yourchannel_contract.py -v
```

### 第三步：检查覆盖率

```bash
make check-contracts
# 应显示你的 Channel 在已测试列表中
```

---

## 官方模板

### 模板 A：简单 Channel（Console）

```python
# tests/contract/channels/test_console_contract.py
"""官方模板：简单 Channel，最小配置。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from src.copaw.app.channels.base import BaseChannel


def create_mock_process_handler():
    """为 Channel 测试创建 mock process handler。"""
    mock = AsyncMock()

    async def mock_process(*args, **kwargs):
        from unittest.mock import MagicMock

        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        yield mock_event

    mock.side_effect = mock_process
    return mock


class TestConsoleChannelContract(ChannelContractTest):
    """ConsoleChannel 契约验证。"""

    def create_instance(self) -> "BaseChannel":
        """提供用于契约测试的 ConsoleChannel 实例。"""
        from src.copaw.app.channels.console.channel import ConsoleChannel

        process = create_mock_process_handler()
        return ConsoleChannel(
            process=process,
            enabled=True,
            bot_prefix="[TEST] ",
            show_tool_details=False,
            filter_tool_messages=True,
        )
```

### 模板 B：复杂 Channel 带 HTTP（DingTalk）

```python
# tests/contract/channels/test_dingtalk_contract.py
"""官方模板：复杂 Channel，带 Token 缓存和 HTTP。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from src.copaw.app.channels.base import BaseChannel


class TestDingTalkChannelContract(ChannelContractTest):
    """DingTalkChannel 契约验证。"""

    @pytest.fixture(autouse=True)
    def _setup_dingtalk_env(self, tmp_path):
        """为 DingTalk 测试设置隔离环境。"""
        self._media_dir = tmp_path / ".copaw" / "media"
        self._media_dir.mkdir(parents=True, exist_ok=True)

    def create_instance(self) -> "BaseChannel":
        """提供用于契约测试的 DingTalkChannel 实例。"""
        from src.copaw.app.channels.dingtalk.channel import DingTalkChannel

        process = AsyncMock()

        return DingTalkChannel(
            process=process,
            enabled=True,
            client_id="test_client_id",
            client_secret="test_client_secret",
            bot_prefix="[Test]",
            media_dir=str(self._media_dir),
            show_tool_details=False,
            filter_tool_messages=True,
        )

    # DingTalk 特定契约
    def test_has_token_caching_attributes(self, instance):
        """DingTalk 特定：必须有 Token 缓存机制。"""
        assert hasattr(instance, "_token_value")
        assert hasattr(instance, "_token_expires_at")

    def test_has_session_webhook_store(self, instance):
        """DingTalk 特定：必须有 Session webhook 存储。"""
        assert hasattr(instance, "_session_webhook_store")
        assert isinstance(instance._session_webhook_store, dict)
```

---

## 测试场景

### 场景 1：修改 BaseChannel

修改 `BaseChannel` 时，运行所有 Channel 的契约测试：

```bash
# 验证无破坏性变更
pytest tests/contract/channels/ -v

# 如有测试失败，说明破坏了契约！
```

**四层防护将捕获**：
- BaseChannel 新增抽象方法
- 方法签名变更破坏兼容性
- 缺少必需方法
- 方法仍抛出 NotImplementedError

### 场景 2：添加新 Channel

```bash
# 1. 从模板创建契约测试
# cp tests/contract/channels/test_console_contract.py \
#    tests/contract/channels/test_yourchannel_contract.py

# 2. 用你 Channel 的必需参数实现 create_instance()

# 3. 运行契约测试
pytest tests/contract/channels/test_yourchannel_contract.py -v

# 4. 验证覆盖率
make check-contracts
```

### 场景 3：修复 Bug

```bash
# 1. 先写回归测试
# 添加到该 Channel 的契约测试文件

# 2. 运行测试确认失败
pytest tests/contract/channels/test_dingtalk_contract.py -v

# 3. 修复 Channel 实现中的 bug

# 4. 运行所有契约测试确保无回归
pytest tests/contract/channels/ -v
```

---

## Makefile 命令

```makefile
# 检查契约覆盖率（显示哪些 Channel 缺少测试）
make check-contracts

# 运行所有契约测试
pytest tests/contract/channels/ -v

# 运行特定 Channel 契约测试
pytest tests/contract/channels/test_dingtalk_contract.py -v

# 运行单元测试补充（可选）
pytest tests/unit/channels/test_base_core.py -v
```

---

## 契约测试覆盖率（当前状态）

```
✅ ConsoleChannel      - 官方模板（简单）
✅ DingTalkChannel     - 官方模板（复杂带 HTTP）
✅ FeishuChannel       - 官方模板（复杂）
✅ DiscordChannel      - 批量生成
✅ TelegramChannel     - 批量生成
✅ QQChannel           - 批量生成
✅ IMessageChannel     - 批量生成
✅ MQTTChannel         - 批量生成
✅ MatrixChannel       - 批量生成
✅ MattermostChannel   - 批量生成
✅ VoiceChannel        - 批量生成

总计：11 个 Channel，12 个已测试（包含 BaseChannel）
缺失：0
```

---

## 核心原则

### 1. 契约测试是主要的

契约测试验证所有 Channel 满足 BaseChannel 接口。防止"修 Console 破坏 DingTalk"的回归。

### 2. 所有 Channel 都有契约测试

官方团队为所有 11 个 Channel 生成了契约测试。

### 3. 四层防护

`ChannelContractTest` 基类有四层机制捕获破坏性变更：

1. **抽象方法检查** - 捕获新方法
2. **实例化检查** - 捕获未实现
3. **方法覆盖检查** - 捕获 NotImplementedError
4. **签名检查** - 捕获参数变更

### 4. 契约测试 = CI 门禁

契约测试必须在 CI 中通过。破坏契约将阻断 PR。

---

## 故障排查

### Q：契约测试失败显示"未实现抽象方法"

**原因**：BaseChannel 新增抽象方法，或你的 Channel 未实现必需方法。

**修复**：在你的 Channel 中实现缺失的方法。

### Q：契约测试失败显示"包含 NotImplementedError"

**原因**：你的 Channel 继承了抛出 NotImplementedError 的 BaseChannel 方法。

**修复**：用真实实现覆盖该方法。

### Q：契约测试失败显示签名不匹配

**原因**：你的方法签名与 BaseChannel 不匹配（如添加了必需参数）。

**修复**：确保你的方法接受与 BaseChannel 相同的参数。

### Q：运行测试时出现导入错误

```bash
# 确保在项目根目录且包已安装
cd /Users/hex/work/CoPaw
pip install -e ".[dev]"
pytest tests/contract/channels/ -v
```

---

## 快速参考

| 任务 | 命令 |
|------|------|
| 检查覆盖率 | `make check-contracts` |
| 运行所有契约测试 | `pytest tests/contract/channels/ -v` |
| 运行特定 Channel | `pytest tests/contract/channels/test_dingtalk_contract.py -v` |
| 添加新 Channel 测试 | 复制 `test_console_contract.py` 模板 |
| 验证无回归 | `pytest tests/contract/channels/ -v` |

---

## 总结

| 方面 | 当前状态 |
|------|----------|
| Channel 覆盖 | 11/11 (100%) |
| 契约测试 | 128 通过 ✅ |
| 官方模板 | Console, DingTalk, Feishu |
| 防护层 | 4 层 |
| CI 门禁 | 是 - 契约测试必须通过 |
