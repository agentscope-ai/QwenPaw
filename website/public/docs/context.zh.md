# 上下文管理（Context Management）

## 概述

QwenPaw 当前默认的上下文策略是 **scroll**：旧轮次不会被总结后丢弃，而是先写入持久化 SQLite 历史库；当模型窗口接近上限时，再把中间历史从实时上下文中驱逐出去，并用一条紧凑的上下文内索引表示。之后 Agent 可以按需把原始历史读回来。

当前实现位置：

- `src/qwenpaw/agents/context/base.py` - 可插拔上下文管理接口
- `src/qwenpaw/agents/context/scroll/` - scroll 策略实现
- `src/qwenpaw/config/config.py` - `LightContextConfig`、`ContextCompactConfig`、`ScrollContextConfig`

旧的 AgentScope 原生压缩路径仍然可用，配置 `strategy: "native"` 即可切回；新配置默认使用 `strategy: "scroll"`。

## Scroll 工作方式

```mermaid
flowchart LR
    A[新轮次进入上下文] --> B[写穿到 history.db]
    B --> C{实时上下文超过触发比例?}
    C -->|否| D[保持当前窗口]
    C -->|是| E[保留固定头部 + 最近尾部]
    E --> F[驱逐中间历史]
    F --> G[把 seq 区间加入驱逐索引]
    G --> H[用一条索引消息重建实时上下文]
    H --> I[之后用 recall_history_python 回溯]
```

核心特性：

- **先持久化**：`ScrollContextManager` 在任何驱逐前，都会先把实时上下文写入 `{working_dir}/history.db`。
- **不依赖摘要**：被驱逐的内容由 `EvictionIndex` 表示，而不是由 LLM 生成一段压缩摘要。
- **可回溯原文**：索引中的每一行都带 `seq` 区间。Agent 可以调用 `recall_history_python`，再用 `ms.expand(lo, hi)` 读取完整原始记录。
- **跨会话历史**：历史行包含 `session_id` 和 `agent_id`，默认可检索当前 Agent 的所有历史会话；显式放宽时也能查询同一工作区内其他 Agent 的历史。
- **安全降级**：如果 scroll 无法构建，或 recall 工具无法安全运行，QwenPaw 会退回 native 上下文管理，避免把历史驱逐到无法读取的位置。

## 存储布局

| 路径                                    | 默认值                                          | 用途                                                                        |
| --------------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------- |
| `{working_dir}/history.db`              | `scroll_config.db_filename = "history.db"`      | 主要持久化 SQLite 历史库，是 scroll recall 的真相来源。                     |
| `{working_dir}/.scroll/repl/scratch.db` | 内部路径                                        | `recall_history_python` 的持久 scratch DB，多次 recall 调用之间保留派生表。 |
| `{working_dir}/.scroll/cells/`          | 内部路径                                        | recall 调用临时生成的 Python cell。                                         |
| `{working_dir}/dialog/YYYY-MM-DD.jsonl` | 可选                                            | `scroll_config.offload_dialog = true` 时写入的旧版 JSONL 归档。             |
| `{working_dir}/tool_results/`           | `tool_result_pruning_config.tool_results_cache` | 旧版分层工具结果裁剪中间件使用的文件缓存。                                  |

`history.db` 中的核心表是 `conversation_history`：

| 字段                                            | 含义                                                    |
| ----------------------------------------------- | ------------------------------------------------------- |
| `seq`                                           | 全局递增地址，驱逐索引和 recall helper 都用它定位历史。 |
| `session_id`, `agent_id`                        | 会话与 Agent 归属。                                     |
| `kind`                                          | `model_turn`、`context_msg` 或 `tool_result`。          |
| `role`, `name`, `content`                       | 角色/工具元数据以及可搜索的扁平文本。                   |
| `tool_call_id`, `tool_input`, `tool_state`      | 工具调用关联、参数和结果状态。                          |
| `headline`                                      | 模型主动写入的里程碑标题，用作驱逐索引叶子。            |
| `blocks`, `metadata`, `created_at`, `dedup_key` | 完整序列化块、元数据、时间戳和幂等键。                  |

如果当前 SQLite 支持 FTS5，QwenPaw 会维护 `conversation_history_fts` 全文索引；否则 `ms.search` 会降级为较慢的 `LIKE` 扫描。

## 实时上下文结构

发生驱逐后，实时上下文会被重建为：

```text
固定头部
  通常是第一条用户任务，由 scroll_config.pinned 控制。

驱逐索引占位消息
  一条名为 "memory" 的合成消息，包含 [context compressed]、
  分层 seq 区间和 recall 指引。

最近尾部
  由 AgentScope 的配对安全切分逻辑选出的最新轮次。
```

切分使用 AgentScope 的 token 统计和配对安全压缩 helper，因此会尽量保持实时窗口边界上的 tool_call / tool_result 对齐。

## 驱逐索引

驱逐索引是保留在上下文里的历史地图，采用分层结构：

- **Tier 0** 保存最近被驱逐的块，细节最多。
- 更老的 Tier 会把旧块折叠成端点区间。
- 每一行仍然带 `seq` 或 `seq lo-hi` 区间，因此即便折叠后也能从 `history.db` 展开原文。

示例形态：

```text
<system-info>
[context compressed] The turns below were evicted ...

Re-expand a span inside recall_history_python: ms.expand(lo, hi)

===== Tier 1 (older msgs) =====
  [seq 10-80]
    · seq 10-34  ⟦ chose SQLite history store - added recall tool ⟧
===== Tier 0 (recently compressed) =====
  [seq 81-96]
    · seq 84  ⟦ implemented context builder wiring ⟧
    · seq 93  ⟦ verified fallback to native strategy ⟧
</system-info>
```

模型不应该只凭 headline 回答。headline 只是指针；真正证据应来自 `ms.expand`、`ms.search` 或其他 recall helper 返回的完整内容。

## Recall API

scroll 启用时，QwenPaw 会注入一个支持沙箱运行的工具：`recall_history_python`。Python cell 中已经定义好 `ms`，它是一个 `MemorySpace` 对象。

常用 helper：

```python
# 展开索引中的区间。
print(ms.expand(81, 96))

# 搜索当前 Agent 跨会话的持久历史。
hits = ms.search("deployment decision", k=20)
for row in hits:
    print(row["seq"], row["session_id"], row["content"][:500])

# 读取某次工具调用及其结果。
print(ms.recall_tool("tool-call-id"))

# 发现并读取会话。
print(ms.sessions())
print(ms.session("cron:nightly-report"))

# 明确需要时查看工作区内 Agent。
print(ms.agents())
```

持久历史对 recall 是只读的：`history.db` 会以只读方式挂载为 SQLite schema `hist`。模型只能写自己的 scratch `main` 数据库。

安全说明：`recall_history_python` 会运行模型生成的 Python。正常情况下，它需要治理层注入 sandbox 配置；如果没有 sandbox，它会默认拒绝执行。只有同时满足以下条件时才允许非沙箱运行：

- 环境变量 `QWENPAW_ALLOW_UNSANDBOXED_RECALL` 为 truthy
- `running.light_context_config.scroll_config.allow_unsandboxed = true`

非沙箱 recall 等同于让模型以 Agent 用户身份执行任意宿主机 Python，仅适合可信本地开发。

## 工具结果

当前有两个相关机制：

| 机制                          | 默认状态                                     | 作用                                                                                                                                                     |
| ----------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ToolResultCapMiddleware`     | scroll 启用时生效                            | 单个工具结果超过 `scroll_config.tool_output_token_cap` 时，把完整输出写入 `history.db`，实时上下文只保留有限预览和 `ms.recall_tool(tool_call_id)` 指针。 |
| `ToolResultPruningMiddleware` | 由 `tool_result_pruning_config.enabled` 控制 | 旧版按字节分层裁剪工具结果，可选使用 `tool_results/` 文件缓存。                                                                                          |

scroll cap 是基于 token 的，并通过持久历史回溯；旧版 pruning 是基于字节的，用于兼容原有工具结果 offload 行为。

## 配置

相关配置位于 `running.light_context_config`：

```json
{
  "running": {
    "light_context_config": {
      "strategy": "scroll",
      "dialog_path": "dialog",
      "context_compact_config": {
        "enabled": true,
        "compact_threshold_ratio": 0.8,
        "reserve_threshold_ratio": 0.1
      },
      "scroll_config": {
        "db_filename": "history.db",
        "tool_output_token_cap": 3000,
        "pinned": 1,
        "repl_timeout_s": 300,
        "history_retention_days": 30,
        "allow_unsandboxed": false,
        "offload_dialog": false
      },
      "tool_result_pruning_config": {
        "enabled": true,
        "pruning_recent_n": 2,
        "pruning_old_msg_max_bytes": 3000,
        "pruning_recent_msg_max_bytes": 50000,
        "offload_retention_days": 5,
        "tool_results_cache": "tool_results"
      }
    }
  }
}
```

重要字段：

| 字段                                             | 默认值         | 含义                                                                      |
| ------------------------------------------------ | -------------- | ------------------------------------------------------------------------- |
| `strategy`                                       | `"scroll"`     | `"scroll"` 使用持久历史 + 驱逐索引；`"native"` 使用 AgentScope 原生压缩。 |
| `context_compact_config.compact_threshold_ratio` | `0.8`          | 模型输入达到上下文窗口该比例时触发。                                      |
| `context_compact_config.reserve_threshold_ratio` | `0.1`          | 驱逐后保留最近尾部的预算。                                                |
| `scroll_config.db_filename`                      | `"history.db"` | 相对工作区的 SQLite 文件名。                                              |
| `scroll_config.tool_output_token_cap`            | `3000`         | 单个工具结果在实时上下文中的预览 token 上限。                             |
| `scroll_config.pinned`                           | `1`            | 永不驱逐的开头消息数量。                                                  |
| `scroll_config.repl_timeout_s`                   | `300`          | `recall_history_python` 单次调用超时时间。                                |
| `scroll_config.history_retention_days`           | `30`           | 自动清理早于该天数的历史行；设为 `0` 表示永久保留。                       |
| `scroll_config.offload_dialog`                   | `false`        | 是否额外写旧版 `dialog/*.jsonl` 归档；`history.db` 仍是真相来源。         |

## 手动压缩

`/compact` 仍然存在，但在 scroll 策略下，它的含义是“强制 scroll manager 回收实时上下文，并展示当前驱逐索引”，而不是“生成一段压缩摘要”。

典型返回：

```text
Context compressed.

===== Tier 0 (recently compressed) =====
  [seq 81-96]
    · seq 84  ⟦ implemented context builder wiring ⟧
```

如果没有可驱逐消息，或者上下文本来就足够小，可能不会产生新的驱逐。

## Native 策略

如果希望使用 AgentScope 内置行为而不是 scroll，可以配置：

```json
{
  "running": {
    "light_context_config": {
      "strategy": "native"
    }
  }
}
```

native 模式不会接入 `ScrollContextManager`、`ToolResultCapMiddleware` 或 `recall_history_python`。它会使用 AgentScope 的上下文压缩，并继续映射 `compact_threshold_ratio` 和 `reserve_threshold_ratio`。
