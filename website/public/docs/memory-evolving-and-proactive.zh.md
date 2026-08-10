# 智能体记忆进化与主动交互（Beta）

> **Beta 功能**：QwenPaw 的 ReMeLight memory manager 会把 [ReMe](https://github.com/agentscope-ai/ReMe) 作为进程内应用嵌入。Auto Memory、Daily Paper、Auto Dream、搜索，以及 ReMe 底层的 proactive topic 读取能力都是 ReMe job。QwenPaw 的 `/proactive` 命令是另一条运行时逻辑，它读取近期 chat session 和可选屏幕上下文。

QwenPaw 将记忆保存为 agent workspace 下的文件。对话先保存为 JSONL 来源日志，有价值的对话事实写入 daily Markdown note，资源可以转换成 daily note，Auto Dream 再定期把可复用抽象整合进 digest 记忆。

---

## 核心理念：自进化的个人知识库

ReMe 的目标不是给聊天模型挂一个黑盒向量库，而是基于 **Memory as File, File as Memory** 原则，长出一个**自进化的个人知识库**：每个工作记忆或长期记忆节点都是一份可以直接打开、阅读、编辑、移动、删除的 Markdown 文件，同时又是一个可索引、可链接的节点；原始来源与派生系统状态则使用适合各自职责的格式。

因为记忆以文件而非不透明的数据库记录形式存在，长期记忆获得了黑盒存储无法提供的特性：

| 特性   | 实际意义                                                           |
| ------ | ------------------------------------------------------------------ |
| 可读   | 打开 workspace，像普通 Markdown 一样阅读 daily note 和 digest 节点 |
| 可编辑 | 用普通文件编辑就能纠正、扩展、移动、删除记忆，无需专用客户端       |
| 可追溯 | 每条长期结论都通过 `derived_from:: [[...]]` 链接回它的来源         |
| 可迁移 | workspace 就是一个普通目录，可以备份、同步，或用 git 做版本管理    |
| 可协作 | 你负责判断与纠正，agent 负责整理、链接、检索——都在同一批文件上     |

### 记忆分层

workspace 把记忆从"原始证据"到"可复用知识"组织为四层：

```text
原始输入   → mem_session/ + resource/   原始对话与外部资料
工作记忆   → memory/                     daily note：事实、决策、资源解读
长期记忆   → digest/                     可复用知识：personal / procedure / wiki
系统状态   → mem_metadata/               索引、wikilink 图、catalog（不手工编辑）
```

QwenPaw 的目录名与 ReMe 上游默认值不同，但每层的职责一致：`mem_session/` 对应 ReMe `session/`，`memory/` 对应 `daily/`，`mem_metadata/` 对应 `metadata/`；`resource/` 和 `digest/` 保持同名。

### 知识库如何进化

知识库通过持续的 **capture → index → consolidate → recall** 闭环生长：

1. **Capture（捕获）** — Auto Memory 把对话蒸馏成 daily note，Daily Paper 把论文精读和简报写成 daily note，同时保留原始对话与论文 PDF 作为证据。
2. **Index（索引）** — 后台 job 通过 BM25 关键词索引、可选向量、以及 wikilink 图，让 `memory/` 和 `digest/` 始终可检索。
3. **Consolidate（整合）** — Auto Dream 读取近期 daily note，整合进长期 `digest/` 节点。这一步才是记忆真正**进化**的地方：它不是复制文本，而是把每个抽取出的 unit 合并进已有节点或创建新节点，并织入来源与关系 wikilink。
4. **Recall（召回）** — `memory_search` 召回最相关的片段并沿 wikilink 图展开；interest topics 和 QwenPaw 的 `/proactive` 主动浮现值得关注的内容。

digest 层刻意**不是只追加**的。当新素材与已有节点重复、细化或冲突时，Auto Dream 会对其 corroborate、refine 或 correct（见下文整合动作）。再配合让节点保持连通、可追溯的 wikilink 图，知识库会随时间变得更密、更准，而不只是变得更大。

---

## 实际流程

```mermaid
graph LR
    A[Conversation turns] --> B[MemoryMiddleware]
    B --> C[ReMe auto_memory job]
    C --> D[mem_session/dialog/*.jsonl]
    C --> E[memory/<date>/<note>.md]
    R[Hugging Face paper rankings] --> S[ReMe daily_paper job]
    S --> T[resource/papers/*.pdf]
    S --> E
    E --> U[ReMe auto_dream job]
    U --> V["digest/personal | procedure | wiki/*.md"]
    U --> W[memory/<date>/interests.yaml]
```

| 能力                 | 代码路径                                                     | 触发方式                                                                | 主要产物                                                                               |
| -------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | -------------- | ------------------------------------------------ |
| Auto Memory          | `ReMeLightMemoryManager.auto_memory()` -> ReMe `auto_memory` | `MemoryMiddleware` 按配置的用户轮次数触发；启用时也会在上下文压缩前触发 | `mem_session/dialog/<session_id>.jsonl`、`memory/<date>/<note>.md`、`memory/<date>.md` |
| Daily Paper          | `ReMeLightMemoryManager.daily_paper()` -> ReMe `daily_paper` | `daily_paper_cron_enabled` 启用后由 `daily_paper_cron` 调度             | `resource/papers/*.pdf`、论文精读和每日简报                                            |
| Auto Dream           | `ReMeLightMemoryManager.dream()` -> ReMe `auto_dream`        | `/dream` 命令或 `dream_cron` 调度                                       | `digest/*/*.md`、`memory/<date>/interests.yaml`                                        |
| ReMe proactive job   | ReMe `proactive`                                             | 仅在直接调用 ReMe job 时运行                                            | `memory/<date>/interests.yaml` 的 metadata/content                                     |
| QwenPaw `/proactive` | `src/qwenpaw/agents/memory/proactive`                        | `/proactive [minutes                                                    | on                                                                                     | off]` 空闲循环 | 通过 `/api/console/chat` 发送的主动 chat request |

关键边界：`memory/<date>/interests.yaml` 由 Auto Dream 生成，也可以被 ReMe 的 `proactive` job 读取；但 QwenPaw 当前 `/proactive` 实现不会调用这个 job，也不会直接消费 `interests.yaml`。

---

## 文件布局

嵌入式 ReMe 配置来自 `src/qwenpaw/agents/memory/reme_config.py`，面向用户的默认值来自 `ReMeLightMemoryConfig`。

```text
<workspace>/
├── mem_metadata/   # ReMe 持久状态、索引、catalog
├── mem_session/    # Auto Memory 使用的来源对话日志
│   └── dialog/
│       └── <session_id>.jsonl
├── mem_agent/      # ReMe 内部 memory-agent session
├── resource/       # 主动知识能力保存的原始资源
│   └── papers/
│       └── <arxiv_id>.pdf
├── memory/         # Daily memory notes 和 day index
│   ├── YYYY-MM-DD.md
│   └── YYYY-MM-DD/
│       ├── <note>.md
│       └── interests.yaml
└── digest/         # 长期 digest 记忆
    ├── personal/
    ├── procedure/
    └── wiki/
```

默认目录名可通过 `metadata_dir`、`session_dir`、`mem_session_dir`、`resource_dir`、`daily_dir`、`digest_dir` 配置。

---

## Auto Memory

Auto Memory 由 `MemoryMiddleware` 调用，不是每次 model call 都直接运行。Middleware 会：

- 跳过来源为 `cron` 或 `heartbeat` 的自动化请求；
- 当 `auto_memory_search_config.enabled` 为 true 时，在模型调用前注入自动记忆搜索上下文；
- 在回复后收集 user-turn marker；
- 累计到 `auto_memory_interval` 个用户轮次后 flush；
- 即将压缩上下文时，也会先 flush pending turns。

`auto_memory_interval` 默认是 `5`。`None`、`0` 或负数会禁用周期性 Auto Memory。

Flush 时，QwenPaw 调用 ReMe 的 `auto_memory` job，并传入：

| 字段          | 来源                              |
| ------------- | --------------------------------- |
| `messages`    | pending user turns 对应的会话消息 |
| `session_id`  | Agent session id                  |
| `memory_hint` | 调用方可选提示                    |

ReMe 的 `AutoMemoryStep` 随后会：

1. 校验 `session_id` 存在且合法；
2. 将清洗后的来源消息保存或追加到 `mem_session/dialog/<session_id>.jsonl`；
3. 从保存的来源日志中移除 tool-result block 和 base64 data block；
4. 从显式 date、消息时间戳或配置时区的当前日期中选择 note date；
5. 查找 frontmatter 中 `session_id` 或 `source_conversation` 匹配的已有 daily note；
6. 新 session 最多创建一条 note，已有 session 更新同一条 note；
7. 确保 frontmatter 包含 `session_id` 和 `source_conversation`；
8. 可能根据 frontmatter `name` 重命名 note；
9. 刷新 `memory/<date>.md` day index；
10. 返回 `date`、`path`、`created`、`modified`、`n_messages`、`source_conversation`、`index` 等 metadata。

如果 job 成功但没有实际修改 note，QwenPaw 不会为 `auto_memory` 推送 inbox event。否则会推送标题为 `Auto-memory result` 的 inbox event。

---

## Daily Paper

QwenPaw 通过 `ReMeLightMemoryManager.daily_paper()` 调用 ReMe `daily_paper` job。它从 Hugging Face 周榜和月榜
收集候选论文，排除近期已经推荐的 arXiv ID，选择三篇论文，下载 PDF 并生成三篇精读和一份每日简报。

PDF 保存在 `resource_dir/papers/`，Markdown 保存在 `daily_dir/<date>/` 并进入现有记忆索引。执行结果通过
QwenPaw inbox 推送，不包含 DingTalk step。

`daily_paper_cron_enabled` 默认是 `false`；启用后按 `daily_paper_cron` 调度，默认表达式为 `0 9 * * *`。

---

## Auto Dream

QwenPaw 通过以下入口暴露 Auto Dream：

- `/dream [hint]`，由 `CommandHandler._process_dream()` 处理；
- `dream_cron_enabled` 为 true 时按 `dream_cron` 配置调度，默认 `0 23 * * *`；定时触发后会随机延迟 0–60 秒启动，以避免集中调用；
- `ReMeLightMemoryManager.dream(date="", hint="")`。

QwenPaw 运行名为 `auto_dream` 的 ReMe job，并设置 `needs_llm=True`，因此嵌入式 ReMe 会在 job 运行前用 QwenPaw 当前 active model 刷新自己的 LLM component。

嵌入式 job 配置使用这些默认值：

| 参数                   | 默认值 | 含义                              |
| ---------------------- | -----: | --------------------------------- |
| `date`                 |   `""` | 空值表示配置时区里的今天          |
| `hint`                 |   `""` | 可选用户/操作者提示               |
| `scan_days`            |    `2` | 扫描目标日期及最近日期            |
| `max_units`            |    `5` | 最多抽取的可复用 memory units     |
| `topic_count`          |    `3` | 最多最终 interest topics          |
| `topic_diversity_days` |    `7` | 避免重复最近几天已经出现的 topics |

Auto Dream 运行四个 ReMe steps：

| Step                   | 实际行为                                                                                                                                              |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dream_extract_step`   | 刷新 day indexes，对比 daily files 和 dream catalog，删除缺失的 catalog entries，只从变化的 daily 输入中抽取可复用 memory units 和 topic candidates。 |
| `dream_integrate_step` | 将每个抽取出的 unit 整合进一个 digest node。会使用 `node_search`、`read`、`frontmatter_read`、`write`、`edit`、`frontmatter_update`。                 |
| `dream_topics_step`    | 选择并去重 interest topics，写入 `memory/<date>/interests.yaml`，并刷新 day index。                                                                   |
| `dream_finish_step`    | 将成功处理的 changed paths、interest files 和 day indexes upsert 到 dream catalog，持久化 catalog，并返回 summary。                                   |

如果没有变化的 daily 输入，extract 会以 no-change 响应结束。如果 LLM 不可用，extract 或 integrate 会失败，因为这些 step 需要 LLM。

Digest node 按 bucket 存储：

| Bucket       | 存什么                                                     |
| ------------ | ---------------------------------------------------------- |
| `personal/`  | 用户、团队或项目身份、偏好、约定、约束、avoid-rules        |
| `procedure/` | How-to 工作流、runbook、recipe、方法、可执行模式           |
| `wiki/`      | 定义、原则、观察、作为先例的决策、事实 claim，以及兜底知识 |

Integration action 包括 `CREATE`、`CORROBORATE`、`REFINE`、`CORRECT`。正是这四个动作让知识库"自进化"：与已有节点匹配的 unit 不会被当作重复内容追加，而是合并进该节点——用新来源 corroborate、用新边界 refine、或在冲突时 correct。

| Action        | 含义                                           |
| ------------- | ---------------------------------------------- |
| `CREATE`      | 尚不存在等价抽象，创建新的 digest 节点         |
| `CORROBORATE` | 同一记忆再次出现，追加来源并强化描述           |
| `REFINE`      | 新素材补充边界、步骤、前置条件、适用范围或细节 |
| `CORRECT`     | 新素材纠正已有节点中的错误、遗漏或冲突         |

**通过 wikilink 构建知识图谱。** ReMe 的 wikilink 整合逻辑运行在 `dream_integrate_step` 中。写入前它先用 `node_search` 召回相似或相关的 digest 节点，在上述动作间做出决策，然后向节点正文织入两类 workspace-relative wikilink：

- **来源边** — `derived_from:: [[memory/<date>/<note>.md]]`，让每个 digest 结论都能追溯回它来自的 daily note 或资源。
- **关系边** — `relates_to:: [[digest/wiki/...]]`、`depends_on:: [[digest/procedure/...]]` 等 typed link，把节点连接到相邻概念、前置条件和流程。

更新是增量式的：已有 wikilink 和 `derived_from` 会被保留，图因此持续生长而不丢边。`memory_search` 之后会沿这些链接展开——这正是召回不仅能给出匹配片段、还能带出它连接的长期节点与来源的原因。

Auto Dream 完成后，QwenPaw 会推送标题为 `Auto-dream result` 的 inbox event。

---

## Interest Topics 和 ReMe Proactive Job

`dream_topics_step` 写入：

```text
memory/<date>/interests.yaml
```

YAML payload 包含：

| 字段             | 含义                                                                   |
| ---------------- | ---------------------------------------------------------------------- |
| `date`           | 目标日期                                                               |
| `topic_count`    | 请求的最大 topic 数                                                    |
| `diversity_days` | 最近日期去重窗口                                                       |
| `topics`         | 选出的 topics，包含 `title`、`reason`、`evidence`、`keywords`、`paths` |

ReMe 还定义了一个由 `proactive_step` 实现的 `proactive` job。这个 job 只读取 `memory/<date>/interests.yaml`。它接受：

| 参数              | 默认值 | 含义                             |
| ----------------- | -----: | -------------------------------- |
| `date`            |   `""` | 空值表示今天                     |
| `include_content` | `true` | 在 metadata 中包含原始 YAML 文本 |

如果 interests 文件不存在，ReMe proactive job 会返回正常的 skipped result。

---

## QwenPaw `/proactive`

QwenPaw 当前 `/proactive` 命令实现位于 `src/qwenpaw/agents/memory/proactive`，它和 ReMe 的 `proactive` job 是两套逻辑。

命令行为：

```text
/proactive           # 使用默认 30 分钟空闲阈值启用
/proactive on        # 使用默认 30 分钟空闲阈值启用
/proactive 45        # 使用 45 分钟空闲阈值启用
/proactive off       # 取消后台 monitoring task
```

启用后，QwenPaw 会为 session 保存一个内存态 `ProactiveConfig`，并启动后台循环。该循环会：

- 每 30 秒 wake 一次；
- agent 有 active tasks 时跳过；
- 读取最新 chat update time；
- 等待 session 空闲达到配置分钟数；
- 60 秒内不重复尝试；
- 如果最后一条消息已经是未回应的 `[PROACTIVE]` 消息，则跳过；
- 运行 proactive responder。

Responder 构造上下文时读取近期 chat sessions，而不是读取 `interests.yaml`：

- 通过 `workspace.chat_manager` 读取 chat metadata；
- 保留最近 7 天更新过的 sessions；如果不足 5 个，则取最新 5 个 sessions；
- 加载最多 100 条近期文本消息，总字符上限 50,000；
- 过滤 system messages、非文本 blocks，以及之前 proactive helper 发出的请求；
- 当 active model 支持多模态时，可选分析桌面截图。

随后它让临时 `ProactiveAssistant` agent 从上下文中抽取 1 到 3 个可能任务，最多执行前 3 个任务 query，并通过以下接口发送面向用户的 proactive request：

```text
POST <agent-api-base>/api/console/chat
session_id = proactive_mode:<active_agent_id>
text starts with "[Agent proactive_helper requesting]"
```

最终面向用户的 prompt 要求 agent 回复以 `[PROACTIVE]` 开头。

命令中的 warning 与代码一致：proactive mode 可能读取历史 session memory，并且在多模态屏幕分析可用时可能截图。Proactive agent 通过自己的临时 agent/tool setup 使用 tool protection bypass mode。

---

## 搜索与索引

嵌入式 ReMe app 会启动 `index_update_loop` 后台 job。搜索索引监听：

| 索引目录                  | 后缀 |
| ------------------------- | ---- |
| `daily_dir`、`digest_dir` | `md` |

QwenPaw 的 `memory_search` tool 会运行 ReMe 的 `search` job，参数是 `query`、`limit`、`min_score`。该 job 配置为 hybrid workspace search，包含向量召回、BM25 keyword 召回、RRF 融合和 wikilink expansion。QwenPaw 嵌入式 ReMe 配置里的存储后端是 local。

---

## 当前状态

本文档描述当前代码路径：

- ReMeLight 由 `ReMeLightMemoryManager` 和嵌入式 `get_reme_app_config()` 实现；
- Auto Memory 基于用户轮次数触发，默认每 5 个用户轮次一次；
- Auto Dream 通过 `/dream` 或 `dream_cron` 运行；
- ReMe 会写入 `interests.yaml`，也有读取它的底层 job；
- QwenPaw `/proactive` 当前使用近期 chat/session/screen context，而不是 ReMe interest topics；
- Auto Memory、Daily Paper、Auto Dream 产生可报告输出时，可能投递到 inbox。

该能力仍处于 Beta 阶段，但以上行为与当前代码实现一致。
