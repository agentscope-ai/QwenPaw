# Skills

**Skills**：内置多类能力，你还可以添加自定义 Skill，或者直接从社区 Skills Hub 导入 Skills。

管理 Skill 有两种方式：

- **控制台** — 在 [控制台](./console) 的 **Agent → Skills** 页面操作
- **工作目录** — 按本文步骤直接编辑文件

> 若尚未了解「频道」「心跳」「定时任务」等概念，建议先阅读 [项目介绍](./intro)。

每个 workspace 都在自己的 `skills/` 目录中保存本地 Skill，并通过
`skill.json` 控制是否启用。任意子目录只要包含一份 `SKILL.md`，就会被识别为
Skill，无需额外注册。

所有新建或导入的 Skill 默认**处于禁用状态**，需要在控制台或 CLI 中手动启用后才会生效。

---

## 内置 Skills 一览

当前内置的 Skills 如下。它们会出现在本地 skill pool 中，需要时可广播到某个
workspace，再由该 workspace 自己决定是否启用。

| Skill 名称                   | 说明                                                                                                                                        | 来源                                                           |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| **cron**                     | 定时任务管理。通过 `copaw cron` 或控制台 Cron Jobs 创建、查询、暂停、恢复、删除定时任务，按时间表执行并把结果发到频道。                     | 自建                                                           |
| **file_reader**              | 读取与摘要文本类文件（如 .txt、.md、.json、.csv、.log、.py 等）。PDF 与 Office 由下方专用 Skill 处理。                                      | 自建                                                           |
| **dingtalk_channel_connect** | 辅助完成钉钉频道接入流程：引导进入开发者后台、填写必要信息，帮助用户获取 `Client ID` 与 `Client Secret`，并提示用户完成必要的手动配置步骤。 | 自建                                                           |
| **himalaya**                 | 通过 CLI 管理邮件（IMAP/SMTP）。使用 `himalaya` 列出、阅读、搜索、整理邮件，支持多账户与附件管理。                                          | https://github.com/openclaw/openclaw/tree/main/skills/himalaya |
| **news**                     | 从指定新闻站点查询最新新闻，支持政治、财经、社会、国际、科技、体育、娱乐等分类，并做摘要。                                                  | 自建                                                           |
| **pdf**                      | PDF 相关操作：阅读、提取文字/表格、合并/拆分、旋转、水印、创建、填表、加密/解密、OCR 等。                                                   | https://github.com/anthropics/skills/tree/main/skills/pdf      |
| **docx**                     | Word 文档（.docx）的创建、阅读、编辑，含目录、页眉页脚、表格、图片、修订与批注等。                                                          | https://github.com/anthropics/skills/tree/main/skills/docx     |
| **pptx**                     | PPT（.pptx）的创建、阅读、编辑，含模板、版式、备注与批注等。                                                                                | https://github.com/anthropics/skills/tree/main/skills/pptx     |
| **xlsx**                     | 表格（.xlsx、.xlsm、.csv、.tsv）的读取、编辑、创建与格式整理，支持公式与数据分析。                                                          | https://github.com/anthropics/skills/tree/main/skills/xlsx     |
| **browser_visible**          | 以可见模式（headed）启动真实浏览器窗口，适用于演示、调试或需要人工参与（如登录、验证码）的场景。                                            | 自建                                                           |

---

## 通过控制台管理 Skills

在 [控制台](./console) 侧栏进入 **Agent → Skills**，可以：

- 查看当前已加载的 Skills 及启用状态；
- **启用/禁用**某个 Skill（开关切换）；
- **新建**自定义 Skill：填写名称与内容即可，无需手动建目录；
- **编辑**已有 Skill 的名称或内容。
- **导入** Skills Hub 中的 Skills

修改后会写入当前 workspace 的 `skills/` 目录与 `skill.json`，并影响该
workspace 的 Agent 行为。适合不习惯直接改文件的用户。

---

## 内置 Skill：Cron（定时任务）

**Cron** 是内置 Skill，可以从 skill pool 添加到某个 workspace。它提供
「按时间表执行任务并把结果发到频道」的能力；具体任务的增删改查用 [CLI](./cli)
的 `copaw cron` 或控制台 **Control → Cron Jobs** 完成，不需要手写 cron 以外的配置。

常用操作：

- 创建任务：`copaw cron create --type agent --name "xxx" --cron "0 9 * * *" ...`
- 查看列表：`copaw cron list`
- 查看状态：`copaw cron state <job_id>`

---

## 技能池（Skill Pool）

**技能池** 是一个本地共享仓库，存放在 `~/.copaw/skill_pool/`。它保存内置技能和
你选择跨 workspace 共享的自定义技能。

```
~/.copaw/
  skill_pool/                # 共享池
    skill.json               # 池清单（源数据）
    pdf/
      SKILL.md
    cron/
      SKILL.md
    my_shared_skill/
      SKILL.md
  workspaces/
    default/
      skill.json             # workspace 清单（启用/频道/配置）
      skills/                # 当前 workspace 的本地副本
        pdf/
          SKILL.md
        my_skill/
          SKILL.md
```

要点：

- 池中的技能**不会被任何 workspace 直接使用**。workspace 必须先**广播**（复制）
  技能，才能启用该技能。
- 每个 workspace 的 `skill.json` 是该 workspace 技能启用、频道路由和配置的唯一
  数据源。
- 池中的内置技能可以删除，之后也可以从打包源码重新导入回来；但仍然不能被同名的
  customized skill 原地覆盖。

### 从池广播到 workspace（pool → workspace）

要在 workspace 中使用池技能：

1. 在控制台进入 **技能池** 页面。
2. 点击想要的技能旁的 **广播**。
3. 选择目标 workspace 并确认。
4. 技能被复制到 workspace 的 `skills/` 目录，**默认禁用**。
5. 在 **Agent → Skills** 页面用开关启用它。

如果 workspace 中已有同名技能，广播会报告冲突并建议一个带时间戳后缀的替代名称。

workspace 通过 `sync_to_pool` 字段跟踪与池的关系：

| 状态         | 含义                                       |
| ------------ | ------------------------------------------ |
| `synced`     | workspace 副本与池版本一致                 |
| `not_synced` | 池中没有对应条目（如本地创建的技能）       |
| `conflict`   | 两者都存在但内容不同（广播后本地做了修改） |

### 从 workspace 上传到池（workspace → pool）

要在多个 agent 之间共享 workspace 技能，可以上传到池：

1. 在 **Agent → Skills** 页面点击 **上传**。
2. 选择要上传的技能并确认。
3. 如果池中已有同名技能，需要先改名或删除已有条目。
4. 上传后，workspace 条目标记为 `synced`，并关联到池中的副本。

如果同名内置技能已经存在，上传/创建/保存都会直接报冲突。你可以改名保存；如果确实想用同名
customized skill，先手动删除该 builtin 再创建。

### 导入内置技能

CoPaw 升级后，`src/` 下打包的内置技能可能比本地池中的版本更新，或者你也可能主动从
池里删除了一些 builtin。

如需把源码中的 builtin 导入到技能池：

1. 在控制台进入技能池页面。
2. 点击 **导入内置**。
3. 选择想要导入的 builtin 并确认。
4. 缺失的 builtin 会被补回。已是最新的条目不做改动。池中副本与打包版本不同的
   条目会报告冲突——确认后覆盖，或跳过以保留当前副本。

要单独更新某个已过期的 builtin，可以在技能池页面点击其卡片上的 **更新**。

你也可以先删除某个 builtin，之后再按需重新导入。

---

## 导入 Skill

当前支持在控制台中导入以下 Skill URL：

- `https://skills.sh/...`
- `https://clawhub.ai/...`
- `https://skillsmp.com/...`
- `https://lobehub.com/...`
- `https://market.lobehub.com/...`（LobeHub 直链下载地址）
- `https://github.com/...`
- `https://modelscope.cn/skills/...`

### 步骤

1. 打开 [控制台](./console) → **智能体 → 技能**，点击右上角 **导入 Hub**。

   ![import](https://img.alicdn.com/imgextra/i1/O1CN01bPOPqG1msB1BfyaWH_!!6000000005009-2-tps-3422-1964.png)

2. 在弹窗中粘贴 Skill URL（获取方式见下方 **URL 获取示例**）。

   ![url](https://img.alicdn.com/imgextra/i1/O1CN01tkDSeA23nunikJNbG_!!6000000007301-2-tps-3422-1964.png)

3. 点击导入技能，等待导入完成。

   ![click](https://img.alicdn.com/imgextra/i2/O1CN015ZrEml1oGjsI3SnRZ_!!6000000005198-2-tps-3422-1964.png)

4. 导入成功后，在技能列表中可以看到新加入的 Skill。

   ![new](https://img.alicdn.com/imgextra/i2/O1CN01E5vUus1VdezregzVv_!!6000000002676-2-tps-3422-1964.png)

### URL 获取示例

1. 以 `skills.sh` 为例（`clawhub.ai`、`skillsmp.com`、`lobehub.com` 和 `modelscope.cn` 获取 Skill URL 的方式类似），进入对应技能市场页面。
2. 选择你需要的 Skill（以 `find-skills` 为例）。

   ![find](https://img.alicdn.com/imgextra/i4/O1CN015bgbAR1ph8JbtTsIY_!!6000000005391-2-tps-3410-2064.png)

3. 点击最上方的 URL 并复制，即为导入 Skill 时需要的 Skill URL。

   ![url](https://img.alicdn.com/imgextra/i2/O1CN01d1l5kO1wgrODXukNV_!!6000000006338-2-tps-3410-2064.png)

   LobeHub 另外还提供 `https://market.lobehub.com/...` 形式的直链下载地址，这类 URL 也支持直接导入。

4. 如果想导入 GitHub 仓库中的 Skills，进入包含 `SKILL.md` 的页面（以 anthropics 的 skills 仓库中的 `skill-creator` 为例），复制最上方 URL 即可。

   ![github](https://img.alicdn.com/imgextra/i2/O1CN0117GbZa1lLN24GNpqI_!!6000000004802-2-tps-3410-2064.png)

### 说明

- 导入的技能**默认处于禁用状态**，需要手动启用。
- 若同名 Skill 已存在，默认不会覆盖；建议先在列表中确认现有内容后再处理。
- 导入失败时优先检查：URL 是否完整、来源域名是否受支持、外网是否可访问。若遇到 GitHub 限流，建议在 [控制台 → 设置 → 环境变量](./console#环境变量) 中添加 `GITHUB_TOKEN`；获取方式可参考 GitHub 官方文档：[管理个人访问令牌（PAT）](https://docs.github.com/zh/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)。

---

## 频道路由

每个 Skill 可以限制在特定频道上生效。默认情况下，Skill 对**所有频道**生效
（`channels: ["all"]`）。

要限制某个 Skill 只在特定频道上生效：

1. 在 **Agent → Skills** 中，点击某个技能的频道设置。
2. 选择希望该技能生效的频道（如 `discord`、`telegram`、`console`）。

Agent 在某个频道运行时，只会加载 `channels` 列表包含该频道（或 `"all"`）的技能。
这样可以实现频道专属技能——例如，钉钉接入引导技能只在钉钉频道出现，不会出现在
Discord 上。

---

## 自定义 Skill（在工作目录中）

想通过文件方式给 Agent 加自己的一套说明或能力时，可以在某个 workspace 的
`skills/` 目录下手动添加自定义 Skill。

### 步骤

1. 在 `~/.copaw/workspaces/{agent_id}/skills/` 下新建一个目录，例如 `my_skill`。
2. 在该目录下新建 `SKILL.md`。文件**必须**以 YAML front matter 开头，包含 `name` 和 `description` 两个必填字段。front matter 之后用 Markdown 编写给 Agent 的能力说明。若 Skill 依赖外部二进制或环境变量，可在 `metadata.requires` 中声明；CoPaw 会将其透出为 `require_bins` 和 `require_envs` 元数据，但不会因此自动禁用 Skill。

### SKILL.md 示例

```markdown
---
name: my_skill
description: 我的自定义能力说明
metadata:
  requires:
    bins: [ffmpeg]
    env: [MY_SKILL_API_KEY]
---

# 使用说明

本 Skill 用于……
```

`name` 和 `description` 为**必填**字段，`metadata` 为可选。

手动放置的 Skill 会在下次清单调和时被检测到，并以**禁用**状态写入 `skill.json`。
在控制台或 CLI 中启用即可。

---

## Skill Config 运行时注入

每个 Skill 可以在 manifest 条目中存储一个 `config` 对象。这个 config 不只是
展示字段——当某个 Skill 在当前 workspace 和频道下生效时，CoPaw 会在该次 Agent
运行期间把它注入到运行时环境中，Skill 结束后再回滚。

可以在控制台 **Agent → Skills** 中点击技能的配置图标设置 config，也可以通过
API 操作。

### 注入方式

config 中与 SKILL.md `metadata.requires.env` 声明匹配的 key 会被注入为环境变量。
未在 `requires.env` 中声明的 key 不会注入（但仍可通过完整 JSON 变量读取）。
如果 config 缺少某个必需 key，会记录警告日志。

完整 config 始终以 `COPAW_SKILL_CONFIG_<SKILL_NAME>`（JSON 字符串）注入，
不受 `requires.env` 影响。

宿主进程中已存在的同名环境变量不会被覆盖。

### 示例

若 `SKILL.md` 中声明：

```markdown
---
name: my_skill
description: demo
metadata:
  requires:
    env: [MY_API_KEY, BASE_URL]
---
```

config 为：

```json
{
  "MY_API_KEY": "sk-demo",
  "BASE_URL": "https://api.example.com",
  "timeout": 30
}
```

则运行时可读取：

- `MY_API_KEY` ← 来自 config，匹配 `requires.env`
- `BASE_URL` ← 来自 config，匹配 `requires.env`
- `timeout` ← 不在 `requires.env` 中，仅可通过完整 JSON 读取
- `COPAW_SKILL_CONFIG_MY_SKILL` ← 完整 JSON 配置（始终注入）

Python 示例：

```python
import json
import os

api_key = os.environ.get("MY_API_KEY", "")
base_url = os.environ.get("BASE_URL", "")
cfg = json.loads(os.environ.get("COPAW_SKILL_CONFIG_MY_SKILL", "{}"))
timeout = cfg.get("timeout", 30)
```

Config 在池与 workspace 同步时也会保留：上传 workspace 技能会把 config 复制到
池条目，下载时则把池的 config 复制到 workspace 条目。

### 配置优先级

Skill 运行时，生效配置按以下优先级（高优先覆盖低优先）：

1. **宿主环境变量** — 机器上已存在的环境变量不会被覆盖。
2. **工作区配置** — 工作区 manifest 条目（`skill.json`）中的 `config` 对象，即控制台中针对每个 Agent 编辑的配置。
3. **池配置** — 从池下载技能到工作区时，池的 `config` 会作为初始工作区配置复制过来，之后工作区的编辑优先。

对于 `requires` 元数据，解析器按顺序检查：`metadata.openclaw.requires` → `metadata.copaw.requires` → `metadata.requires`，取第一个找到的。

---

## 从旧版本升级

在最新版本引入。将旧的 `active_skills/` 和 `customized_skills/` 目录转换为统一的工作区技能布局。

所有迁移在首次启动时自动执行，无需手动操作。

| 迁移前               | 迁移后                                                           |
| -------------------- | ---------------------------------------------------------------- |
| `active_skills/`     | 工作区 `skills/`（已启用）                                       |
| `customized_skills/` | 工作区 `skills/`（未启用，除非同名且内容相同地存在于 active 中） |

- 两个目录中同名但**内容不同**的技能：两个版本都会保留，分别添加 `-active` / `-customize` 后缀。
- 内置技能由系统单独管理，始终从打包版本同步。
- 如需跨智能体共享工作区技能，可通过 UI 手动上传至技能池。

---

## 相关页面

- [项目介绍](./intro) — 这个项目可以做什么
- [控制台](./console) — 在控制台管理 Skills 与频道
- [频道配置](./channels) — 接钉钉、飞书、iMessage、Discord、QQ
- [心跳](./heartbeat) — 定时自检/摘要
- [CLI](./cli) — 定时任务命令详解
- [配置与工作目录](./config) — 工作目录与 config
