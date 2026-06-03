---
name: make-skill
description: "用于把当前会话沉淀为可复用的 workspace skill。当用户希望把当前对话、工作流或排错路径写成 SKILL.md 时触发。触发表达包括「把这个变成 skill」「记住我是怎么做 X 的」「保存这个工作流」「make a skill from this」以及任何 /make-skill <focus> 调用。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "✍️"
    requires: {}
---

<!--
  参考 Anthropic 的 `skill-creator` skill（尤其 "creating a skill" 部分），
  为 QwenPaw 改写。
  Credit: https://github.com/anthropics/skills/blob/main/skill-creator/SKILL.md
-->

# Make Skill

把当前会话沉淀为可复用的 workspace skill。

你自己编排两阶段流程：

* **Phase A.** 提出一份精简的计划，让出 turn 等用户 approve。
* **Phase B.** 用户 approve 后，基于 THIS 会话撰写完整 SKILL.md 正文，
  通过 `materialize_skill` 持久化。

**不要**用 `write_file` 直接写 SKILL.md。必须走 `materialize_skill`，
它会跑安全扫描并原子写入 manifest。

## 步骤 0. 确定 focus 并派生 skill 名

两种触发入口：

* `/make-skill <focus>`。focus 紧跟在命令后面。
* 自然语言（「把这个变成 skill」「保存这个工作流」「把刚才的 X 流程
  变成 skill」「make a skill from this」）。从用户想保存的对话主题里
  提炼一个简短 focus 短语。如果模糊，先问一句澄清。

按**这条规则**从 focus 派生 skill 名：

```
skill_name = "-".join(focus.split())
```

内部空白（空格、tab、全角空格、连续空格）折叠成单个 `-`。其他字符
原样保留。

例子：

* `cooking` → `cooking`
* `view image debug` → `view-image-debug`
* `烹饪 食谱` → `烹饪-食谱`
* `Stock Price` → `Stock-Price`（大小写保留）

这个 `skill_name` 在以下场合**保持一致使用**：步骤 1 的 `plan.name`、
步骤 3 的 `materialize_skill` 的 `name=` 参数。

## 步骤 1. 提出计划，让出 turn 等用户 approve

调用 `create_plan`，**四个必填参数**（`name`、`description`、
`expected_outcome`、`subtasks`）都要给：

* **`name`**：步骤 0 中标准化的 `skill_name`。
* **`description`**：精简 preview（这是用户审核的内容），两部分：
  * **Part 1：触发预览。** 2 到 4 句话，日常语言。必须覆盖三点：
    * **Goal.** 这个 skill 产生什么端到端结果。
    * **Trigger.** 哪些用户表达和场景应该触发它。稍微 push 一些
      同义词。
    * **I/O.** 期望什么输入，产出什么输出。
    这里不是 SKILL.md frontmatter 格式，frontmatter 后面再 distill。
  * **Part 2：步骤大纲。** 编号列表，每行一个简短动词短语。不写细
    节、不写参数、不写错误处理、不写 sub-bullet、不写 `##` 子标题。
    只给出形状，让用户能快速判断顺序和范围，决定要不要改。
    格式示例（**不要**抄这个内容）：
    ```
    1. <verb phrase, ~5-10 words>
    2. <verb phrase, ~5-10 words>
    3. <…>
    ```
    步骤名要从 THIS 会话里实际发生的事情里提取。不要编造；会话里没
    依据的就省略。
* **`expected_outcome`**（plan 顶层，**必填**，与 subtask 的
  `expected_outcome` 不是同一个）：一句具体描述整个 skill 创建的成功
  状态。直接用这个字面值（替换 `<skill_name>`）即可：
  `"A new workspace skill <skill_name> is created, enabled, and invocable via /<skill_name>."`
* **`subtasks`**：一个长度为 1 的列表，包含唯一一个 subtask：
  * `name`：`"Write and materialize skill"`
  * `description`：`"Write the SKILL.md body and call materialize_skill."`
  * `expected_outcome`：`"Skill created and visible via /skills."`

`plan.name` 和 `plan.description` 用**与用户最近消息相同的语言**。
`expected_outcome` 保留英文即可。

`create_plan` 返回后，**让出 turn**。用户会回复 approve、refine 或
cancel。`/plan` 模式的标准机制接管：

* Refine：调 `revise_current_plan`，把反馈合到 name、description、或步
  骤大纲里。
* Cancel：调 `finish_plan` with `state="abandoned"`。

向用户呈现计划时用标准 plan card 格式。**不要**在 chat 里另搞
`Subtask: …` / `Focus: …` 这种自定义字段，用标准化后的 `plan.name`，
不要用 raw focus。

### Plan 工具不可用时的 fallback

如果 `create_plan` 不在你的 toolkit 里（workspace 未启用 plan mode），
退回到文本式计划：

1. 把同样的精简 preview（Part 1 触发预览 + Part 2 步骤大纲）作为普通
   聊天消息发给用户。
2. 消息末尾请用户回复 approve、refine 或 cancel。
3. **让出 turn。** approve → 用你提出的大纲跳到步骤 2 写正文；
   refine → 修文本计划再让出 turn；cancel → 停止。
4. 跳过步骤 5 的 `finish_subtask` / `finish_plan`，没 plan 就没这两个
   动作。

## 步骤 2. 用户 approve 后撰写 SKILL.md 正文

用户 approve 计划、唯一的 subtask 转为 in-progress 后，基于 THIS 会话
写完整的 SKILL.md 正文。**内容能撑得起就不嫌长。**

写作风格：

* 使用祈使句。
* 对**非显而易见**的指令简要解释 WHY（next agent 的 theory of mind）。
  避免硬邦邦的 `MUST`。
* 正文目标少于约 500 行。接近上限就拆 sub-section + 加清晰指针。

### 2a. 与已 approve 的步骤大纲 1-to-1 对齐

正文主章节与 `plan.description` Part 2 一一对应：同序、同范围。章节
标题用对应步骤的动词短语。如果用户在 approve 阶段对 Part 2 做了
refine，**按 refined 版本**写。

### 2b. 每个步骤从 THIS 会话取实料

对每个步骤，**从会话事实出发**回答四个具体问题（不是凭常识猜）：

* **真正跑通的是哪个 tool、API、文件、命令？** 直接写真名。如果尝试
  过多个，**只**记录跑通的那个。
* **它使用的具体参数是什么？** 用会话中真实的参数值，不要占位符。
  未来的 agent 要能照搬直接跑。
* **本路径上撞过哪些错？怎么提前避开？** 写成预防性提示。例如：
  *「注意：该 endpoint 每秒被调用超过一次就返回 429。直接传
  `delay=2` 避开之前出现的重试循环。」*
* **哪些死路要跳过？** 试过三条路一条跑通时，只把跑通的那条完整写
  出。失败的那几条**仅**以简短的「避免 X」提醒带过，不要展开成
  子流程。

如果会话里没有某个问题的真实答案，**省略**这一项，不要编造。编造参
数或错误提示是本 skill 最常见的失败模式。

### 2c. 可选小节

只在能帮到 future agent 时才加，没有固定 schema：

* **Prerequisites。** 环境变量、auth 凭证、期待的输入文件、工具版本。
* **Worked example。** 一个真实调用，input 到 output。
* **Failure modes and recovery。** 已知失败模式与处理方式。
* **Edge cases。** 未来 agent 可能踩到的意外。

不适用就跳过。**空章节比省略更糟。**

### 2d. 输出格式（仅当稳定时）

如果会话里输出形态固定下来（表格、JSON schema、markdown 模板），在产
出该输出的步骤顶部用 `ALWAYS use this template:` 块**写一次**即可：

```markdown
ALWAYS use this exact template:

| Ticker | Last close | Currency | Source |
|--------|-----------|----------|--------|
| <symbol> | <price> | <iso-4217> | <api-name> |
```

如果输出本质是自由形态，跳过本步。

### 2e. 持久化前自查

完整通读一遍正文，**单 pass** 检查全部三项：

* **精简。** 无冗余，不重复前面章节已说过的内容。
* **覆盖 focus end-to-end。** `plan.description` Part 2 的每个步骤都已
  落到正文，且有事实支撑。
* **正确。** 每个 tool 名、API 名、参数值、错误提示都准确反映真实发
  生的事。**没有编造的事实，没有猜测的参数。**

任何一项不通过就回去修。

## 步骤 3. 通过 `materialize_skill` 持久化

调用 `materialize_skill`：

* **`name`**：与 `plan.name` 相同的标准化 `skill_name`。
* **`description`**：从 `plan.description` Part 1 浓缩出的紧凑
  `Use this skill when …` 串。≤ 200 字符。**保留** preview 中的同义词
  与邻近表达（LLM 倾向于**少触发** skill，描述稍微「推一下」比窄定
  义更可靠）。
* **`body`**：已 review 过的 SKILL.md 正文。**不含 frontmatter**，工
  具会自己渲染。

**不要**用 `write_file` 直接写 SKILL.md。

## 步骤 4. 处理 `materialize_skill` 的错误

### 命名冲突（skill 名已存在）

工具会返回冲突 skill 名 + 一个建议的改名。**自动恢复，不要再问用户。**

1. 挑一个新名字。工具的建议（例如带时间戳的）可以直接用，但只要避开
   冲突，任何合理改名都行。例如原名 `cooking` 已占用时可以用：
   `cooking-v2`、`cooking-2`、`cooking-new`。
2. 调 `revise_current_plan` 把 `plan.name` 改成新名（文本式计划
   fallback 时直接在内存里换掉工作名）。
3. 用新名字再调一次 `materialize_skill`。
4. 步骤 5 报告成功时**说明改名了**，让用户知道原名被占用。例如：
   *「已存为 `cooking-v2`，因为 `cooking` 已被占用。如果想用回原名，
   可以删掉旧的再跑 `/make-skill`。」*

### 格式错误

修正 SKILL.md 内容（frontmatter 字段、正文章节等）再调一次。
**`materialize_skill` 没成功前不要**调 `finish_subtask`。

### 安全扫描拒绝

移除被 flag 的模式再重试。

### 其他错误

调整输入再重试，或如果不可恢复就 abandon 计划。

## 步骤 5. 收尾

`materialize_skill` 返回成功后：

1. 对唯一的 subtask 调 `finish_subtask`。
2. 调 `finish_plan` with `state="completed"`。
3. 告知用户：新 skill 已创建并启用，可通过 `/<skill_name>` 调用。
