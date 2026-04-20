# 长期记忆

**长期记忆** 让 QwenPaw 拥有跨对话的持久记忆能力：通过文件工具将关键信息写入 Markdown 文件长期保存，并配合语义检索随时召回。

> 长期记忆机制设计受 [OpenClaw](https://github.com/openclaw/openclaw) 启发，由 [ReMe](https://github.com/agentscope-ai/ReMe) 的 **ReMeLight** 实现——以文件系统为存储后端，记忆即 Markdown 文件，可直接读取、编辑与迁移。

---

## 架构概览

```mermaid
graph TB
    User[用户 / Agent] --> MM[MemoryManager]
    MM --> MemoryMgmt[长期记忆管理]
    MemoryMgmt --> FileTools[记忆更新]
    MemoryMgmt --> Watcher[记忆索引更新]
    MemoryMgmt --> SearchLayer[记忆混合检索]
    FileTools --> LTM[MEMORY.md]
    FileTools --> DailyLog[memory/YYYY-MM-DD.md]
    Watcher --> Index[异步更新数据库]
    SearchLayer --> VectorSearch[向量语义搜索]
    SearchLayer --> BM25[BM25 全文检索]
```

长期记忆管理包含以下能力：

| 能力           | 说明                                                                                    |
| -------------- | --------------------------------------------------------------------------------------- |
| **记忆持久化** | 通过文件工具（`read` / `write` / `edit`）将关键信息写入 Markdown 文件，文件即真实数据源 |
| **文件监控**   | 通过 `watchfile` 监控文件改动，异步更新本地数据库（语义索引 & 向量索引）                |
| **语义搜索**   | 通过向量嵌入 + BM25 混合检索，按语义召回相关记忆                                        |
| **文件读取**   | 直接通过文件工具读取对应的 Memory Markdown 文件，按需加载保持上下文精简                 |
| **梦境优化**   | 定时自动整理和优化 MEMORY.md，去冗存精，保持记忆库的高质量                              |

---

## 记忆文件结构

记忆采用纯 Markdown 文件存储，Agent 通过文件工具直接操作。默认工作空间使用两层结构：

```mermaid
graph LR
    Workspace[工作空间 working_dir] --> MEMORY[MEMORY.md 长期记忆]
    Workspace --> MemDir[memory/*]
    MemDir --> Day1[2025-02-12.md]
    MemDir --> Day2[2025-02-13.md]
    MemDir --> DayN[...]
```

### MEMORY.md（长期记忆，可选）

存放长期有效、极少变动的关键信息。

- **位置**：`{working_dir}/MEMORY.md`
- **用途**：存储决策、偏好、持久性事实、经验教训
- **更新**：Agent 通过 `write` / `edit` 文件工具写入

### memory/YYYY-MM-DD.md（每日日志）

每天一页，追加写入，记录当天的工作与交互。

- **位置**：`{working_dir}/memory/YYYY-MM-DD.md`
- **用途**：记录日常笔记和运行上下文
- **更新**：Agent 通过 `write` / `edit` 文件工具追加写入，对话过长需要进行总结时自动触发

### 何时写入记忆？

| 信息类型             | 写入目标               | 操作方式              | 示例                                       |
| -------------------- | ---------------------- | --------------------- | ------------------------------------------ |
| 决策、偏好、持久事实 | `MEMORY.md`            | `write` / `edit` 工具 | "项目使用 Python 3.12"、"偏好 pytest 框架" |
| 日常笔记、运行上下文 | `memory/YYYY-MM-DD.md` | `write` / `edit` 工具 | "今天修复了登录 Bug"、"部署了 v2.1"        |
| 用户说"记住这个"     | 立即写入文件           | `write` 工具          | 不要仅保存在内存中！                       |
| 可复用经验           | `MEMORY.md`            | `write` / `edit` 工具 | 梦境优化从日常记录中提炼的核心知识         |

---

## 🌙 梦境优化机制

**梦境优化**是 CoPaw 的自动记忆整理功能，会在预设时间（默认每晚23:00）运行。该功能自动从日常记录中提炼**核心业务决策、确认的用户偏好和高价值可复用经验**，通过四大原则优化 MEMORY.md：

- **极简去冗**：移除流水账和临时细节
- **状态覆写**：用新状态替换过时信息
- **归纳整合**：合并零散规则为通用原则
- **废弃剔除**：删除已证伪或过时内容

由 `dream_cron` 配置项控制（默认 `"0 23 * * *"`），设为空字符串可禁用。

---

## 记忆配置

### 配置结构

记忆配置位于 `agent.json` 的 `running.reme_light_memory_config` 中：

| 配置项                          | 说明                                                                        | 默认值         |
| ------------------------------- | --------------------------------------------------------------------------- | -------------- |
| `summarize_when_compact`        | 是否在上下文压缩时后台保存长期记忆（调用 `summary_memory` 写入文件）        | `true`         |
| `auto_memory_interval`          | 每隔 N 次用户查询触发自动记忆。null 表示禁用定期自动记忆                    | `null`         |
| `dream_cron`                    | 梦境记忆优化任务的 Cron 表达式（空字符串表示禁用）                          | `"0 23 * * *"` |
| `rebuild_memory_index_on_start` | 启动时是否清空并重建记忆搜索索引；设为 `false` 可跳过重建，仅监控新文件变更 | `false`        |
| `recursive_file_watcher`        | 是否递归监控记忆目录（包含子目录如 `memory/subdirectory/*`）                | `false`        |

### 自动记忆搜索配置

在 `running.reme_light_memory_config.auto_memory_search_config` 中配置：

| 配置项        | 说明                                        | 默认值  |
| ------------- | ------------------------------------------- | ------- |
| `enabled`     | 是否在每次对话时自动执行记忆搜索            | `false` |
| `max_results` | 自动搜索时最多返回的结果数                  | `1`     |
| `min_score`   | 自动搜索时的最低相关性分数阈值（0.0 ~ 1.0） | `0.1`   |
| `timeout`     | 自动搜索超时时间（秒）                      | `10.0`  |

### Embedding 配置（可选）

Embedding 配置用于向量语义搜索，位于 `running.reme_light_memory_config.embedding_model_config`：

| 配置项             | 说明                                  | 默认值   |
| ------------------ | ------------------------------------- | -------- |
| `backend`          | Embedding 后端类型                    | `openai` |
| `api_key`          | Embedding 服务的 API Key              | ``       |
| `base_url`         | Embedding 服务的 URL                  | ``       |
| `model_name`       | Embedding 模型名称                    | ``       |
| `dimensions`       | 向量维度，用于初始化向量数据库        | `1024`   |
| `enable_cache`     | 是否启用 Embedding 缓存               | `true`   |
| `use_dimensions`   | 是否在 API 请求中传递 dimensions 参数 | `false`  |
| `max_cache_size`   | Embedding 缓存最大条目数              | `3000`   |
| `max_input_length` | 单次 Embedding 最大输入长度           | `8192`   |
| `max_batch_size`   | Embedding 批处理最大数量              | `10`     |

> `use_dimensions` 用于某些 vLLM 模型不支持 dimensions 参数的情况，设为 `false` 可跳过该参数。

#### 通过环境变量配置（Fallback）

当配置文件中未设置时，以下环境变量作为 fallback：

| 环境变量               | 说明                     | 默认值 |
| ---------------------- | ------------------------ | ------ |
| `EMBEDDING_API_KEY`    | Embedding 服务的 API Key | ``     |
| `EMBEDDING_BASE_URL`   | Embedding 服务的 URL     | ``     |
| `EMBEDDING_MODEL_NAME` | Embedding 模型名称       | ``     |

> `base_url` 和 `model_name` 都非空才能开启混合检索中的向量检索（`api_key` 不参与判断）。

### 全文检索配置

通过环境变量 `FTS_ENABLED` 控制是否启用 BM25 全文检索：

| 环境变量      | 说明             | 默认值 |
| ------------- | ---------------- | ------ |
| `FTS_ENABLED` | 是否启用全文检索 | `true` |

> 即使不配置 Embedding，启用全文检索仍可通过 BM25 进行关键词搜索。

---

### 底层数据库

通过 `MEMORY_STORE_BACKEND` 环境变量配置记忆存储后端：

| 环境变量               | 说明                                                   | 默认值 |
| ---------------------- | ------------------------------------------------------ | ------ |
| `MEMORY_STORE_BACKEND` | 记忆存储后端，可选 `auto`、`local`、`chroma`、`sqlite` | `auto` |

**存储后端说明：**

| 后端     | 说明                                                                         |
| -------- | ---------------------------------------------------------------------------- |
| `auto`   | 自动选择：Windows 使用 `local`，其他系统使用 `chroma`                        |
| `local`  | 本地文件存储，无需额外依赖，兼容性最好                                       |
| `chroma` | Chroma 向量数据库，支持高效向量检索；在某些 Windows 环境下可能出现 core dump |
| `sqlite` | SQLite 数据库 + 向量扩展；在 macOS 14 及更低版本上存在卡死和闪退问题         |

> **推荐**：使用默认的 `auto` 模式，系统会根据平台自动选择最稳定的后端。

---

## 搜索记忆

Agent 有两种方式找回过去的记忆：

| 方式     | 工具            | 适用场景                           | 示例                        |
| -------- | --------------- | ---------------------------------- | --------------------------- |
| 语义搜索 | `memory_search` | 不确定记在哪个文件，按意图模糊召回 | "之前关于部署流程的讨论"    |
| 直接读取 | `read_file`     | 已知具体日期或文件路径，精确查阅   | 读取 `memory/2025-02-13.md` |

---

## 混合检索原理

记忆搜索默认采用**向量 + BM25 混合检索**，两种检索方式各有所长，互为补充。

### 向量语义搜索

将文本映射到高维向量空间，通过余弦相似度衡量语义距离，能捕捉意义相近但措辞不同的内容：

| 查询                   | 能召回的记忆                       | 为什么能命中                     |
| ---------------------- | ---------------------------------- | -------------------------------- |
| "项目的数据库选型"     | "最终决定用 PostgreSQL 替换 MySQL" | 语义相关：都在讨论数据库技术选择 |
| "怎么减少不必要的重建" | "配置了增量编译避免全量构建"       | 语义等价：减少重建 ≈ 增量编译    |
| "上次讨论的性能问题"   | "P99 延迟从 800ms 优化到 200ms"    | 语义关联：性能问题 ≈ 延迟优化    |

但向量搜索对**精确、高信号的 token** 表现较弱，因为嵌入模型倾向于捕捉整体语义而非单个 token 的精确匹配。

### BM25 全文检索

基于词频统计进行子串匹配，对精确 token 命中效果极佳，但在语义理解（同义词、改写）方面较弱。

| 查询                       | BM25 能命中            | BM25 会漏掉                    |
| -------------------------- | ---------------------- | ------------------------------ |
| `handleWebSocketReconnect` | 包含该函数名的记忆片段 | "WebSocket 断线重连的处理逻辑" |
| `ECONNREFUSED`             | 包含该错误码的日志记录 | "数据库连接被拒绝"             |

**打分逻辑**：将查询拆分为词，统计每个词在目标文本中的命中比例，并为完整短语匹配提供加分：

```
base_score = 命中词数 / 查询总词数           # 范围 [0, 1]
phrase_bonus = 0.2（仅当多词查询且完整短语匹配时）
score = min(1.0, base_score + phrase_bonus)  # 上限 1.0
```

示例：查询 `"数据库 连接 超时"` 命中一段只包含 "数据库" 和 "超时" 的文本 → `base_score = 2/3 ≈ 0.67`，无完整短语匹配 →
`score = 0.67`

> 为了处理 ChromaDB `$contains` 的大小写敏感问题，检索时会自动生成每个词的多种大小写变体（原文、小写、首字母大写、全大写），提高召回率。

### 混合检索融合

同时使用向量和 BM25 两路召回信号，对结果进行**加权融合**（默认向量权重 `0.7`，BM25 权重 `0.3`）：

1. **扩大候选池**：将最终需要的结果数乘以 `candidate_multiplier`（默认 3 倍，上限 200），两路分别检索更多候选
2. **独立打分**：向量和 BM25 各自返回带分数的结果列表
3. **加权合并**：按 chunk 的唯一标识（`path + start_line + end_line`）去重融合
   - 仅被向量召回 → `final_score = vector_score × 0.7`
   - 仅被 BM25 召回 → `final_score = bm25_score × 0.3`
   - **两路都召回** → `final_score = vector_score × 0.7 + bm25_score × 0.3`
4. **排序截断**：按 `final_score` 降序排列，返回 top-N 结果

**示例**：查询 `"handleWebSocketReconnect 断线重连"`

| 记忆片段                                               | 向量分数 | BM25 分数 | 融合分数                       | 排序 |
| ------------------------------------------------------ | -------- | --------- | ------------------------------ | ---- |
| "handleWebSocketReconnect 函数负责 WebSocket 断线重连" | 0.85     | 1.0       | 0.85×0.7 + 1.0×0.3 = **0.895** | 1    |
| "网络断开后自动重试连接的逻辑"                         | 0.78     | 0.0       | 0.78×0.7 = **0.546**           | 2    |
| "修复了 handleWebSocketReconnect 的空指针异常"         | 0.40     | 0.5       | 0.40×0.7 + 0.5×0.3 = **0.430** | 3    |

``mermaid
graph LR
Query[搜索查询] --> Vector[向量语义搜索 × 0.7]
Query --> BM25[BM25 全文检索 × 0.3]
Vector --> Merge[按 chunk 去重 + 加权求和]
BM25 --> Merge
Merge --> Sort[按融合分数降序排列]
Sort --> Results[返回 top-N 结果]

```

> **总结**：单独使用任何一种检索方式都存在盲区。混合检索让两种信号互补，无论是「自然语言提问」还是「精确查找」，都能获得可靠的召回结果。

---

## 相关页面

- [项目介绍](./intro.zh.md) — 这个项目可以做什么
- [控制台](./console.zh.md) — 在控制台管理记忆与配置
- [Skills](./skills.zh.md) — 内置与自定义能力
- [配置与工作目录](./config.zh.md) — 工作目录与 config
```
