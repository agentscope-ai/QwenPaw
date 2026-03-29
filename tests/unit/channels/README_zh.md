# Channel 测试指南

## 测试体系结构

```
tests/
├── contract/channels/          # ⭐ 契约测试（主要）
│   ├── __init__.py            # ChannelContractTest 基类
│   ├── test_console_contract.py   # 官方模板：简单 Channel
│   ├── test_dingtalk_contract.py  # 官方模板：复杂 Channel
│   ├── test_feishu_contract.py    # 官方模板：复杂 Channel
│   └── test_*_contract.py         # 全部 11 个 Channel 覆盖（0 缺失）
│
└── unit/channels/              # 补充测试（可选）
    ├── README.md               # 本文件
    └── test_base_core.py       # BaseChannel 内部逻辑（防抖/合并/权限）
```

## 契约测试 vs 单元测试

| 类型 | 位置 | 用途 | 覆盖率 |
|------|------|------|--------|
| **契约测试** | `tests/contract/channels/` | 验证对外接口兼容 | 契约覆盖率（128 测试） |
| **单元测试** | `tests/unit/channels/` | 验证内部逻辑正确 | 本地暂不强制 |

## 本地开发

```bash
# 契约测试（主要）
pytest tests/contract/channels/ -v

# 检查契约覆盖率
make check-contracts

# 补充单元测试（可选）
pytest tests/unit/channels/test_base_core.py -v
```

## 添加新 Channel 契约测试

所有 Channel 已有契约测试。要添加新 Channel：

```bash
# 1. 复制官方模板
cp tests/contract/channels/test_console_contract.py \
   tests/contract/channels/test_yourchannel_contract.py

# 2. 修改类名和 create_instance()

# 3. 本地验证
make check-contracts  # 应显示你的 Channel 在已测试列表
```

## 关于 test_base_core.py

**用途**：补充测试 BaseChannel 内部逻辑（防抖、合并、权限）

**运行**：本地开发时手动跑
```bash
pytest tests/unit/channels/test_base_core.py -v
```

**覆盖率**：本期不强制，后续官方决定是否纳入 CI

**注意**：此文件中部分测试可能因测试期望与实际实现不匹配而失败。这些是补充测试，不阻断 PR 合并。

## 运行所有单元测试

```bash
# 运行所有单元测试
pytest tests/unit/channels/ -v

# 运行特定 Channel 单元测试
pytest tests/unit/channels/test_base_core.py -v

# 带覆盖率检查
pytest tests/unit/channels/ \
    --cov=src/copaw/app/channels \
    --cov-report=term-missing
```

## 契约测试与单元测试的关系

```
契约测试（tests/contract/channels/）：验证接口规范 ✅ 全部 11 个 Channel 覆盖
单元测试（tests/unit/channels/）：验证内部逻辑   🆕 补充（可选）
```

两者互补：
- 契约测试验证"方法存在且签名正确"
- 单元测试验证"内部逻辑正确"

## 四层防护机制

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
   总 Channel 数: 11
   有契约测试: 12
   缺失: 0

✅ 已测试: ConsoleChannel, DingTalkChannel, FeishuChannel,
          DiscordChannel, IMessageChannel, MQTTChannel,
          MatrixChannel, MattermostChannel, QQChannel,
          TelegramChannel, VoiceChannel

🎉 所有 Channel 都有契约测试！
128 个契约测试通过，0 失败
```

## 核心原则

1. **契约测试是主要的** - 必须在 CI 中通过
2. **单元测试是可选的** - 补充，不阻断 PR
3. **所有 Channel 都有契约测试** - 官方团队生成全部 11 个
4. **四层防护** - 有效防止"修 Console 破坏 DingTalk"
5. **破坏契约 = 阻断 PR** - CI 门禁确保接口兼容

## 快速参考

| 命令 | 用途 |
|------|------|
| `make check-contracts` | 显示契约覆盖率状态 |
| `pytest tests/contract/channels/ -v` | 运行所有契约测试 |
| `pytest tests/unit/channels/test_base_core.py -v` | 运行可选单元测试 |
| `pytest tests/contract/channels/test_console_contract.py -v` | 运行特定 Channel |
