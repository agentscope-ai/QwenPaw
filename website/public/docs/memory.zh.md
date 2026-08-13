# 长期记忆

QwenPaw 的长期记忆由 [ReMe](https://github.com/agentscope-ai/ReMe) 驱动。它不会在每次对话时重新读完全部历史，而是把值得保留的对话和当前已接入的资料整理成 Markdown 文件；需要时，再只找回与当前问题有关的部分。

简单来说，它做四件事：

1. **记录**：从对话中留下偏好、事实、决定、原因和下一步；
2. **整理**：把不同日期的零散记录沉淀为长期知识；
3. **连接**：用来源链接和 Wikilink 串起结论、证据与相关知识；
4. **找回**：通过关键词、语义和知识关系找到真正相关的内容。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01mG5Uot1GQdX33v4h4_!!6000000000617-55-tps-1200-640.svg" alt="QwenPaw 长期记忆从记录、整理到找回的完整循环" />
</p>

## 先理解它怎样工作

假设你正在准备一次产品发布。最近几周，你和 QwenPaw 讨论过：发布说明要先讲用户价值、本次暂不迁移数据库、发布后需要重新评估迁移计划。

这些信息如果只留在聊天记录里，很快就会被新的对话淹没。长期记忆会把它们依次变成每日记忆、长期知识和可检索的依据。

### 1. 记忆首先是你拥有的文件

ReMe 遵循 **Memory as File, File as Memory**。核心记忆不是藏在不可见的数据库中，而是保存在 Agent workspace 里的普通文件：

- `memory/` 保存每天发生的事实、决定、进度和资料精读；
- `digest/` 保存跨时间仍然有用的偏好、流程和知识；
- `mem_session/` 保存可追溯的来源对话；
- `resource/` 保存 Daily Paper 下载的 PDF 等原始资料；
- `mem_metadata/` 保存可重建的索引、图谱和缓存。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i4/O1CN01wj1PUE1a2d5QtEyUv_!!6000000003272-55-tps-1200-640.svg" alt="Markdown 记忆文件连接长期知识和原始证据" />
</p>

这意味着你可以直接查看、修改、备份或迁移记忆。Markdown 文件是事实来源；索引和图谱只是派生状态，损坏后可以从文件重新构建。

一条长期记忆可能长这样：

```markdown
---
name: 发布沟通偏好
description: 发布说明先讲用户价值，再讲技术变化。
---

# 发布沟通偏好

发布说明先讲用户能得到什么，再说明技术变化。

## Sources

- [[memory/2026-08-06/release-discussion.md]]
```

正文保存知识，frontmatter 提供概要，`[[...]]` 则连接来源和相关节点。

### 2. Auto-Memory 从对话中留下有用的事

Auto-Memory 不会复制整段聊天，而是周期性识别以后仍可能有用的内容，例如：

- 稳定偏好与长期约定；
- 项目背景和限制条件；
- 已确认的决定及其原因；
- 当前进展、阻塞项与下一步；
- 可以复用的流程和排查经验。

例如，你说“这次不迁移数据库，因为发布时间紧，现有方案仍然够用；发布后再评估”，它会保留决定、原因、后续动作和来源，而不是只记住“不迁移数据库”。

默认每累计 5 个用户回合触发一次。发生上下文淘汰或折叠时，尚未处理的对话也会先进入同一条记忆流程。若没有值得新增或更新的内容，本次运行不会制造空记忆，也不会发送 Inbox 事件。

Auto-Memory 会把来源会话写入哈希命名的 JSONL 文件，并创建或更新当天的一张记忆卡片：

```text
mem_session/dialog/qpsid_sha256_<64-hex>.jsonl
memory/2026-08-06/release-discussion.md
```

自动召回的旧记忆会在抽取前移除，避免把“刚找回的内容”误当成用户新提供的事实。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01q1761gvctQB49nzS_!!6000000007099-0-tps-2048-414.jpg" alt="Auto-Memory 完成后推送到 Inbox 的任务结果" />
</p>

Inbox 只用于查看运行结果；真正可编辑、可复用的记忆仍然是 workspace 中的文件。

### 3. Daily Paper 让已接入的资料进入记忆

有价值的信息不只来自聊天。启用 Daily Paper 后，QwenPaw 会从 Hugging Face Papers 的周榜和月榜中筛选论文，保存原始 PDF，并生成三篇精读和一份每日简报。

- PDF 写入 `resource/papers/`；
- 精读和简报写入 `memory/YYYY-MM-DD/`；
- Markdown 阅读记录进入普通记忆索引，也能继续参与长期整理。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i4/O1CN01P4HuDOo3HjE3MD24_!!6000000007223-0-tps-1654-670.jpg" alt="Daily Paper 的调度与主题配置" />
</p>

Daily Paper 是当前内置的资料入口。任意文件仅仅放进 `resource/` 并不会被自动处理。

### 4. Auto-Dream 把每日记录整理成长期经验

只有 daily note 还不够。随着记录越来越多，Auto-Dream 会扫描近期发生变化的每日记忆，把可复用内容整合到 `digest/`。

面对已有知识，它会根据新证据选择：

| 动作          | 含义                                       |
| ------------- | ------------------------------------------ |
| `CREATE`      | 没有相同知识时创建新节点                   |
| `CORROBORATE` | 新材料再次证明已有记忆，补充来源或强化表述 |
| `REFINE`      | 新材料增加步骤、条件、边界或细节           |
| `CORRECT`     | 新材料修正已有节点中的错误、遗漏或冲突     |

例如，三次发布分别留下“说明太技术化”“先讲用户价值反馈更好”“重要变化最好配使用场景”，最终可以整理成一条稳定经验：

> 发布说明先讲用户能得到什么，再说明技术变化；重要变化尽量配一个实际使用场景。

Auto-Link 就发生在这个整合阶段。长期节点通过 `## Sources` 回到 daily note，也通过 Wikilink 连接相关的偏好、流程和知识。Auto-Dream 不会改写每日记忆：`memory/` 保留当时的现场，`digest/` 保存跨时间复用的结论。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i1/O1CN01ddkg0rN9DXK49o5c_!!6000000001181-0-tps-2048-796.jpg" alt="Auto-Dream 完成后推送到 Inbox 的任务摘要" />
</p>

Auto-Dream 还会生成 `interests.yaml`。它与 QwenPaw 当前的 `/proactive` mode 是独立能力；当前 `/proactive` 不读取该文件。

### 5. Memory Search 在需要时找回正确的记忆

当你问“当初为什么没有迁移数据库？”，`memory_search` 不需要重新阅读全部历史。它会：

1. 用 BM25 找到关键词相符的片段；
2. 配置 Embedding 后，再找到措辞不同但意思相近的片段；
3. 用 RRF 融合两组结果；
4. 按需沿 Wikilink 展开来源和相关知识。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN01Zln7TK1TJOGqP84hk_!!6000000002361-55-tps-1200-640.svg" alt="BM25 与向量检索融合后按需展开相关记忆" />
</p>

没有配置 Embedding 时，BM25 和 Wikilink 展开仍然可用。Embedding 的作用是补充语义检索，例如让“上线前检查”找到“生产发布前验证 staging”。详细配置见 [Embedding Models](./embedding)。

索引后台只监听 `memory/` 和 `digest/` 中的 `.md` 文件，每个文件最大 10 MiB。文件会按 Markdown 结构分块，并保留路径和行号；`resource/` 与 `mem_session/` 不直接进入记忆搜索。

### 完整循环

回到产品发布的例子：

1. Auto-Memory 把重要决定、原因和偏好写入 daily note；
2. Daily Paper 的精读也可以进入同一套每日记忆；
3. 后台索引持续让 Markdown 可搜索；
4. Auto-Dream 把零散记录整合为长期知识并建立链接；
5. Memory Search 在新问题出现时，只取回相关片段和依据；
6. 你可以随时检查和修正文件，修改后的内容继续参与后续协作。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i2/O1CN019aX2sCLIZvB6wGdo_!!6000000005818-0-tps-3418-1594.jpg" alt="QwenPaw 长期记忆控制台总览" />
</p>

## 参数配置

默认的 `remelight` backend 在 QwenPaw 进程内运行，并复用当前 Agent 的模型完成记忆抽取和整理。你可以在控制台配置，也可以编辑 `agent.json` 中的 `running.reme_light_memory_config`。

### 常用配置

```json
{
  "running": {
    "memory_manager_backend": "remelight",
    "reme_light_memory_config": {
      "auto_memory_interval": 5,
      "auto_memory_inbox_push_enabled": true,
      "dream_cron_enabled": true,
      "dream_cron": "0 23 * * *",
      "auto_dream_inbox_push_enabled": true,
      "daily_paper_cron_enabled": false,
      "daily_paper_cron": "0 9 * * *",
      "daily_paper_use_hf_mirror": false,
      "daily_paper_topics": "",
      "daily_paper_inbox_push_enabled": true,
      "memory_search_enabled": true,
      "auto_memory_search_config": {
        "enabled": false,
        "max_results": 2
      }
    }
  }
}
```

| 配置项                                  | 默认值         | 说明                                                               |
| --------------------------------------- | -------------- | ------------------------------------------------------------------ |
| `auto_memory_interval`                  | `5`            | 每累计 N 个用户回合触发 Auto-Memory；`null` 或 `<= 0` 关闭周期触发 |
| `auto_memory_inbox_push_enabled`        | `true`         | 记忆实际变化后，把 Auto-Memory 结果推送到 Inbox                    |
| `dream_cron_enabled`                    | `true`         | 启用定时 Auto-Dream                                                |
| `dream_cron`                            | `"0 23 * * *"` | 五段式 cron；实际运行前会随机延迟 0–60 秒                          |
| `auto_dream_inbox_push_enabled`         | `true`         | 把 Auto-Dream 结果推送到 Inbox                                     |
| `daily_paper_cron_enabled`              | `false`        | 启用定时 Daily Paper                                               |
| `daily_paper_cron`                      | `"0 9 * * *"`  | Daily Paper 的五段式 cron                                          |
| `daily_paper_use_hf_mirror`             | `false`        | 通过 Hugging Face 镜像获取论文信息                                 |
| `daily_paper_topics`                    | `""`           | 选论文时优先考虑的主题                                             |
| `daily_paper_inbox_push_enabled`        | `true`         | 把 Daily Paper 结果推送到 Inbox                                    |
| `memory_search_enabled`                 | `true`         | 向 Agent 提供手动 `memory_search` 工具                             |
| `auto_memory_search_config.enabled`     | `false`        | 每次普通用户请求前自动搜索记忆                                     |
| `auto_memory_search_config.max_results` | `2`            | 自动搜索时最多注入的结果数                                         |

自动搜索结果只注入当前请求，不写入正式会话历史，也不会再次被 Auto-Memory 保存。自动化产生的请求不会触发自动搜索。

### 目录与索引配置

| 配置项                   | 默认值           | 说明                                                 |
| ------------------------ | ---------------- | ---------------------------------------------------- |
| `metadata_dir`           | `"mem_metadata"` | 索引、图谱、catalog 和缓存目录                       |
| `session_dir`            | `"mem_session"`  | Auto-Memory 来源对话目录                             |
| `mem_session_dir`        | `"mem_agent"`    | ReMe 内部 memory-agent 会话目录                      |
| `resource_dir`           | `"resource"`     | Daily Paper 等工作流的原始资源目录                   |
| `daily_dir`              | `"memory"`       | 每日记忆目录                                         |
| `digest_dir`             | `"digest"`       | 长期知识目录                                         |
| `embedding_model_config` | 默认关闭         | 可选向量模型配置，见 [Embedding Models](./embedding) |
| `needs_reindex`          | `false`          | 向量空间变化后由运行时维护的待重建标记               |

旧字段 `inbox_push_enabled` 仅用于迁移：它会初始化尚未设置的三个任务级 Inbox 开关，但不会写回已验证的配置。

### 状态与重建索引

长期记忆页面可以查看后台任务、等待队列、资源占用和索引组件状态。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01hrPfLUAdE1C2Fz5c_!!6000000006909-0-tps-1112-1312.jpg" alt="ReMe 后台活动、资源占用和索引组件状态" />
</p>

正常的 Markdown 新增和修改会被增量索引。只有在控制台提示向量空间发生变化、索引损坏或搜索明显异常时，才需要使用 **Rebuild Memory Index**，或调用：

```http
POST /api/agents/{agentId}/memory/reindex
```

重建会清空派生索引，再从 `memory/` 和 `digest/` 的 Markdown 生成新索引；不会删除源记忆。运行期间 CPU 和内存占用可能上升，同一个 Agent 同时只能运行一个重建任务。

<p align="center">
  <img src="https://img.alicdn.com/imgextra/i3/O1CN01BCTjXC0jfMG1GYA0_!!6000000005728-0-tps-624-276.jpg" alt="重建记忆索引前的资源占用确认提示" />
</p>

---

## 其他 Memory Backend

QwenPaw 的记忆系统采用可插拔的 Backend 架构。除了默认的 ReMeLight（本地文件存储）外，还支持通过 `memory_manager_backend` 切换到其他后端。

### ADBPG（AnalyticDB for PostgreSQL）

基于云端向量数据库的长期记忆后端，适合需要跨设备共享、大规模语义检索的场景。QwenPaw 通过 ADBPG 记忆服务的 REST API 接入，无需安装额外数据库驱动。

**核心特点：**

- **跨会话持久化** — 记忆存储在云端数据库，重启后不丢失，支持多设备共享
- **服务端事实抽取** — 由 ADBPG 记忆服务完成事实提取，客户端无额外开销
- **REST API 接入** — 通过 HTTP API 调用 ADBPG 记忆服务
- **优雅降级** — ADBPG 不可达时 Agent 正常运行，仅长期记忆功能暂时禁用

**配置方式：**

进入 Agent 配置页面的「运行配置」标签，找到「长期记忆管理后端」下拉框，选择 `adbpg`，并在「ADBPG 长期记忆」Tab 中填写 `REST Base URL` 与 `REST API Key`。

![adbpg-backend](https://img.alicdn.com/imgextra/i3/O1CN01bH1Rj41wwQs3v04U6_!!6000000006372-2-tps-2954-1484.png)

> ⚠️ 切换后端不支持热更新，保存后需要重启 QwenPaw 才能生效（页面也会以黄色横幅提醒）。

> 迁移提示：ADBPG SQL 直连模式已移除。旧配置中的 `api_mode: "sql"`、
> `host`、`port`、`user`、`password`、`dbname`、LLM 和 Embedding 相关字段
> 会被忽略；请改为配置 `rest_base_url` 和 `rest_api_key`，保存后重启
> QwenPaw。

| 配置项                      | 说明                                                                    | 默认值                                |
| --------------------------- | ----------------------------------------------------------------------- | ------------------------------------- |
| `rest_base_url`             | ADBPG 记忆服务的 REST API 地址                                          | `""`                                  |
| `rest_api_key`              | REST API 的访问密钥                                                     | `""`                                  |
| `memory_isolation`          | 记忆隔离模式，`true` 为每个 Agent 独立，`false` 为共享                  | `true`                                |
| `search_timeout`            | 记忆搜索超时时间（秒）                                                  | `10.0`                                |
| `auto_memory_search_config` | 自动记忆搜索配置，结构与 ReMe Light 的 `auto_memory_search_config` 一致 | `{"enabled": true, "max_results": 3}` |

**配置示例：**

完整配置可写入 `agent.json` 的 `running.adbpg_memory_config` 字段：

```json
{
  "running": {
    "memory_manager_backend": "adbpg",
    "adbpg_memory_config": {
      "rest_base_url": "https://your-adbpg-memory-api.example.com",
      "rest_api_key": "your-rest-api-key",
      "memory_isolation": true,
      "search_timeout": 10.0,
      "auto_memory_search_config": {
        "enabled": true,
        "max_results": 3
      }
    }
  }
}
```

> 💡 通过 Console「运行配置」页面填写时，框架会自动将这些字段写入 `agent.json`，无需手动编辑文件。

---

## 相关页面

- [智能体记忆进化](./memory-evolving-and-proactive) — Auto-Memory、Auto-Dream、Auto-Memory-Search 与 Proactive 工作流
- [Embedding 向量模型](./embedding) — 向量模型能力、后端、配置与排查
- [控制台](./console) — 在控制台管理记忆与配置
- [配置与工作目录](./config) — 工作目录与 Agent 配置
