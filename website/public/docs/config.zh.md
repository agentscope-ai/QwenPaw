# 配置与工作目录

本页涵盖以下内容：

- **工作目录** — 文件都放在哪
- **config.json** — 每个字段的含义与默认值
- **环境变量** — 如何用环境变量自定义路径

> 不需要读代码，照着改就行。

---

## 工作目录是啥？

CoPaw 所有配置和数据默认都在一个目录里，叫**工作目录**，默认是：

- **`~/.copaw`**（即你当前用户下的 `.copaw` 文件夹）

运行 `copaw init` 后会自动创建这个目录，里面大致是这样的：

| 文件/目录            | 作用                                          |
| -------------------- | --------------------------------------------- |
| `config.json`        | 频道开关与鉴权、心跳设置、语言等              |
| `HEARTBEAT.md`       | 心跳每次要问 CoPaw 的内容                     |
| `jobs.json`          | 定时任务列表（通过 `copaw cron` 或 API 管理） |
| `chats.json`         | 会话列表（文件存储模式）                      |
| `active_skills/`     | 当前激活的技能（Agent 实际使用的）            |
| `customized_skills/` | 用户自定义的技能                              |
| `memory/`            | Agent 记忆文件（自动管理）                    |
| `SOUL.md`            | _（必需）_ 核心身份与行为原则                 |
| `AGENTS.md`          | _（必需）_ 详细的工作流程、规则和指南         |

> **提示：** `SOUL.md` 和 `AGENTS.md` 是 Agent 系统提示词的最低要求。如果它们不存在，Agent
> 会退回到通用的 "You are a helpful assistant" 提示。运行 `copaw init` 时会根据你选择的
> 语言（`zh` / `en`）自动复制这些文件。

---

## 用环境变量改路径（可选）

如果你不想用 `~/.copaw`，可以通过环境变量改工作目录或某些文件的路径：

| 变量                               | 默认值         | 说明                                                           |
| ---------------------------------- | -------------- | -------------------------------------------------------------- |
| `COPAW_WORKING_DIR`                | `~/.copaw`     | 工作目录；config、心跳、jobs、chats、skills、memory 都在这下面 |
| `COPAW_CONFIG_FILE`                | `config.json`  | 配置文件名（相对工作目录）                                     |
| `COPAW_HEARTBEAT_FILE`             | `HEARTBEAT.md` | 心跳问题文件名（相对工作目录）                                 |
| `COPAW_JOBS_FILE`                  | `jobs.json`    | 定时任务文件名（相对工作目录）                                 |
| `COPAW_CHATS_FILE`                 | `chats.json`   | 会话列表文件名（相对工作目录）                                 |
| `COPAW_LOG_LEVEL`                  | `info`         | 日志级别（`debug`、`info`、`warning`、`error`、`critical`）    |
| `COPAW_MEMORY_COMPACT_THRESHOLD`   | `100000`       | 触发记忆压缩的字符阈值                                         |
| `COPAW_MEMORY_COMPACT_KEEP_RECENT` | `3`            | 压缩后保留的最近消息数                                         |
| `COPAW_MEMORY_COMPACT_RATIO`       | `0.7`          | 触发压缩的阈值比例（相对于上下文窗口大小）                     |
| `COPAW_CONSOLE_STATIC_DIR`         | _（自动检测）_ | 控制台前端静态文件路径                                         |

例如在 Linux/macOS 里临时换工作目录：

```bash
export COPAW_WORKING_DIR=/home/me/my_copaw
copaw app
```

这样 config、HEARTBEAT、jobs、memory 等都会在 `/home/me/my_copaw` 下读写。

---

## config.json 完整结构

下面是 **config.json 的完整字段说明**，包括类型、默认值和用途。你不需要填满所有字段——缺失的字段会自动用默认值。

### 完整示例

```json
{
  "channels": {
    "imessage": {
      "enabled": false,
      "bot_prefix": "",
      "db_path": "~/Library/Messages/chat.db",
      "poll_sec": 1.0
    },
    "discord": {
      "enabled": false,
      "bot_prefix": "",
      "bot_token": "",
      "http_proxy": "",
      "http_proxy_auth": ""
    },
    "dingtalk": {
      "enabled": false,
      "bot_prefix": "",
      "client_id": "",
      "client_secret": ""
    },
    "feishu": {
      "enabled": false,
      "bot_prefix": "",
      "app_id": "",
      "app_secret": "",
      "encrypt_key": "",
      "verification_token": "",
      "media_dir": "~/.copaw/media"
    },
    "qq": {
      "enabled": false,
      "bot_prefix": "",
      "app_id": "",
      "client_secret": ""
    },
    "console": {
      "enabled": true,
      "bot_prefix": ""
    }
  },
  "agents": {
    "defaults": {
      "heartbeat": {
        "every": "30m",
        "target": "main",
        "activeHours": null
      }
    },
    "running": {
      "max_iters": 50,
      "max_input_length": 131072
    },
    "language": "zh",
    "installed_md_files_language": "zh"
  },
  "last_api": {
    "host": "127.0.0.1",
    "port": 8088
  },
  "last_dispatch": null,
  "show_tool_details": true
}
```

### 逐字段说明

#### `channels` — 消息频道配置

每个频道都有通用字段和频道专属字段。

**通用字段（所有频道都有）：**

| 字段         | 类型   | 默认值  | 说明                      |
| ------------ | ------ | ------- | ------------------------- |
| `enabled`    | bool   | `false` | 是否启用该频道            |
| `bot_prefix` | string | `""`    | 可选命令前缀（如 `/paw`） |

**`channels.imessage`** — macOS iMessage

| 字段       | 类型   | 默认值                       | 说明                |
| ---------- | ------ | ---------------------------- | ------------------- |
| `db_path`  | string | `~/Library/Messages/chat.db` | iMessage 数据库路径 |
| `poll_sec` | float  | `1.0`                        | 轮询间隔（秒）      |

**`channels.discord`** — Discord 机器人

| 字段              | 类型   | 默认值 | 说明                            |
| ----------------- | ------ | ------ | ------------------------------- |
| `bot_token`       | string | `""`   | Discord Bot Token               |
| `http_proxy`      | string | `""`   | HTTP 代理地址（国内用户常需要） |
| `http_proxy_auth` | string | `""`   | 代理认证字符串                  |

**`channels.dingtalk`** — 钉钉

| 字段            | 类型   | 默认值 | 说明                     |
| --------------- | ------ | ------ | ------------------------ |
| `client_id`     | string | `""`   | 钉钉应用的 Client ID     |
| `client_secret` | string | `""`   | 钉钉应用的 Client Secret |

**`channels.feishu`** — 飞书 / Lark

| 字段                 | 类型   | 默认值           | 说明                     |
| -------------------- | ------ | ---------------- | ------------------------ |
| `app_id`             | string | `""`             | 飞书 App ID              |
| `app_secret`         | string | `""`             | 飞书 App Secret          |
| `encrypt_key`        | string | `""`             | 事件加密密钥（可选）     |
| `verification_token` | string | `""`             | 事件验证令牌（可选）     |
| `media_dir`          | string | `~/.copaw/media` | 接收到的媒体文件存放目录 |

**`channels.qq`** — QQ 机器人

| 字段            | 类型   | 默认值 | 说明                    |
| --------------- | ------ | ------ | ----------------------- |
| `app_id`        | string | `""`   | QQ 机器人 App ID        |
| `client_secret` | string | `""`   | QQ 机器人 Client Secret |

**`channels.console`** — 控制台（终端输入输出）

| 字段      | 类型 | 默认值 | 说明                            |
| --------- | ---- | ------ | ------------------------------- |
| `enabled` | bool | `true` | 默认开启；在终端打印 Agent 回复 |

> **提示：** 系统会每 2 秒自动检测 `config.json` 的变化。如果你在应用运行时修改了某个
> 频道的配置，系统会自动重载该频道——不需要重启。

---

#### `agents` — Agent 行为设置

| 字段                                 | 类型           | 默认值 | 说明                                                   |
| ------------------------------------ | -------------- | ------ | ------------------------------------------------------ |
| `agents.defaults.heartbeat`          | object \| null | 见下方 | 心跳配置                                               |
| `agents.running`                     | object         | 见下方 | Agent 运行时行为配置                                   |
| `agents.language`                    | string         | `"zh"` | Agent 提示词 MD 文件的语言（`"en"` 或 `"zh"`）         |
| `agents.installed_md_files_language` | string \| null | `null` | 记录当前已安装的 MD 文件语言；由 `copaw init` 自动管理 |

**`agents.running`** — Agent 运行时行为配置

| 字段               | 类型 | 默认值          | 说明                                                                                       |
| ------------------ | ---- | --------------- | ------------------------------------------------------------------------------------------ |
| `max_iters`        | int  | `50`            | ReAct Agent 推理-执行循环的最大轮数（必须 ≥ 1）                                            |
| `max_input_length` | int  | `131072` (128K) | 模型上下文窗口的最大输入长度（token 数）。记忆压缩将在达到此值的 80% 时触发（必须 ≥ 1000） |

**`agents.defaults.heartbeat`** — 心跳定时任务

| 字段          | 类型           | 默认值   | 说明                                                                         |
| ------------- | -------------- | -------- | ---------------------------------------------------------------------------- |
| `every`       | string         | `"30m"`  | 运行间隔。支持 `Nh`、`Nm`、`Ns` 组合，如 `"1h"`、`"30m"`、`"2h30m"`、`"90s"` |
| `target`      | string         | `"main"` | `"main"` = 只在主会话运行；`"last"` = 把结果发到最后一个发消息的频道/用户    |
| `activeHours` | object \| null | `null`   | 可选活跃时段，设置后心跳只在该时段内运行                                     |

**`agents.defaults.heartbeat.activeHours`**（不为 null 时）：

| 字段    | 类型   | 默认值    | 说明                         |
| ------- | ------ | --------- | ---------------------------- |
| `start` | string | `"08:00"` | 开始时间（HH:MM，24 小时制） |
| `end`   | string | `"22:00"` | 结束时间（HH:MM，24 小时制） |

> 详细指南请看 [心跳](./heartbeat)。

---

#### `last_api` — 上次使用的 API 地址

| 字段   | 类型           | 默认值 | 说明                        |
| ------ | -------------- | ------ | --------------------------- |
| `host` | string \| null | `null` | 上次 `copaw app` 绑定的主机 |
| `port` | int \| null    | `null` | 上次 `copaw app` 绑定的端口 |

每次运行 `copaw app` 时会自动保存。其他 CLI 子命令（如 `copaw cron`）会读取这个地址来发送请求。

---

#### `last_dispatch` — 最近一次消息分发目标

| 字段         | 类型   | 默认值 | 说明                                     |
| ------------ | ------ | ------ | ---------------------------------------- |
| `channel`    | string | `""`   | 频道名称（如 `"discord"`、`"dingtalk"`） |
| `user_id`    | string | `""`   | 该频道中的用户 ID                        |
| `session_id` | string | `""`   | 会话/对话 ID                             |

当用户发消息时会自动更新。心跳 `target = "last"` 时，心跳结果会发到这里记录的频道/用户/会话。

---

#### `show_tool_details` — 工具输出可见性

| 字段                | 类型 | 默认值 | 说明                                                                                       |
| ------------------- | ---- | ------ | ------------------------------------------------------------------------------------------ |
| `show_tool_details` | bool | `true` | 为 `true` 时，频道消息里显示完整的工具调用/返回详情。为 `false` 时隐藏详情（显示 "..."）。 |

---

## 模型提供商

CoPaw 需要 LLM 提供商才能运行。有三种设置方式：

- **`copaw init`** — 交互式向导，最简单
- **控制台 UI** — 在设置页面点选
- **API** — `PUT /providers/{id}` 和 `PUT /providers/active_llm`

### 内置提供商

| 提供商             | ID           | 默认 Base URL                                       | API Key 前缀 |
| ------------------ | ------------ | --------------------------------------------------- | ------------ |
| ModelScope（魔搭） | `modelscope` | `https://api-inference.modelscope.cn/v1`            | `ms`         |
| DashScope（灵积）  | `dashscope`  | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `sk`         |
| 自定义             | `custom`     | _（你自己填）_                                      | _（任意）_   |

每个提供商需要设置：

| 设置项     | 说明                             |
| ---------- | -------------------------------- |
| `base_url` | API 地址（内置提供商已自动填好） |
| `api_key`  | 你的 API Key                     |

然后选择激活哪个提供商和模型：

| 设置项        | 说明                             |
| ------------- | -------------------------------- |
| `provider_id` | 使用哪个提供商（如 `dashscope`） |
| `model`       | 使用哪个模型（如 `qwen3-max`）   |

> **提示：** 运行 `copaw init` 跟着提示走就行——它会列出每个提供商的可用模型让你直接选。
>
> **注意：** API Key 和 Base URL 的有效性需要用户自行保证。CoPaw 不会验证你填入的密钥是否正确或是否有余额，请确保所选提供商和模型可正常访问。

---

## 环境变量

部分工具需要额外的 API Key（如网络搜索用的 `TAVILY_API_KEY`）。有三种管理方式：

- **`copaw init`** — 初始化时会问 "Configure environment variables?"
- **控制台 UI** — 在设置页面编辑
- **API** — `GET/PUT/DELETE /envs`

设置好的变量会在应用启动时自动加载，所有工具和子进程都可以通过 `os.environ` 读取。

> **注意：** 环境变量的值（如第三方 API Key）的有效性需要用户自行保证。CoPaw 只负责存储和注入，不会校验其正确性。

---

## 技能（Skills）

技能扩展了 Agent 的能力。它们分布在三个目录中：

| 目录                          | 说明                                                           |
| ----------------------------- | -------------------------------------------------------------- |
| 内置（源码中）                | 随 CoPaw 一起发布——docx、pdf、pptx、xlsx、news、email、cron 等 |
| `~/.copaw/customized_skills/` | 用户自己创建的技能                                             |
| `~/.copaw/active_skills/`     | 当前激活的技能（从内置 + 自定义同步过来的）                    |

每个技能是一个目录，里面有 `SKILL.md` 文件（YAML front matter 中需包含 `name` 和
`description`），以及可选的 `references/` 和 `scripts/` 子目录。

管理技能的方式：

- `copaw init`（初始化时选择 all / none / custom）
- `copaw skills config`（交互式开关）
- API 接口（`/skills/...`）

---

## 记忆（Memory）

CoPaw 拥有跨对话的持久记忆能力：自动压缩上下文，并将关键信息写入 Markdown 文件长期保存。详细说明请看 [记忆](./memory.zh.md)。

记忆文件存储在两个位置：

| 文件/目录                       | 说明                                       |
| ------------------------------- | ------------------------------------------ |
| `~/.copaw/MEMORY.md`            | 长期有效的关键信息（决策、偏好、持久事实） |
| `~/.copaw/memory/YYYY-MM-DD.md` | 每日日志（日常笔记、运行上下文、自动摘要） |

### Embedding（向量嵌入）配置

记忆搜索依赖向量嵌入进行语义检索，通过以下环境变量配置：

| 环境变量               | 说明                     | 默认值                                              |
| ---------------------- | ------------------------ | --------------------------------------------------- |
| `EMBEDDING_API_KEY`    | Embedding 服务的 API Key | （空，不配置则禁用向量搜索）                        |
| `EMBEDDING_BASE_URL`   | Embedding 服务的 URL     | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `EMBEDDING_MODEL_NAME` | Embedding 模型名称       | `text-embedding-v4`                                 |
| `EMBEDDING_DIMENSIONS` | 向量维度                 | `1024`                                              |
| `FTS_ENABLED`          | 是否启用 BM25 全文检索   | `true`                                              |

> **推荐**：配置 `EMBEDDING_API_KEY` 并保持 `FTS_ENABLED=true`，使用向量 + BM25 混合检索以获得最佳效果。

---

## 小结

- 默认一切都在 **`~/.copaw`**；想改就设 **`COPAW_WORKING_DIR`** 等环境变量。
- 日常主要改 **config.json**（频道、心跳、语言）和 **HEARTBEAT.md**（心跳问什么）；定时
  任务用 CLI/API 管理即可。
- Agent 的人设由工作目录中的 Markdown 文件定义：**SOUL.md** + **AGENTS.md**（必需）。
- LLM 提供商通过 `copaw init` 或控制台 UI 配置。
- 频道配置的修改会**自动热加载**（每 2 秒检测一次），不需要重启。
- 直接调 Agent 接口：**POST** `/agent/process`，JSON 请求体、SSE 流式；具体示例见
  [快速开始 — 验证安装](./quickstart#验证安装可选)。

---

## 相关页面

- [项目介绍](./intro) — 这个项目可以做什么
- [频道配置](./channels) — config 里 channels 怎么填
- [心跳](./heartbeat) — config 里 heartbeat 怎么填

---

## Agent Prompt 文件一览

> 以下内容浓缩自 [Agent Prompt 文件](./agent_md_intro.zh.md)，完整说明请查阅原文。
>
> 本部分 Prompt 设计受 [OpenClaw](https://github.com/openclaw/openclaw) 启发。

| 文件             | 核心职责                            | 读写属性                                           | 关键内容                                                                  |
| ---------------- | ----------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------- |
| **SOUL.md**      | 定义 Agent 的**价值观与行为准则**   | 只读（由开发者/用户预先定义）                      | 真心帮忙不敷衍；有自己的观点不盲从；先自己想办法再问人；尊重隐私不越权    |
| **PROFILE.md**   | 记录 Agent 的**身份**和**用户画像** | 读写（BOOTSTRAP 自动生成，之后可手动或控制台修改） | Agent 侧：名字、定位、风格、能力范围；用户侧：名字、时区、偏好、背景      |
| **BOOTSTRAP.md** | 新 Agent 的**首次运行引导流程**     | 一次性（引导完成后自我删除 ✂️）                    | ① 自我介绍 → ② 了解用户 → ③ 写入 PROFILE.md → ④ 阅读 SOUL.md → ⑤ 自我删除 |
| **AGENTS.md**    | Agent 的**完整工作规范**            | 只读（日常运行核心参考）                           | 记忆系统读写规则；安全与权限；工具调用规范；Heartbeat 触发逻辑；操作边界  |
| **MEMORY.md**    | 存储 Agent 的**工具设置与经验教训** | 读写（Agent 自行维护，也可手动编辑）               | SSH 配置与连接信息；本地环境路径/版本；用户个性化设置与偏好               |
| **HEARTBEAT.md** | 定义 Agent 的**后台巡检任务**       | 读写（空文件 = 跳过心跳）                          | 空文件 → 不巡检；写入任务 → 按配置间隔自动执行清单                        |

**文件协作关系：**

```
BOOTSTRAP.md (🐣 一次性)
    ├── 生成 → PROFILE.md (🪪 我是谁)
    ├── 引导阅读 → SOUL.md (🫀 我的灵魂)
    └── 完成后自我删除 ✂️

AGENTS.md (📋 日常规范)
    ├── 读写 → MEMORY.md (🧠 长期记忆)
    ├── 参考 → HEARTBEAT.md (💓 定期巡检)
    └── 参考 → PROFILE.md (🪪 了解用户)
```

> **一句话总结：** SOUL 决定性格，PROFILE 记住关系，BOOTSTRAP 完成出生，AGENTS 规定行为，MEMORY 积累经验，HEARTBEAT 保持警觉。
