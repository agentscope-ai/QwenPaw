# Skills

**Skills**：内置多类能力，你还可以添加自定义 Skill，或者直接从社区 Skills Hub 导入 Skills。

管理 Skill 有两种方式：

- **控制台** — 在 [控制台](./console) 的 **Agent → Skills** 页面操作
- **工作目录** — 按本文步骤直接编辑文件

> 若尚未了解「频道」「心跳」「定时任务」等概念，建议先阅读 [项目介绍](./intro)。

应用从工作目录下的 `skills` 目录（默认 `~/.copaw/active_skills/`）加载能力：每个子目录中只要包含一份 `SKILL.md`，即会被识别为一个 Skill 并加载，无需额外注册。

---

## 内置 Skills 一览

当前内置的 Skills 如下，安装后会在首次需要时同步到工作目录，你可在控制台或通过配置启用/禁用。

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

修改后会自动同步到工作目录并影响 Agent 行为。适合不习惯直接改文件的用户。

---

## 内置 Skill：Cron（定时任务）

首次运行时会从包里把 **Cron** 同步到 `~/.copaw/active_skills/cron/`。它提供「按时间表执行任务并把结果发到频道」的能力；具体任务的增删改查用 [CLI](./cli) 的 `copaw cron` 或控制台 **Control → Cron Jobs** 完成，不需要手写 cron 以外的配置。

常用操作：

- 创建任务：`copaw cron create --type agent --name "xxx" --cron "0 9 * * *" ...`
- 查看列表：`copaw cron list`
- 查看状态：`copaw cron state <job_id>`

---

## 导入 Skill

当前支持在控制台中导入以下四种来源的 Skills：

- `https://skills.sh/...`
- `https://clawhub.ai/...`
- `https://skillsmp.com/...`
- `https://github.com/...`

### 步骤

1. 打开 [控制台](./console) → **智能体 → 技能**，点击右上角 **导入技能**。

   ![import](https://img.alicdn.com/imgextra/i1/O1CN01bPOPqG1msB1BfyaWH_!!6000000005009-2-tps-3422-1964.png)

2. 在弹窗中粘贴 Skill URL（获取方式见下方 **URL 获取示例**）。

   ![url](https://img.alicdn.com/imgextra/i1/O1CN01tkDSeA23nunikJNbG_!!6000000007301-2-tps-3422-1964.png)

3. 点击导入技能，等待导入完成。

   ![click](https://img.alicdn.com/imgextra/i2/O1CN015ZrEml1oGjsI3SnRZ_!!6000000005198-2-tps-3422-1964.png)

4. 导入成功后，在技能列表中可以看到新加入的 Skill。

   ![new](https://img.alicdn.com/imgextra/i2/O1CN01E5vUus1VdezregzVv_!!6000000002676-2-tps-3422-1964.png)

### URL 获取示例

1. 以 `skills.sh` 为例（`clawhub.ai` 和 `skillsmp.com` 获取 Skill URL 的方式相同），进入 `https://skills.sh/`。
2. 选择你需要的 Skill（以 `find-skills` 为例）。

   ![find](https://img.alicdn.com/imgextra/i4/O1CN015bgbAR1ph8JbtTsIY_!!6000000005391-2-tps-3410-2064.png)

3. 点击最上方的 URL 并复制，即为导入 Skill 时需要的 Skill URL。

   ![url](https://img.alicdn.com/imgextra/i2/O1CN01d1l5kO1wgrODXukNV_!!6000000006338-2-tps-3410-2064.png)

4. 如果想导入 GitHub 仓库中的 Skills，进入包含 `SKILL.md` 的页面（以 anthropics 的 skills 仓库中的 `skill-creator` 为例），复制最上方 URL 即可。

   ![github](https://img.alicdn.com/imgextra/i2/O1CN0117GbZa1lLN24GNpqI_!!6000000004802-2-tps-3410-2064.png)

### 说明

- 若同名 Skill 已存在，默认不会覆盖；建议先在列表中确认现有内容后再处理。
- 导入失败时优先检查：URL 是否完整、来源域名是否受支持、外网是否可访问。若遇到网络不稳定或 GitHub 限流，建议在 [控制台 → 设置 → 环境变量](./console#环境变量) 中添加 `GITHUB_TOKEN`；获取方式可参考 GitHub 官方文档：[管理个人访问令牌（PAT）](https://docs.github.com/zh/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)。

## 自定义 Skill（在工作目录中）

想通过文件方式给 Agent 加自己的一套说明或能力时，可以在 `customized_skills` 目录下手动添加自定义 Skill。

### 步骤

1. 在 `~/.copaw/customized_skills/` 下新建一个目录，例如 `my_skill`。
2. 在该目录下新建 `SKILL.md`。里面写 Markdown，给 Agent 看的能力说明、使用注意等；可选在文件开头用 YAML front matter 写 `name`、`description`、`metadata`，方便在 Agent 或控制台里展示。

### 目录结构示例

```
~/.copaw/
  active_skills/        # 实际激活的 Skill（由内置与自定义合并同步）
    cron/
      SKILL.md
    my_skill/
      SKILL.md
  customized_skills/    # 用户自定义 Skill（在此添加）
    my_skill/
      SKILL.md
```

### SKILL.md 示例

```markdown
---
name: my_skill
description: 我的自定义能力说明
---

# 使用说明

本 Skill 用于……
```

应用启动时会将内置 Skill 与 `~/.copaw/customized_skills/` 中的自定义 Skill 合并同步到 `~/.copaw/active_skills/`，同名时自定义优先。你在 `customized_skills` 中新加的目录不会被覆盖；内置 Skill 只会在 `active_skills` 中缺失时复制一次，已存在则不会覆盖。

---

## 相关页面

- [项目介绍](./intro) — 这个项目可以做什么
- [控制台](./console) — 在控制台管理 Skills 与频道
- [频道配置](./channels) — 接钉钉、飞书、iMessage、Discord、QQ
- [心跳](./heartbeat) — 定时自检/摘要
- [CLI](./cli) — 定时任务命令详解
- [配置与工作目录](./config) — 工作目录与 config
