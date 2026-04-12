# Channel 测试指南

## 测试体系结构

```
tests/
├── contract/channels/          # ⭐ 契约测试（必需）
│   ├── __init__.py            # ChannelContractTest 基类
│   ├── test_console_contract.py   # 简单 Channel 参考
│   ├── test_dingtalk_contract.py  # 复杂 Channel 参考
│   ├── test_feishu_contract.py    # 复杂 Channel 参考
│   └── test_*_contract.py         # 全部 11 个 Channel 覆盖（0 缺失）
│
└── unit/channels/              # 单元测试（全量）
    ├── README.md               # 本文件
    ├── test_base_core.py       # BaseChannel 内部逻辑（68 个测试）
    ├── test_console.py         # ConsoleChannel 单元测试（26 个测试）
    ├── test_dingtalk.py        # DingTalkChannel 单元测试（159 个测试）
    ├── test_discord.py         # DiscordChannel 单元测试（55 个测试）
    ├── test_feishu.py          # FeishuChannel 单元测试（120 个测试）
    ├── test_imessage.py        # IMessageChannel 单元测试（37 个测试）
    ├── test_matrix.py          # MatrixChannel 单元测试（55 个测试）
    ├── test_mattermost.py      # MattermostChannel 单元测试（82 个测试）
    ├── test_mqtt.py            # MQTTChannel 单元测试（50 个测试）
    ├── test_onebot_channel.py  # OneBotChannel 单元测试（53 个测试）
    ├── test_qq.py              # QQChannel 单元测试（116 个测试）
    ├── test_telegram.py        # TelegramChannel 单元测试（93 个测试）
    ├── test_voice.py           # VoiceChannel 单元测试（37 个测试）
    ├── test_wecom.py           # WecomChannel 单元测试（69 个测试）
    ├── test_weixin.py          # WeixinChannel 单元测试（78 个测试）
    └── test_xiaoyi.py          # XiaoyiChannel 单元测试（57 个测试）
```

## 契约测试 vs 单元测试

| 类型 | 位置 | 用途 | 状态 |
|------|------|------|------|
| **契约测试** | `tests/contract/channels/` | 验证对外接口兼容 | ✅ 128 个测试，CI 强卡点 |
| **单元测试** | `tests/unit/channels/` | 验证内部逻辑正确 | ✅ 1200+ 个测试，CI 强卡点 |

两种测试类型都需要在 CI 中通过。

## 各 Channel 单元测试覆盖率

| Channel | 测试数量 | 代码行数 | 复杂度 | 状态 |
|---------|----------|----------|--------|------|
| DingTalk | 159 | 3,708 | 高 | ✅ 完成 |
| Feishu | 120 | 2,652 | 高 | ✅ 完成 |
| QQ | 116 | 2,096 | 高 | ✅ 完成 |
| Telegram | 93 | 1,798 | 中高 | ✅ 完成 |
| Mattermost | 82 | 1,990 | 中高 | ✅ 完成 |
| Weixin | 78 | 1,617 | 中 | ✅ 完成 |
| Wecom | 69 | 1,504 | 中 | ✅ 完成 |
| BaseChannel (Core) | 68 | 1,390 | 核心逻辑 | ✅ 完成 |
| Console | 26 | 567 | 简单 | ✅ 完成 |
| Xiaoyi | 57 | 1,219 | 中 | ✅ 完成 |
| Discord | 55 | 945 | 中 | ✅ 完成 |
| Matrix | 55 | 1,068 | 中 | ✅ 完成 |
| OneBot | 53 | 756 | 中 | ✅ 完成 |
| MQTT | 50 | 922 | 中 | ✅ 完成 |
| IMessage | 37 | 1,007 | 简单-中 | ✅ 完成 |
| Voice | 37 | 651 | 简单 | ✅ 完成 |

**总计：1,200+ 单元测试，分布在 16 个测试文件中**

## 本地开发

```bash
# 运行所有契约测试（必需）
pytest tests/contract/channels/ -v

# 运行所有单元测试
pytest tests/unit/channels/ -v

# 运行特定 Channel 单元测试
pytest tests/unit/channels/test_dingtalk.py -v
pytest tests/unit/channels/test_feishu.py -v

# 带覆盖率检查运行
pytest tests/unit/channels/ \
    --cov=src/copaw/app/channels \
    --cov-report=term-missing

# 检查契约覆盖率状态
make check-contracts
```

## 添加新 Channel 测试

### 契约测试

全部 11 个 Channel 已有契约测试。添加新 Channel：

```bash
# 1. 复制官方模板
cp tests/contract/channels/test_console_contract.py \
   tests/contract/channels/test_yourchannel_contract.py

# 2. 修改类名和 create_instance()

# 3. 本地验证
make check-contracts  # 应显示你的 Channel 在已测试列表
```

### 单元测试

按照现有模式创建新的测试文件：

```python
# tests/unit/channels/test_yourchannel.py
"""YourChannel 实现的单元测试。"""

import pytest
from src.copaw.app.channels.your_channel import YourChannel


class TestYourChannel:
    """YourChannel 测试套件。"""

    def test_initialization(self):
        """测试 Channel 可以被初始化。"""
        channel = YourChannel()
        assert channel is not None

    def test_start_stop(self):
        """测试 Channel 生命周期。"""
        # 在此实现
        pass

    # 添加更多测试...
```

## CI/CD 集成

所有测试在 CI 流水线中运行，卡点策略如下：

| 阶段 | 测试类型 | 阈值 | 卡点类型 | 状态 |
|------|----------|------|----------|------|
| 1 | 契约测试 | 100% (128/128) | 🔴 硬卡点 | ⚠️ 暂时跳过（Pydantic 问题） |
| 2 | 单元测试 | 全部通过 | 🔴 硬卡点 | ✅ 运行中 |
| 3 | 覆盖率 | 55% 最低 | 🟡 软卡点 | ✅ 当前 57.36% |

**硬卡点**：失败将阻断 PR 合并
**软卡点**：仅警告，不阻断（`continue-on-error`）

### PR #2506 覆盖率变更

| 配置项 | 之前 | 之后 | 原因 |
|--------|------|------|------|
| `fail_under` | 0%（不检查） | 55% | 建立最低问责线 |
| `continue-on-error` | - | `true` | 不阻断紧急合并 |
| 当前覆盖率 | - | 57.36% | 高于阈值 2.36% 缓冲 |

**设计理由**：55% 反映现状同时建立可见问责。低于 55% = CI 警告。高于 55% = 通过。

## 四层防护机制（契约测试）

```
第一层: 抽象方法检查
├── test_no_abstract_methods_remaining
└── 捕获：BaseChannel 新增 @abstractmethod

第二层: 实例化检查
├── test_no_abstractmethods__in_instance
└── 捕获：无法创建实例（未实现方法）

第三层: 方法覆盖检查
├── test_required_methods_not_raising_not_implemented
└── 捕获：方法仍抛出 NotImplementedError

第四层: 签名兼容性检查
├── test_start_method_signature_compatible
├── test_stop_method_signature_compatible
├── test_resolve_session_id_signature_compatible
└── 捕获：方法签名变更破坏子类
```

## 当前状态

```
📊 Channel 契约测试覆盖率
   Channel 总数: 11
   有契约测试: 12
   缺失: 0
   契约测试: 128 个通过

📊 Channel 单元测试覆盖率
   Channel 总数: 11
   有单元测试: 11
   缺失: 0
   单元测试: 1,200+ 个通过

✅ 全部 Channel 完整覆盖：
   ConsoleChannel, DingTalkChannel, FeishuChannel,
   DiscordChannel, IMessageChannel, MQTTChannel,
   MatrixChannel, MattermostChannel, QQChannel,
   TelegramChannel, VoiceChannel

🎉 零缺失测试 - 契约测试和单元测试全部完成！
```

## 核心原则

1. **契约测试是主要的** - 必须在 CI 中通过（硬卡点）
2. **单元测试是必需的** - 必须在 CI 中通过（硬卡点）
3. **全部 Channel 有完整覆盖** - 同时包含契约测试和单元测试
4. **四层防护** - 有效防止"修 Console 破坏 DingTalk"
5. **测试失败 = 阻断 PR** - CI 卡点确保代码质量

## 快速参考

| 命令 | 用途 |
|------|------|
| `make check-contracts` | 显示契约覆盖率状态 |
| `pytest tests/contract/channels/ -v` | 运行所有契约测试 |
| `pytest tests/unit/channels/ -v` | 运行所有单元测试 |
| `pytest tests/unit/channels/test_dingtalk.py -v` | 运行特定 Channel 测试 |
| `pytest tests/unit/channels/ -k "test_init"` | 运行特定测试模式 |
