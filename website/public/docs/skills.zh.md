# Skills

**Skills** 可以来自打包内置能力、本地技能池、技能市场或 URL 导入，或者你自己
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
- **添加到池子：** 技能池页面提供统一的 **添加技能** 入口（创建技能、通过Zip上传、
  通过URL上传、浏览市场），此外还可以导入内置技能、从工作区上传、或手动放文件。
- **编辑 / 改名：** 普通共享 skill 用原名字保存时，会直接修改池中的这条技
  能。改成新名字保存时，会生成一个改名后的条目。修改内置技能的 `SKILL.md`
  后，该条目会转成自定义技能，之后不会被内置包自动覆盖。
- **冲突：** 如果保存、导入、上传或广播后会落到一个已经存在的名字上，
  QwenPaw 不会静默覆盖，而是直接返回冲突。界面 / API 会同时给出一个建议的新名
  字，便于你按这个名字重试。
- **自动同步：** 为技能开启后，技能池中的 `SKILL.md` 变化会触发完整技能目录
  同步到相关工作区（详见下文「技能自动化」）。
- **自动更新（仅内置技能）：** 开启后，当前内置技能包版本与技能池不同时，先让
  技能池副本跟随内置包，再按需自动同步到工作区（详见下文「技能自动化」）。

向池子中添加技能的方式：

1. **导入内置技能**。
   内置 Skill 的 ID 以打包后的技能目录名为准。

   | Skill ID                      | 说明                                                                                                                          | 来源                                                       |
   | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
   | **browser**                   | 通过 Unified Browser SDK 执行异步 Python，并遵循“感知 → 操作 → 验证”工作流。详见 [浏览器](./browser)。                        | 内置                                                       |
   | **channel_message**           | 在先定位目标 session / channel 后，主动向会话或频道发送单向消息。                                                             | 自建                                                       |
   | **QA_source_index**           | QwenPaw 自身源码与文档的快速索引技能，用于把关键词映射到本地源码路径和文档。                                                  | 自建                                                       |
   | **cron**                      | 定时任务管理。通过 `qwenpaw cron` 或控制台定时任务创建、查询、暂停、恢复、删除定时任务。                                      | 自建                                                       |
   | **dingtalk_channel**          | 通过可视浏览器辅助完成钉钉频道接入流程，并提示用户完成必要手动步骤。                                                          | 自建                                                       |
   | **docx**                      | Word 文档（.docx）的创建、阅读、编辑，含目录、页眉页脚、表格、图片、修订与批注等。                                            | https://github.com/anthropics/skills/tree/main/skills/docx |
   | **file_reader**               | 读取与摘要文本类文件（如 .txt、.md、.json、.csv、.log、.py 等）。PDF 与 Office 由专用 Skill 处理。                            | 自建                                                       |
   | **guidance**                  | 回答 QwenPaw 安装与配置问题，优先查本地文档。                                                                                 | 自建                                                       |
   | **mailbox**                   | 通过 qwenpawmail MCP 连接邮箱，收发、搜索、整理邮件，安全自动处理新邮件并学习可复用流程。详见 [邮箱管理与自动化](./mailbox)。 | 自建                                                       |
   | **multi_agent_collaboration** | 当用户明确要求其他 agent 参与，或需要其他 agent 的上下文与能力时，用于协作与双向沟通。                                        | 自建                                                       |
   | **news**                      | 从指定新闻站点查询最新新闻，支持政治、财经、社会、国际、科技、体育、娱乐等分类，并做摘要。                                    | 自建                                                       |
   | **pdf**                       | PDF 相关操作：阅读、提取文字/表格、合并/拆分、旋转、水印、创建、填表、加密/解密、OCR 等。                                     | https://github.com/anthropics/skills/tree/main/skills/pdf  |
   | **pptx**                      | PPT（.pptx）的创建、阅读、编辑，含模板、版式、备注与批注等。                                                                  | https://github.com/anthropics/skills/tree/main/skills/pptx |
   | **xlsx**                      | 表格（.xlsx、.xlsm、.csv、.tsv）的读取、编辑、创建与格式整理，支持公式与数据分析。                                            | https://github.com/anthropics/skills/tree/main/skills/xlsx |

   在技能池页面里，内置技能可能显示 **最新** / **已过期** 之类状态。
   用 **更新内置技能** 可以补回缺失内置技能或将已过期的内置技能刷新到当前
   打包版本。对于技能池中已有的内置技能，也可以在详情页开启 **自动更新**。
   自动更新成功后，该版本不再计入更新红点；新增或缺失技能仍需手动导入，已移除
   技能继续沿用原有的手动检查流程。

   内置的 **Cron** 技能提供定时任务管理。通过 [CLI](./cli) 的
   `qwenpaw cron` 或控制台 **控制 → 定时任务** 管理：

   - 创建任务：`qwenpaw cron create --type agent --name "xxx" --cron "0 9 * * *" ...`
   - 查看列表：`qwenpaw cron list`
   - 查看状态：`qwenpaw cron state <job_id>`

2. **通过统一的「添加技能」入口添加**。
   技能池页面右上角的 **添加技能** 下拉包含四种方式：

   - **创建技能**：适合一开始就想做成共享 skill，而不是先在某个工作区里创建。
   - **通过Zip上传**：导入已打包好的一个或多个 skill 目录。
   - **通过URL上传**：从受支持的 Hub / GitHub URL 直接导入。
   - **浏览市场**：切换到内嵌的技能市场，点击卡片上的 **保存** 即保存到技能池
     （详见下文「技能市场」）。

3. **从工作区上传到池子**。
   在 **工作区 → 技能** 页面点击 **同步到技能池**，可以把某个工作区技能发布到池子。

4. **手动在技能池目录中操作**。
   可以直接往 `$QWENPAW_WORKING_DIR/skill_pool/` 下放目录，但**不推荐**。技能池上的直接文件操作
   更容易被后续同步、重导入或人工误操作影响，尤其是自定义技能，要格外小心。

### 外部技能路径

默认情况下，技能池只有一个根目录：主池 `$QWENPAW_WORKING_DIR/skill_pool/`。
你还可以在配置中登记一个或多个 **外部技能根目录**，让 QwenPaw 把这些目录里的技能
一并读进 **同一个技能池视图**。这适合复用本机已有的技能集合（例如 git 仓库、团队
共享目录），而无需把它们复制进主池。

外部路径的语义：

- **同一个池，多个根。** 外部目录里的技能不会被复制到主池；它们原地被读入，与主池技能并列出现在技能池里。磁盘上的改动会在下次加载时反映出来。
- **顺序即优先级。** 扫描顺序为：先主池，再按配置中 `skill_paths` 的先后顺序。若不同根下有同名技能，**靠前的胜出**，靠后的同名技能被遮蔽并跳过（日志里会有一条warning）。
- **外部技能可以做什么。** 列出、查看、广播 / 下发到工作区、原地编辑（保存 / 改名会写回外部目录）、删除（会**物理删除外部目录下的文件**）。在技能池界面里，外部技能的**安装来源** 会显示它所在的外部路径，便于识别。
- **不会往外部目录写元数据。** 技能池的 `skill.json` 索引只保存在主池里，从磁盘重建并自愈；外部目录保持原样，不会被写入 manifest。
- **上传 / 导入始终落到主池。** 从工作区上传、从 ZIP 导入、从 URL 导入都只写入主池，不会写到外部路径。

#### 如何配置

编辑`$QWENPAW_WORKING_DIR/config.json`，添加顶层字段 `skill_paths`：

```json
{
  "skill_paths": ["~/my-skills", "/opt/team/shared-skills"]
}
```

说明：

- 数组有序，先后顺序决定上面的冲突优先级。
- 路径支持 `~` 展开到用户主目录。
- 不存在或无效的路径会被静默跳过。
- 保存后，下次加载技能池（刷新、重启或相关接口触发）时，外部技能即会出现。

`$QWENPAW_WORKING_DIR` 默认是 `~/.qwenpaw`，可由环境变量
`QWENPAW_WORKING_DIR` 覆盖。完整配置说明见 [配置](./config)。

### 工作区技能副本

每个工作区都只运行自己 `skills/` 目录下的本地副本。这些本地副本才是 Agent
实际加载的 skill。

---

## Workspace 创建

[控制台](./console) → **工作区 → 技能** 页面右上角的 **添加技能** 下拉是
统一入口，通过它添加的 skill 都**默认启用**：

- **从技能池载入**：勾选要载入的技能并确认。这是使用内置技能和共享技能的
  首选方式（也可以反过来在 **设置 → 技能池** 对目标 skill 点 **广播**）。
  同名冲突会报错并给建议的新名字。
- **创建技能**：填写名称和内容，创建后写入工作区的 `skills/` 目录和
  `skill.json`。编辑抽屉里的 **AI 优化** 目前是 **Beta**，可能帮你改写内容
  但不保证可用，保存前请人工检查。
- **通过Zip上传**：导入已打包好的一个或多个 skill 目录。
- **通过URL上传**：从受支持的 Hub / GitHub URL 导入，详见下方
  「通过 URL 导入」。
- **浏览市场**：切换到内嵌的技能市场，点卡片上的 **保存** 安装到当前工作区，
  详见下文[技能市场](#技能市场)。

此外，还可以在页面之外手动写文件，或用 `/make-skill` 从当前会话生成，见下。

### 通过 URL 导入

工作区技能页支持从以下 URL 来源导入：

- `https://skills.sh/...`
- `https://clawhub.ai/...`
- `https://skillsmp.com/...`
- `https://lobehub.com/...`
- `https://market.lobehub.com/...`（LobeHub 直链下载地址）
- `https://github.com/...`
- `https://modelscope.cn/skills/...`

CLI 支持相同的基于 URL 的导入方式：

**指定工作区：** 指定单个智能体工作区时使用 `--agent-id`；不指定时，`install` / `uninstall` 作用于技能池。

```bash
qwenpaw skills install <skill_url> --pool
qwenpaw skills install <skill_url> --agent-id <agent_id>
```

CLI 也支持从共享技能池或单个工作区卸载技能：

```bash
qwenpaw skills uninstall <skill_name> --pool
qwenpaw skills uninstall <skill_name> --agent-id <agent_id>
```

Workspace 技能可以按精确名称直接启用或禁用，也可以用支持即时文本过滤的复选界面
批量配置。Pool 是独立的共享作用域，可在支持的命令中用 `--pool` 选择；它没有
启用/禁用状态，因此 `config`、`enable`、`disable` 只支持 workspace：

```bash
qwenpaw skills enable <skill_name>... --agent-id <agent_id>
qwenpaw skills disable <skill_name>... --agent-id <agent_id>
qwenpaw skills list --status enabled --agent-id <agent_id>
qwenpaw skills list --pool
qwenpaw skills info <skill_name> --pool
```

#### 步骤

1. 打开 [控制台](./console) → **工作区 → 技能**，点击 **添加技能 → 通过URL上传**。

   ![import](https://img.alicdn.com/imgextra/i2/O1CN01iaEhjy1hOnXfVjZaK_!!6000000004268-2-tps-3822-2070.png)

2. 在弹窗中粘贴 Skill URL（获取方式见下方 **URL 获取示例**）。弹窗内会列出
   受支持的来源及各自的示例 URL，点击示例可直接填入输入框。

   ![url](https://img.alicdn.com/imgextra/i2/O1CN01l47mhN1aKwu48KLry_!!6000000003312-2-tps-3822-2070.png)

3. 点击**确认**，等待导入完成。

   ![click](https://img.alicdn.com/imgextra/i4/O1CN01amjZHZ1lwT7eVqWx9_!!6000000004883-2-tps-3822-2070.png)

4. 导入成功后，skill 出现在技能列表中，**默认启用**。

   ![new](https://img.alicdn.com/imgextra/i4/O1CN01TOYn2U1RFbk5BQOR1_!!6000000002082-2-tps-3822-2070.png)

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

### 手动创建

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

### 通过 /make-skill 从当前会话创建 (Beta)

刚在对话里跑完一个工作流（试过工具、撞过错、得出可行路径）, 用这个
命令把它存成 skill：

```
/make-skill 烹饪
```

会看到一张计划卡，展示建议的 skill 名和步骤大纲。用自然语言确认、
修改或取消。确认后，Agent 基于会话内容写出 skill 并保存到当前
workspace，**默认启用**。

`<focus>` 会作为 skill 名，内部空格折叠为 `-`（例如
`view image debug` → `view-image-debug`），其它字符（中文、大小写、
数字）保留原样。

`/make-skill` 本身是一个内建 skill，调用前请先在 `/skills` 中确认
它已启用。

### 技能自动化：自动更新与自动同步

两个阶段在技能详情页中独立配置：

```text
内置技能包 -- 自动更新 --> 技能池 -- 自动同步 --> 工作区
```

- **自动更新** 仅支持技能池中的内置技能。当前内置包版本与技能池版本不同时，
  QwenPaw 无需二次确认便会替换技能池副本。技能池始终跟随当前安装包，因此安装包
  降级时也会跟随降级；但不会自动导入新增或缺失技能、删除已移除技能，或覆盖已转成
  自定义的技能。
- **自动同步** 同时支持内置和自定义技能。`SKILL.md` 变化会触发完整技能目录复制
  到配置的工作区，无需手动广播。
- **组合开启：** 两项都开启时，先更新技能池，再把新版本同步到工作区。只开自动
  更新时仅修改技能池；只开自动同步时仍会传播技能池内容，但不会升级内置版本。
- **配置命名：** `auto_update` 始终表示“内置技能包 → 技能池”，`auto_sync` 始终
  表示“技能池 → 工作区”。新配置统一收在每个技能的 `automation` 对象中。旧的扁平
  `auto_update` 同步开关及其目标和同步 hash 仍可读取，并会在技能池下次写入时归一化
  到 `automation.auto_sync`；新的自动更新默认关闭，不会被误开启。

  ```json
  {
    "automation": {
      "auto_update": { "enabled": true },
      "auto_sync": {
        "enabled": true,
        "targets": ["default"]
      }
    }
  }
  ```

  自定义技能不包含 `auto_update`。省略 `targets` 时，默认同步到已经包含该技能的
  工作区。

- **检查时机：** 保存或开启自动化设置后立即检查，应用启动时检查，手动刷新技能池
  时检查。仅打开页面不会修改技能，也不会启动轮询。
- **同步范围：**
  - **默认**（未配置关联智能体）：只同步给那些**已安装该技能**的工作区。
  - **指定关联智能体：** 精确同步到所选智能体；尚未安装该技能的所选智能体会自动
    安装。关闭自动同步不会清空选择，下次开启时继续使用。
- **卡片快捷操作：** 自定义技能沿用原卡片入口切换自动同步。内置技能也只保留这一个
  入口，用于同时开启或关闭两项设置；若当前只开启其中一项，卡片显示混合状态并打开
  详情页，不擅自决定要修改哪一项。
- **状态与通知：** 自动更新成功后，对应版本的更新红点会消失；失败和需要手动处理的
  变更仍会显示。一次内置技能更新会在 [收件箱](./console) 生成一条合并消息，同时
  展示技能池版本变化和工作区同步结果；仅自动同步的运行仍使用原同步消息。

---

工作区里常见的后续操作还有：

- **启用 / 禁用：** 不改文件内容，只切换这个 skill 是否生效。
- **预加载 / 按需加载：** 默认按需加载；可在 **工作区 → 技能 → 编辑** 中，为可信的
  核心或高频 Skill 开启预加载，其完整内容会作为结构化 Skill 区块加入系统提示词。
- **删除：** 删除工作区 skill。如果 skill 当前处于启用状态，会自动先禁用再删除。
- **同步到技能池：** 把当前工作区 skill 发布到共享池，供其他工作区复用。
- **编辑频道范围 / config：** 调整这个 skill 在当前工作区中的生效频道与运行时
  配置。

---

## 技能市场

在一个页面内跨多个市场搜索并安装 skill。技能市场内嵌在技能相关页面里：
在 **工作区 → 技能** 或 **设置 → 技能池** 页面点击 **添加技能 → 浏览市场**
即可切换到市场视图（点 **返回** 或浏览器后退回到列表）。相比上面"从 URL 导入"
的逐条粘贴流程，这里是基于搜索的入口。

内置四个数据源：

- **QwenPaw** —— 公开，始终启用。
- **ClawHub** —— 公开，始终启用。
- **ModelScope** —— 公开，始终启用。
- **Aliyun** —— 需在 **设置 → 环境变量** 中配置
  `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET`；
  未配置时该数据源会被置灰，并在 tooltip 中显示原因。

工作机制：

- 支持按 **来源**、**分类** 和关键词筛选；分类会自动映射为各数据源的原生分类
  或等价检索词。
- 搜索并行调用所有启用的数据源；单个数据源失败不影响其它结果展示。
- **保存** 的目标由入口决定：从 **工作区 → 技能** 进入保存到当前工作区，从
  **设置 → 技能池** 进入保存到技能池。
- 安装走串行队列（同一时刻只跑一个），支持重试和取消；重名时会以失败项展示服务端错误，可改名后重装。

安装完成后，每个 skill 都会记住自己的来源（`installed_from` 字段），在技能抽屉中以 **安装来源** 展示。可能的取值包括 `clawhub`、`modelscope`、
`aliyun`、`skills-sh`、`lobehub`、`skillsmp`、`github`、`url`、`zip`；没有记录来源的 skill（内建、手动创建、legacy 条目）该字段显示为空。

对于搜索数据源未覆盖的来源（skills.sh、lobehub.com、github.com 等），
仍可继续使用上面的"从 URL 导入"流程。

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
