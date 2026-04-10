# Skills

**Skills** 可以来自打包内置能力、本地技能池、Skills Hub 导入，或者你自己
写入的文件。

管理 Skill 有两种方式：

- **控制台：** 在 [控制台](./console) 的 **工作区 → 技能** 页面操作。
- **工作目录：** 直接在 `$QWENPAW_WORKING_DIR`（默认 `~/.qwenpaw`）下编辑技能文件，
  包括 `$QWENPAW_WORKING_DIR/skill_pool/` 和各工作区下的
  `$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/`。

> 若尚未了解「频道」「心跳」「定时任务」等概念，建议先阅读 [项目介绍](./intro)。

技能由共享池和各工作区的本地运行副本共同构成。具体结构和创建方式见下文。

---

## 技能结构

QwenPaw 的 skills 分为两层：

- **技能池：** 共享本地仓库，路径是 `$QWENPAW_WORKING_DIR/skill_pool/`
  （默认 `~/.qwenpaw/skill_pool/`）。
- **工作区技能副本：** 某个工作区真正运行时使用的本地副本，路径是
  `$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/`
  （默认 `~/.qwenpaw/workspaces/{agent_id}/skills/`）。

```
$QWENPAW_WORKING_DIR/                      # 默认 ~/.qwenpaw
  skill_pool/                # 共享池
    skill.json               # 池清单
    pdf/
      SKILL.md
    cron/
      SKILL.md
    my_shared_skill/
      SKILL.md
  workspaces/
    default/
      skill.json             # 工作区清单
      skills/                # 当前工作区真正使用的本地副本
        pdf/
          SKILL.md
        my_skill/
          SKILL.md
```

![技能池与工作区视觉图](https://img.alicdn.com/imgextra/i3/O1CN01BY2oPh1KqykMev8jC_!!6000000001216-2-tps-1919-1080.png)

### 技能池

技能池是内置技能和可复用共享技能的来源仓库。工作区 **不会直接运行** 技能池里的条目；
要使用某个池中技能，必须先把它广播到工作区。

技能池侧常见功能：

- **广播：** 把技能池中的技能复制到一个或多个工作区。
- **添加到池子：** 在技能池页面中创建、导入内置、从 URL 导入、上传 ZIP、
  从工作区上传、或手动放文件。
- **编辑 / 改名：** 普通共享 skill 用原名字保存时，会直接修改池中的这条技
  能。改成新名字保存时，会生成一个改名后的条目。内置技能不能用原名字原地定
  制覆盖；如果要改 builtin，必须另存为新名字，原 builtin 槽位保持不动。
- **冲突：** 如果保存、导入、上传或广播后会落到一个已经存在的名字上，
  QwenPaw 不会静默覆盖，而是直接返回冲突。界面 / API 会同时给出一个建议的新名
  字，便于你按这个名字重试。

向池子中添加技能的方式：

1. **导入内置技能**。
   内置 Skill 的 ID 以打包后的技能目录名为准。

   | Skill ID                      | 说明                                                                                               | 来源                                                           |
   | ----------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
   | **browser_cdp**               | 连接到已运行的 Chrome 或以开启 CDP / 远程调试的方式启动浏览器。仅在用户明确要求 CDP 时使用。       | 自建                                                           |
   | **browser_visible**           | 以可见模式（headed）启动真实浏览器窗口，适用于演示、调试或需要人工参与的场景。                     | 自建                                                           |
   | **channel_message**           | 在先定位目标 session / channel 后，主动向会话或频道发送单向消息。                                  | 自建                                                           |
   | **QA_source_index**           | QwenPaw 自身源码与文档的快速索引技能，用于把关键词映射到本地源码路径和文档。                       | 自建                                                           |
   | **cron**                      | 定时任务管理。通过 `qwenpaw cron` 或控制台定时任务创建、查询、暂停、恢复、删除定时任务。           | 自建                                                           |
   | **dingtalk_channel**          | 通过可视浏览器辅助完成钉钉频道接入流程，并提示用户完成必要手动步骤。                               | 自建                                                           |
   | **docx**                      | Word 文档（.docx）的创建、阅读、编辑，含目录、页眉页脚、表格、图片、修订与批注等。                 | https://github.com/anthropics/skills/tree/main/skills/docx     |
   | **file_reader**               | 读取与摘要文本类文件（如 .txt、.md、.json、.csv、.log、.py 等）。PDF 与 Office 由专用 Skill 处理。 | 自建                                                           |
   | **guidance**                  | 回答 QwenPaw 安装与配置问题，优先查本地文档。                                                      | 自建                                                           |
   | **himalaya**                  | 通过 CLI 管理邮件（IMAP/SMTP）。使用 `himalaya` 列出、阅读、搜索、整理邮件。                       | https://github.com/openclaw/openclaw/tree/main/skills/himalaya |
   | **multi_agent_collaboration** | 当用户明确要求其他 agent 参与，或需要其他 agent 的上下文与能力时，用于协作与双向沟通。             | 自建                                                           |
   | **news**                      | 从指定新闻站点查询最新新闻，支持政治、财经、社会、国际、科技、体育、娱乐等分类，并做摘要。         | 自建                                                           |
   | **pdf**                       | PDF 相关操作：阅读、提取文字/表格、合并/拆分、旋转、水印、创建、填表、加密/解密、OCR 等。          | https://github.com/anthropics/skills/tree/main/skills/pdf      |
   | **pptx**                      | PPT（.pptx）的创建、阅读、编辑，含模板、版式、备注与批注等。                                       | https://github.com/anthropics/skills/tree/main/skills/pptx     |
   | **xlsx**                      | 表格（.xlsx、.xlsm、.csv、.tsv）的读取、编辑、创建与格式整理，支持公式与数据分析。                 | https://github.com/anthropics/skills/tree/main/skills/xlsx     |

   在技能池页面里，内置技能可能显示 **最新** / **已过期** 之类状态。
   用 **更新内置技能** 可以补回缺失内置技能或将已过期的内置技能刷新到当前
   打包版本。

   内置的 **Cron** 技能提供定时任务管理。通过 [CLI](./cli) 的
   `qwenpaw cron` 或控制台 **控制 → 定时任务** 管理：

   - 创建任务：`qwenpaw cron create --type agent --name "xxx" --cron "0 9 * * *" ...`
   - 查看列表：`qwenpaw cron list`
   - 查看状态：`qwenpaw cron state <job_id>`

2. **直接在技能池页面中创建**。
   适合一开始就想做成共享 skill，而不是先在某个工作区里创建。

3. **从 URL 导入到池子**。
   技能池页面支持从受支持的 Hub / GitHub URL 直接导入。

4. **上传 ZIP 到池子**。
   适合已经打包好的一个或多个 skill 目录。

5. **从工作区上传到池子**。
   在 **工作区 → 技能** 页面点击 **同步到技能池**，可以把某个工作区技能发布到池子。

6. **手动在技能池目录中操作**。
   可以直接往 `$QWENPAW_WORKING_DIR/skill_pool/` 下放目录，但**不推荐**。技能池上的直接文件操作
   更容易被后续同步、重导入或人工误操作影响，尤其是自定义技能，要格外小心。

### 工作区技能副本

每个工作区都只运行自己 `skills/` 目录下的本地副本。这些本地副本才是 Agent
实际加载的 skill。

---

## Workspace 创建

工作区侧推荐按这个顺序理解创建方式：

### 1. 从技能池创建

这是使用内置技能和共享技能的首选方式。

1. 打开控制台的 **技能池** 页面。
2. 对目标 skill 点击 **广播**。
3. 选择目标工作区并确认。
4. skill 会被复制进工作区，并且**默认启用**。

如果目标工作区已经有同名 skill，广播会报冲突并给建议的新名字。

### 2. 通过界面创建

在 [控制台](./console) → **工作区 → 技能** 中直接填写名称和内容即可创建。
创建后会写入工作区的 `skills/` 目录和 `skill.json`，并且**默认启用**。

在编辑工作区 skill 的抽屉里，还可以使用 **AI 优化**。这个功能目前只是
**Beta**。它可能帮你改写或整理 skill 内容，但**不保证**生成结果一定可用，也
不保证优化后的 skill 一定能工作。保存前请务必人工检查。

### 3. 通过 ZIP 导入

工作区技能页支持 ZIP 导入。这和“向技能池添加技能”类似，只是目标位置变成了当前
工作区。导入后 skill **默认启用**。

### 4. 通过 URL 导入

工作区技能页支持从以下 URL 来源导入：

- `https://skills.sh/...`
- `https://clawhub.ai/...`
- `https://skillsmp.com/...`
- `https://lobehub.com/...`
- `https://market.lobehub.com/...`（LobeHub 直链下载地址）
- `https://github.com/...`
- `https://modelscope.cn/skills/...`

#### 步骤

1. 打开 [控制台](./console) → **工作区 → 技能**，点击 **从 Skills Hub 导入技能**。

   ![import](https://img.alicdn.com/imgextra/i1/O1CN0134XTb81v513NbR5YT_!!6000000006120-2-tps-2938-1560.png)

2. 在弹窗中粘贴 Skill URL（获取方式见下方 **URL 获取示例**）。

   ![url](https://img.alicdn.com/imgextra/i4/O1CN01enUOza1epPhw1IRJs_!!6000000003920-2-tps-2924-1562.png)

3. 点击**从 Skills Hub 导入技能**，等待导入完成。

   ![click](https://img.alicdn.com/imgextra/i3/O1CN019BEC8u1cImFpKaQJv_!!6000000003578-2-tps-2940-1556.png)

4. 导入成功后，skill 出现在技能列表中，**默认启用**。

   ![new](https://img.alicdn.com/imgextra/i2/O1CN01A4T0dQ1OxcxZ6jP3Q_!!6000000001772-2-tps-2940-1556.png)

#### URL 获取示例

1. 打开受支持的技能市场页面（以 `skills.sh` 为例；`clawhub.ai`、`skillsmp.com`、
   `lobehub.com`、`modelscope.cn` 获取方式类似）。
2. 选择你需要的 Skill（以 `find-skills` 为例）。

   ![find](https://img.alicdn.com/imgextra/i4/O1CN015bgbAR1ph8JbtTsIY_!!6000000005391-2-tps-3410-2064.png)

3. 复制地址栏中的 URL，即为导入 Skill 时需要的 Skill URL。

   ![url](https://img.alicdn.com/imgextra/i2/O1CN01d1l5kO1wgrODXukNV_!!6000000006338-2-tps-3410-2064.png)

   LobeHub 另外还提供 `https://market.lobehub.com/...` 形式的直链下载地址，
   也支持直接导入。

4. 如果想导入 GitHub 仓库中的 Skills，进入包含 `SKILL.md` 的页面（以 anthropics
   skills 仓库中的 `skill-creator` 为例），复制地址栏 URL 即可。

   ![github](https://img.alicdn.com/imgextra/i2/O1CN0117GbZa1lLN24GNpqI_!!6000000004802-2-tps-3410-2064.png)

#### 说明

- 若同名 Skill 已存在，默认不会覆盖；建议先在列表中确认现有内容。
- 导入失败时优先检查：URL 是否完整、来源域名是否受支持、外网是否可访问。
  若遇到 GitHub 限流，建议在控制台 → 设置 → 环境变量中添加 `GITHUB_TOKEN`；
  获取方式可参考 GitHub 官方文档：
  [管理个人访问令牌（PAT）](https://docs.github.com/zh/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)。

### 5. 手动创建

也可以直接在 `$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/` 下创建 skill 文件，包括让
QwenPaw 帮你写这些文件。

这种方式更灵活，但写入位置和 skill 质量不一定总是可控。你需要监督创建过程，
确认文件确实写进了正确的工作区目录，并检查 skill 内容质量后再使用。

在 `$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/` 下新建目录，并放入 `SKILL.md`。
`SKILL.md` 必须包含带 `name` 和 `description` 的 YAML front matter。若 Skill
依赖外部二进制或环境变量，可在 `metadata.requires` 中声明；QwenPaw 会将其透出为
`require_bins` 和 `require_envs` 元数据，但不会因此自动禁用 Skill。

#### SKILL.md 示例

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

工作区里常见的后续操作还有：

- **启用 / 禁用：** 不改文件内容，只切换这个 skill 是否生效。
- **删除：** 删除工作区 skill。如果 skill 当前处于启用状态，会自动先禁用再删除。
- **上传到技能池：** 把当前工作区 skill 发布到共享池，供其他工作区复用。
- **编辑频道范围 / config：** 调整这个 skill 在当前工作区中的生效频道与运行时
  配置。

---

## 频道路由

每个 Skill 可以限制在特定频道上生效。默认情况下，Skill 对**所有频道**生效
（`channels: ["all"]`）。

要限制某个 Skill 只在特定频道上生效：

1. 在 **工作区 → 技能** 中，点击某个技能的频道设置。
2. 选择希望该技能生效的频道（如 `discord`、`telegram`、`console`）。

Agent 在某个频道运行时，只会加载 `channels` 列表包含该频道（或 `"all"`）的技能。
这样可以实现频道专属技能，例如钉钉接入引导技能只在钉钉频道出现，不会出现在
Discord 上。

---

## Skill Config 运行时注入

每个 Skill 可以在 manifest 条目中存储一个 `config` 对象。这个 config 不只是
展示字段。当某个 Skill 在当前 workspace 和频道下生效时，QwenPaw 会在该次 Agent
运行期间把它注入到运行时环境中，Skill 结束后再回滚。

可以在控制台 **工作区 → 技能** 中点击技能的配置图标设置 config，也可以通过
API 操作。

### 注入方式

config 中与 SKILL.md `metadata.requires.env` 声明匹配的 key 会被注入为环境变量。
未在 `requires.env` 中声明的 key 不会注入（但仍可通过完整 JSON 变量读取）。
如果 config 缺少某个必需 key，会记录警告日志。

完整 config 始终以 `QWENPAW_SKILL_CONFIG_<SKILL_NAME>`（JSON 字符串）注入，
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

- `MY_API_KEY` 来自 config，并匹配 `requires.env`。
- `BASE_URL` 来自 config，并匹配 `requires.env`。
- `timeout` 不在 `requires.env` 中，因此只能通过完整 JSON 读取。
- `QWENPAW_SKILL_CONFIG_MY_SKILL` 始终包含完整 JSON 配置。

Python 示例：

```python
import json
import os

api_key = os.environ.get("MY_API_KEY", "")
base_url = os.environ.get("BASE_URL", "")
cfg = json.loads(os.environ.get("QWENPAW_SKILL_CONFIG_MY_SKILL", "{}"))
timeout = cfg.get("timeout", 30)
```

Config 在池与工作区同步时也会保留：上传工作区技能会把 config 复制到池条目，
下载时则把池的 config 复制到工作区条目。

### 配置优先级

Skill 运行时，生效配置按以下优先级（高优先覆盖低优先）：

1. **宿主环境变量：** 机器上已存在的环境变量不会被覆盖。
2. **工作区配置：** 工作区 manifest 条目（`skill.json`）中的 `config` 对象，
   即控制台中针对每个 Agent 编辑的配置。
3. **池配置：** 从池下载技能到工作区时，池的 `config` 会作为初始工作区配
   置复制过来，之后工作区的编辑优先。

对于 `requires` 元数据，解析器按顺序检查：`metadata.openclaw.requires` → `metadata.qwenpaw.requires` → `metadata.requires`，取第一个找到的。

---

## 从旧版本升级

将旧的 `active_skills/` 和 `customized_skills/` 目录转换为统一的工作区
`skills/` 布局。

迁移在首次启动时自动执行。技能是**复制**而非移动——原来的 `active_skills/` 和
`customized_skills/` 目录会保留。升级前请先备份重要的自定义 skill 内容。迁移会
尽量减少手工处理，但对长期有价值的 skill，仍建议你自行做好备份与管理。确认迁移
结果无误后，可以手动删除旧目录。**旧的 `active_skills/` 和 `customized_skills/` 中的 skill 不会再被读取。**

| 迁移前               | 迁移后                                                           |
| -------------------- | ---------------------------------------------------------------- |
| `active_skills/`     | 工作区 `skills/`（已启用）                                       |
| `customized_skills/` | 工作区 `skills/`（未启用，除非同名且内容相同地存在于 active 中） |

如果两个目录中存在同名但**内容不同**的技能，两个版本都会保留，并分别添加
`-active` / `-customize` 后缀。如需跨智能体共享工作区技能，可通过界面上传至
技能池。

---

## 相关页面

- [项目介绍](./intro) — 这个项目可以做什么
- [控制台](./console) — 在控制台管理 Skills 与频道
- [频道配置](./channels) — 接钉钉、飞书、iMessage、Discord、QQ
- [心跳](./heartbeat) — 定时自检/摘要
- [CLI](./cli) — 定时任务命令详解
- [配置与工作目录](./config) — 工作目录与 config
