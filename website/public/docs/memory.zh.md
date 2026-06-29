# 长期记忆

**长期记忆** 让 QwenPaw 拥有跨对话的持久记忆能力。默认后端会在 QwenPaw 进程内嵌入 ReMe 应用，并通过 ReMe jobs
完成对话事实保存、每日记忆、梦境摘要、资源文件监听和记忆检索。

> 长期记忆机制设计受 [OpenClaw](https://github.com/openclaw/openclaw)
> 启发，由 [ReMe](https://github.com/agentscope-ai/ReMe) 的 **ReMeLight** 实现——以文件系统为存储后端，记忆即 Markdown
> 文件，可直接读取、编辑与迁移。

---

## 架构概览

```mermaid
graph TB
    User[用户 / Agent] --> Middleware[MemoryMiddleware]
    Middleware --> Manager[ReMeLightMemoryManager]
    Manager --> ReMe[嵌入式 ReMe 应用]
    ReMe --> Jobs[ReMe Jobs]
    Jobs --> AutoMemory[auto_memory]
    Jobs --> AutoDream[auto_dream]
    Jobs --> Search[search]
    Jobs --> Resource[auto_resource]
    Jobs --> Reindex[reindex / index_update_loop]
    AutoMemory --> Daily[memory/YYYY-MM-DD/*.md]
    AutoMemory --> Session[mem_session/dialog/*.jsonl]
    AutoDream --> Digest[digest/*.md 和 interests.yaml]
    Resource --> ResourceDir[resource/*]
    Search --> Store[mem_metadata 文件存储 + BM25 + 可选向量]
```

长期记忆管理包含以下能力：

| 能力               | 说明                                                                                    |
| ------------------ | --------------------------------------------------------------------------------------- |
| **嵌入式 ReMe**    | QwenPaw 在进程内启动 ReMe，并将当前 Agent 使用的 QwenPaw 模型注入到 ReMe 默认 LLM 组件  |
| **Auto-Memory**    | 每隔可配置数量的用户回合，将对话中值得保留的事实抽取为每日 Markdown 记忆                |
| **上下文压缩保存** | 上下文压缩前，可把尚未写入的回合先提交给同一套 `auto_memory` 流程                       |
| **Auto-Dream**     | 定时从近期每日记忆中提取更高层的 digest 单元和主动交互兴趣主题                          |
| **混合检索**       | `memory_search` 调用 ReMe `search` job，通过 BM25 + 可选向量检索，并使用 RRF 融合排序   |
| **资源记忆**       | `resource/` 下的外部文件会被编目，变更后可通过 `auto_resource` 转成带来源链接的每日记忆 |
| **Inbox 通知**     | `auto_memory`、`auto_dream`、`auto_resource` 产生结果时，会推送到 QwenPaw inbox         |

---

## 记忆文件结构

记忆以普通文件保存在 Agent 工作区中。ReMe 写出的 Markdown 是可读的记忆源数据，`mem_metadata/` 则保存搜索索引、catalog、graph
和 embedding cache 等持久状态。

```
{工作区}/
├── memory/                         ← 每日记忆
│   └── 2026-06-29/
│       ├── project-plan.md          ← auto_memory 创建或更新的单条记忆
│       └── index.md                 ← 当日记忆索引
│
├── mem_session/
│   └── dialog/
│       └── <session_id>.jsonl       ← 作为记忆来源的对话记录
│
├── digest/                         ← Auto-Dream 产出的 digest 记忆和兴趣主题
├── resource/                       ← auto_resource 监听的外部资源
└── mem_metadata/                   ← ReMe 持久化索引和 catalog
```

### memory/YYYY-MM-DD/\*.md（每日记忆）

每日记忆是 Auto-Memory 的默认输出。ReMe 每天会写入一到多条记忆，并通过来源会话来定位已有记忆，后续同一会话的新内容会更新既有
note，而不是无限创建重复文件。

- **位置**：`{working_dir}/memory/YYYY-MM-DD/*.md`
- **用途**：保存长期有用的对话事实、决策、偏好和工作记录
- **更新**：ReMe `auto_memory` 通过 `daily_write`、`read`、`edit`、`frontmatter_update`、`write` 等 ReMe 文件 jobs 创建或编辑
- **索引**：每次成功写入后，ReMe 会刷新当天的 `index.md`

### mem_session/dialog/\*.jsonl（来源对话）

抽取记忆前，ReMe 会把相关消息保存为 session log。保存时会去掉 tool result 和 base64 数据块，避免未来的 Auto-Memory
把“检索出来的旧记忆”或大媒体内容误当成用户新提供的事实。

- **位置**：默认 `{working_dir}/mem_session/dialog/<session_id>.jsonl`
- **用途**：为每日记忆提供可追溯的来源
- **链接**：每日记忆 frontmatter 会通过 `[[mem_session/dialog/<session_id>.jsonl]]` 链接回来源会话

### digest/（梦境记忆）

Auto-Dream 会读取近期每日记忆，提取可合并的 digest 单元，更新 dream catalog，并写入主动交互使用的兴趣主题。

- **位置**：`{working_dir}/digest/`
- **用途**：跨会话的高层记忆和主动交互兴趣主题
- **更新**：ReMe `auto_dream`，通常由 `dream_cron` 定时触发

### resource/（资源记忆）

`resource/` 下的文件会被监听和编目。支持的文件发生变化时，ReMe 可以通过 `auto_resource` 将其解释为带来源链接的每日记忆。

- **位置**：`{working_dir}/resource/`
- **默认支持后缀**：`md`、`txt`、`json`、`jsonl`、`csv`、`yaml`、`html`
- **Inbox 行为**：只有实际修改记忆时，资源处理结果才会推送到 inbox

> 关于 Auto-Memory、Auto-Dream、Auto-Memory-Search 和 Proactive
> 的完整工作流介绍，请参阅 [智能体记忆进化与主动交互](./memory-evolving-and-proactive)。以下仅补充技术实现细节与配置说明。

---

## 搜索记忆

Agent 有两种方式找回过去的记忆：

| 方式     | 工具            | 适用场景                           | 示例                                     |
| -------- | --------------- | ---------------------------------- | ---------------------------------------- |
| 混合检索 | `memory_search` | 不确定记在哪个文件，按意图模糊召回 | "之前关于部署流程的讨论"                 |
| 直接读取 | 文件工具        | 已知具体日期或文件路径，精确查阅   | 读取 `memory/2026-06-29/project-plan.md` |

### 混合检索原理

`memory_search` 会调用 ReMe 的 `search` job。搜索始终尝试 BM25 关键词检索；当配置了 embedding 模型时，也会同时运行向量检索。
两路都有结果时，ReMe 使用 **Reciprocal Rank Fusion（RRF）** 融合排序。

#### 向量语义搜索

将文本映射到高维向量空间，通过余弦相似度衡量语义距离，能捕捉意义相近但措辞不同的内容：

| 查询                   | 能召回的记忆                       | 为什么能命中                     |
| ---------------------- | ---------------------------------- | -------------------------------- |
| "项目的数据库选型"     | "最终决定用 PostgreSQL 替换 MySQL" | 语义相关：都在讨论数据库技术选择 |
| "怎么减少不必要的重建" | "配置了增量编译避免全量构建"       | 语义等价：减少重建 ≈ 增量编译    |
| "上次讨论的性能问题"   | "P99 延迟从 800ms 优化到 200ms"    | 语义关联：性能问题 ≈ 延迟优化    |

但向量搜索对**精确、高信号的 token** 表现较弱，因为嵌入模型倾向于捕捉整体语义而非单个 token 的精确匹配。

#### BM25 关键词检索

基于词频统计进行子串匹配，对精确 token 命中效果极佳，但在语义理解（同义词、改写）方面较弱。

| 查询                       | BM25 能命中            | BM25 会漏掉                    |
| -------------------------- | ---------------------- | ------------------------------ |
| `handleWebSocketReconnect` | 包含该函数名的记忆片段 | "WebSocket 断线重连的处理逻辑" |
| `ECONNREFUSED`             | 包含该错误码的日志记录 | "数据库连接被拒绝"             |

ReMe 会为被索引文件维护本地 BM25 索引。它适合命中精确标识符、错误码、文件名和低频词；即使没有配置 embedding，也能提供关键词召回。

#### 混合检索融合

当向量检索和 BM25 都返回候选时，ReMe 使用加权 RRF 融合。默认向量权重为 `0.7`，剩余 `0.3` 给关键词检索。

1. **扩大候选池**：将最终需要的结果数乘以 `candidate_multiplier`（默认 3 倍，上限 200），两路分别检索更多候选
2. **独立排序**：向量和 BM25 各自返回排序后的候选列表
3. **RRF 合并**：按 chunk id 去重，并叠加基于排名的贡献：
   - 向量贡献：`0.7 / (60 + vector_rank)`
   - 关键词贡献：`0.3 / (60 + keyword_rank)`
   - 两路都命中的 chunk 会获得两份贡献
4. **排序截断**：按 `final_score` 降序排列，返回 top-N 结果
5. **链接展开**：搜索结果可附带相关链接文件上下文，帮助理解命中片段

**示例**：查询 `"handleWebSocketReconnect 断线重连"`

| 记忆片段                                               | 向量排序 | BM25 排序 | 排名靠前原因                           |
| ------------------------------------------------------ | -------- | --------- | -------------------------------------- |
| "handleWebSocketReconnect 函数负责 WebSocket 断线重连" | 2        | 1         | 语义匹配强，同时精确命中关键词         |
| "网络断开后自动重试连接的逻辑"                         | 1        | -         | 语义匹配强，即使没有精确函数名也能召回 |
| "修复了 handleWebSocketReconnect 的空指针异常"         | -        | 2         | 精确标识符命中，使其保留在候选集中     |

```mermaid
graph LR
    Query[搜索查询] --> Vector[向量语义搜索 x0.7]
    Query --> BM25[BM25 关键词检索 x0.3]
    Vector --> Merge[按 chunk 去重 + 加权 RRF]
    BM25 --> Merge
    Merge --> Sort[按融合分数降序排列]
    Sort --> Results[返回 top-N 结果]
```

> **总结**：单独使用任何一种检索方式都存在盲区。混合检索让两种信号互补，无论是「自然语言提问」还是「精确查找」，都能获得可靠的召回结果。

---

## 记忆配置

### 配置结构

记忆配置位于 `agent.json` 的 `running.reme_light_memory_config` 中：

| 配置项                          | 说明                                                                     | 默认值           |
| ------------------------------- | ------------------------------------------------------------------------ | ---------------- |
| `metadata_dir`                  | ReMe 持久状态目录，用于保存索引、catalog、graph 和缓存                   | `"mem_metadata"` |
| `session_dir`                   | 来源对话保存目录                                                         | `"mem_session"`  |
| `resource_dir`                  | `auto_resource` 监听的资源目录                                           | `"resource"`     |
| `daily_dir`                     | 每日记忆目录                                                             | `"memory"`       |
| `digest_dir`                    | dream/digest 记忆目录                                                    | `"digest"`       |
| `enable_search_raw_log`         | 是否让搜索索引包含原始 session/resource JSONL 类数据                     | `false`          |
| `summarize_when_compact`        | 是否在上下文压缩前将待保存回合提交给 Auto-Memory                         | `true`           |
| `auto_memory_interval`          | 每隔 N 个用户回合触发 Auto-Memory。`None` 或 `<= 0` 表示禁用周期自动记忆 | `5`              |
| `dream_cron`                    | Auto-Dream 任务的 Cron 表达式（空字符串表示禁用）                        | `"0 23 * * *"`   |
| `rebuild_memory_index_on_start` | Agent 启动时是否清空并重建 ReMe 搜索索引                                 | `false`          |

### 自动记忆搜索配置

在 `running.reme_light_memory_config.auto_memory_search_config` 中配置：

| 配置项               | 说明                                                     | 默认值  |
| -------------------- | -------------------------------------------------------- | ------- |
| `enabled`            | 是否在每次对话时自动执行记忆搜索                         | `false` |
| `max_results`        | 自动搜索时最多返回的结果数                               | `2`     |
| `persist_to_context` | 是否将自动搜索注入的 tool call/result 保留在对话上下文中 | `false` |

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
| `max_cache_size`   | Embedding 缓存最大条目数              | `10000`  |
| `max_input_length` | 单次 Embedding 最大输入长度           | `8192`   |
| `max_batch_size`   | Embedding 批处理最大数量              | `10`     |

> `use_dimensions` 用于某些 vLLM 模型不支持 dimensions 参数的情况，设为 `false` 可跳过该参数。

> `base_url` 和 `model_name` 都非空才能开启混合检索中的向量检索（`api_key` 不参与判断）。

### 索引行为

嵌入式 ReMe 配置使用本地 file store：

| 组件       | 行为                                                                                       |
| ---------- | ------------------------------------------------------------------------------------------ |
| File store | ReMe 本地文件存储，持久状态位于 `mem_metadata/`                                            |
| 关键词索引 | 默认启用 BM25 关键词索引                                                                   |
| 向量索引   | 仅当 `embedding_model_config.base_url` 和 `model_name` 均非空时启用                        |
| 监听目录   | 默认监听 `daily_dir` 和 `digest_dir`；`enable_search_raw_log=true` 时也索引 `resource_dir` |
| 监听后缀   | 默认索引 `md`；启用 raw-log search 后包含 `jsonl`                                          |

---

## 其他 Memory Backend

QwenPaw 的记忆系统采用可插拔的 Backend 架构。除了默认的 ReMeLight（本地文件存储）外，还支持通过 `memory_manager_backend` 切换到其他后端。

### ADBPG（AnalyticDB for PostgreSQL）

基于云端向量数据库的长期记忆后端，适合需要跨设备共享、大规模语义检索的场景。

**核心特点：**

- **跨会话持久化** — 记忆存储在云端数据库，重启后不丢失，支持多设备共享
- **服务端事实抽取** — 由 ADBPG 内置 LLM 完成事实提取，客户端无额外开销
- **双 API 模式** — 支持 SQL 直连和 REST API 两种接入方式
- **优雅降级** — ADBPG 不可达时 Agent 正常运行，仅长期记忆功能暂时禁用

**配置方式：**

进入 Agent 配置页面的「运行配置」标签，找到「记忆管理后端」下拉框，选择 `adbpg`，并在下方的 `adbpg_memory_config` 中根据所选 API 模式填写对应参数。

![adbpg-backend](https://img.alicdn.com/imgextra/i3/O1CN01bH1Rj41wwQs3v04U6_!!6000000006372-2-tps-2954-1484.png)

> ⚠️ 切换后端不支持热更新，保存后需要重启 QwenPaw 才能生效（页面也会以黄色横幅提醒）。

#### REST 模式（推荐）

通过 HTTP API 接入 ADBPG 记忆服务，无需额外 Python 依赖。

切换到「ADBPG 长期记忆」Tab，将「API 模式」设为 `REST API`，并填写 `REST Base URL` 与 `REST API Key`：

![adbpg-rest-mode](https://img.alicdn.com/imgextra/i4/O1CN01gTvYJI238hAc4fcvr_!!6000000007211-2-tps-2996-1478.png)

| 配置项             | 说明                                                   | 默认值   |
| ------------------ | ------------------------------------------------------ | -------- |
| `api_mode`         | API 模式，设为 `"rest"`                                | `"rest"` |
| `rest_base_url`    | ADBPG 记忆服务的 REST API 地址                         | `""`     |
| `rest_api_key`     | REST API 的访问密钥                                    | `""`     |
| `memory_isolation` | 记忆隔离模式，`true` 为每个 Agent 独立，`false` 为共享 | `true`   |
| `search_timeout`   | 记忆搜索超时时间（秒）                                 | `10.0`   |

#### SQL 模式

通过 psycopg2 直连 ADBPG 数据库，需额外安装依赖：`pip install qwenpaw[adbpg]`。

切换到「ADBPG 长期记忆」Tab，将「API 模式」设为 `SQL (Direct)`，并填写数据库连接信息（主机地址 / 端口 / 用户名 / 密码 / 数据库名）以及 LLM、Embedding 相关参数：

![adbpg-sql-mode](https://img.alicdn.com/imgextra/i2/O1CN01K8Og0P27WkQvGWHvZ_!!6000000007805-2-tps-2988-1498.png)

| 配置项               | 说明                            | 默认值  |
| -------------------- | ------------------------------- | ------- |
| `api_mode`           | API 模式，设为 `"sql"`          | `"sql"` |
| `host`               | ADBPG 数据库地址                | `""`    |
| `port`               | 数据库端口                      | `5432`  |
| `user`               | 数据库用户名                    | `""`    |
| `password`           | 数据库密码                      | `""`    |
| `dbname`             | 数据库名称                      | `""`    |
| `llm_model`          | 服务端事实抽取使用的 LLM 模型名 | `""`    |
| `llm_api_key`        | LLM 服务的 API Key              | `""`    |
| `llm_base_url`       | LLM 服务的 Base URL             | `""`    |
| `embedding_model`    | Embedding 模型名称              | `""`    |
| `embedding_api_key`  | Embedding 服务的 API Key        | `""`    |
| `embedding_base_url` | Embedding 服务的 Base URL       | `""`    |
| `embedding_dims`     | 向量维度                        | `1024`  |
| `memory_isolation`   | 记忆隔离模式                    | `true`  |
| `search_timeout`     | 记忆搜索超时时间（秒）          | `10.0`  |
| `pool_minconn`       | 连接池最小连接数                | `1`     |
| `pool_maxconn`       | 连接池最大连接数                | `5`     |

**配置示例：**

完整配置可写入 `agent.json` 的 `running.adbpg_memory_config` 字段：

```json
{
  "running": {
    "memory_manager_backend": "adbpg",
    "adbpg_memory_config": {
      "host": "gp-xxxxxxxxx-master.gpdb.rds.aliyuncs.com",
      "port": 5432,
      "user": "your_db_user",
      "password": "your_db_password",
      "dbname": "your_db_name",
      "llm_model": "qwen-plus",
      "llm_api_key": "sk-xxxxxxxx",
      "llm_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "embedding_model": "text-embedding-v3",
      "embedding_api_key": "sk-xxxxxxxx",
      "embedding_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "embedding_dims": 1024,
      "api_mode": "sql",
      "rest_api_key": "",
      "rest_base_url": "",
      "memory_isolation": true,
      "search_timeout": 10.0,
      "pool_minconn": 1,
      "pool_maxconn": 5
    }
  }
}
```

> 💡 通过 Console 「运行配置」页面填写时，框架会自动将这些字段写入 `agent.json`，无需手动编辑文件。

---

## 相关页面

- [智能体记忆进化](./memory-evolving-and-proactive) — Auto-Memory、Auto-Dream、Auto-Memory-Search、Proactive 完整工作流
- [项目介绍](./intro) — 这个项目可以做什么
- [控制台](./console) — 在控制台管理记忆与配置
- [Skills](./skills) — 内置与自定义能力
- [配置与工作目录](./config) — 工作目录与 config
