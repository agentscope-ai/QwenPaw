---
name: make-skill
description: "用于把当前会话沉淀为可复用的 workspace skill。当用户希望把当前对话、工作流或排错路径写成 SKILL.md 时触发。触发表达包括「把这个变成 skill」「记住我是怎么做 X 的」「保存这个工作流」「make a skill from this」以及任何 /make-skill <focus> 调用。"
metadata:
  builtin_skill_version: "1.1"
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

**不要**用 `write_file` 直接创建 SKILL.md 或其附属文件（脚本、JSON
等）。所有文件的首次创建必须走 `materialize_skill`（通过 `body` 和
`extra_files` 参数），它会跑安全扫描并原子写入 manifest。创建成功后，
如需修改可以使用 `edit_file` 编辑已有文件。

## 步骤 0. 确定 focus、派生 skill 名

### 0a. 确定 focus

两种触发入口：

* `/make-skill <focus>`。focus 紧跟在命令后面。
* 自然语言（「把这个变成 skill」「保存这个工作流」「把刚才的 X 流程
  变成 skill」「make a skill from this」）。从用户想保存的对话主题里
  提炼一个简短 focus 短语。如果模糊，先问一句澄清。

### 0b. 派生 skill 名

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
  * **Part 2：步骤大纲与 batch 规划。** 两部分内容：
    * **步骤大纲。** 编号列表，每行一个简短动词短语。不写细节、不写
      参数、不写错误处理、不写 sub-bullet、不写 `##` 子标题。只给出
      形状，让用户能快速判断顺序和范围。步骤名要从 THIS 会话里实际
      发生的事情里提取。不要编造；会话里没依据的就省略。
      格式示例（**不要**抄这个内容）：
      ```
      1. <verb phrase, ~5-10 words>
      2. <verb phrase, ~5-10 words>
      3. <…>
      ```
    * **Batch 规划。** 简要说明如何将上述步骤组织成 `run_tool_batch`
      的 JSON 文件：
      * 哪些步骤可以串成一个 batch（或需要拆成多个 batch 文件）。
      * 哪些中间环节原本需要 agent 介入判断，但实际上可以通过编写
        脚本（正则匹配、关键词筛选、JSON 解析等）来替代，从而减少
        agent 交互次数，让更多步骤纳入自动化 batch。
      * 列出预计需要的文件清单，如：
        ```
        scripts/main.json      — 主 batch 流程
        scripts/parse.py       — 解析 snapshot 提取目标内容
        ```
      目标是尽可能用脚本替代 agent 的中间判断，让 skill 执行时只需
      一次 `run_tool_batch` 调用即可完成，避免 agent 与工具之间的
      多轮交互。这让用户在 approve 前就能看到 batch 的整体结构。
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
不要用 raw focus。本步骤只负责提出计划并等待用户确认，**不要**在此步
调用 `materialize_skill`。

### 选择执行方式

用户 approve 后，询问执行方式（让出一轮 turn）：

> 计划已 approve。Phase B（撰写与持久化）要**在当前对话继续执行**，
> 还是**交给后台 subagent 执行**？
>
> - **当前对话**：在本轮对话中完成。适合需要反复 refine 的场景。
> - **后台**：交给 subagent 完成，不阻塞当前对话。subagent 继承本会话
>   完整上下文和已批准的计划。

**让出 turn**，等用户回复后再继续。如果用户没有明确选择，默认使用
当前对话模式。

* **当前对话**模式：按下方步骤 2–5 正常执行。
* **后台**模式：见下方「后台执行 Phase B」小节。

**如果你当前已经是 subagent**（由主 agent 通过 `spawn_subagent`
派生），跳过询问，直接执行步骤 2–4（主 agent 已完成 plan 收尾，
subagent 无需调用任何 plan 相关工具）。

### 后台执行 Phase B

Phase A（步骤 0–1）已在前台完成，用户已经 approve 了计划。现在将
Phase B 交给 subagent 执行。

这一步你自己**不需要**调用 `materialize_skill` 或执行任何 skill 创建
操作——只需组装 task 描述并提交给 subagent，由 subagent 完成全部后续
工作。

1. 将以下信息组装成 task 描述传给 subagent：
   - 已 approve 的 `plan.name`（`skill_name`）和计划内容
   - 明确指令：「基于当前会话上下文和已 approve 的计划，按 make-skill
     步骤 2–4 完整执行：撰写 SKILL.md 正文、调用 materialize_skill
     持久化、验证 batch 引用、试跑 batch。完成后报告结果。**无需调用
     任何 plan 相关工具（`create_plan`、`finish_subtask`、
     `finish_plan`），无需等待用户 approve，直接自行完成全部流程。**」
2. 调用：
   ```
   spawn_subagent(
       task="<上述 task 描述>。无需调用任何 plan 相关工具，直接完成全部流程。",
       fork=True,
       background=True,
   )
   ```
3. 立即对唯一的 subtask 调 `finish_subtask`，再调 `finish_plan` with
   `state="completed"` 收尾。不需要等 subagent 完成。
4. 告知用户已提交后台任务，可通过 `check_agent_task(task_id=...)` 查看
   进度。subagent 完成后会在 workspace 中创建 skill。

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

### 2b. 将完整流程整理为 batch JSON（首选执行方式）

**SKILL.md 正文的核心是一个 `run_tool_batch` 调用。** future agent 触发
skill 时应**直接调用 batch**，而不是逐步手动执行。分步说明只作为
batch 的补充参考（见 2c），不是主要执行指令。

回顾 THIS 会话中的工具调用序列，把 skill 的**完整端到端流程**整理成一
个 `run_tool_batch` JSON 文件。从流程起点到终点，所有**可以无条件串联
执行**的步骤都应纳入 batch。

#### 何时适用

* skill 的核心流程包含 **≥ 2 步的工具调用链**。
* 典型场景：批量文件操作、搜索后处理、多文件修改流水线、多步浏览器
  操作等。
* **大部分流程都可以通过脚本实现自动化。** 不要因为某个步骤「看起来
  需要判断」就放弃把它纳入 batch。绝大多数中间处理——提取内容、筛选
  结果、格式转换、条件判断、数据清洗——都能通过在 batch 中插入
  `execute_shell_command` 调用脚本来程序化。两种方式：
  * **内联短脚本**：直接在 `command` 中写
    `python3 -c "..."` 单行处理。
  * **独立脚本文件**：将复杂逻辑写成 `.py` 或 `.sh` 等文件放在
    `scripts/` 目录下（通过 `extra_files` 打包），batch 中用
    `execute_shell_command` 执行，如
    `"command": "python3 <skill_dir>/scripts/parse.py --param1 ${steps.<index1>.<path>} --param2 ${steps.<index2>.<path>}"`。
  通过命令行参数将前面步骤的输出（`${steps.<index>.<path>}`）传给
  脚本，脚本处理后的 stdout 供后续步骤通过 `${steps}` 引用。这样整个
  工作流就能串成一条完整的 batch 链，无需人工介入。只有**真正需要用户
  实时决策**的环节（如「让用户选择哪个选项」「等待用户确认是否继续」）
  才需要排除。

  `${steps.<index>.<path>}` 不只用于脚本调用——任何工具的参数都可以
  引用前面步骤的输出。例如将 `read_file` 的结果传给 `write_file`，
  或将 `browser_use` snapshot 的内容传给 `execute_shell_command`。

  示例——获取浏览器 snapshot，用独立 Python 脚本提取包含关键词的
  内容并写入文件。其中 `${args.keyword}` 等是调用 `run_tool_batch`
  时通过 `args` 参数传入的运行时变量，在执行前会被替换为实际值。

  `scripts/extract_headings.py`（通过 `extra_files` 打包）：
  ```python
  import sys, re, json

  keyword = sys.argv[1]
  snapshot_file = sys.argv[2]
  with open(snapshot_file) as f:
      text = f.read()
  items = [
      m.group(1)
      for m in re.finditer(
          r'heading "([^"]*' + re.escape(keyword) + r'[^"]*)" \[ref=(\w+)\]',
          text,
      )
  ]
  print(json.dumps(items, ensure_ascii=False))
  ```

  batch JSON（`scripts/extract.json`）：
  ```json
  [
    {
      "tool_name": "browser_use",
      "arguments": {"action": "snapshot"}
    },
    {
      "tool_name": "write_file",
      "arguments": {
        "file_path": "${args.work_dir}/snapshot.txt",
        "content": "${steps.0.text}"
      }
    },
    {
      "tool_name": "execute_shell_command",
      "arguments": {
        "command": "python3 ${args.skill_dir}/scripts/extract_headings.py ${args.keyword} ${args.work_dir}/snapshot.txt"
      }
    },
    {
      "tool_name": "write_file",
      "arguments": {
        "file_path": "${args.output_file}",
        "content": "${steps.2.text}"
      }
    }
  ]
  ```
  这样「从 snapshot 中筛选包含关键词的内容」这个原本需要人工判断的
  步骤就被自动化了：第 0 步获取页面 snapshot，第 1 步将 snapshot
  写入临时文件，第 2 步调用独立脚本读取文件并正则提取，第 3 步把
  结果写入目标文件。复杂的解析逻辑写成独立的 `.py` 文件放在
  `scripts/` 目录下，脚本和 batch JSON 都通过 `extra_files` 一并
  打包到 skill 目录中。触发 skill 时直接调用即可：
  ```
  run_tool_batch(
    file_path="<skill_dir>/scripts/extract.json",
    args={
      "keyword": "搜索关键词",
      "skill_dir": "<本skill目录>",
      "work_dir": "<工作目录>",
      "output_file": "result.json"
    }
  )
  ```

#### 何时不适用（退回纯分步说明）

绝大部分流程都可以自动化。只有同时满足以下条件时才退回分步逻辑：

* **内容理解无法规则化**——完全无法通过关键词匹配、正则、JSON 解析等
  基于规则的方式处理，必须依赖语义理解才能完成（注意：如果用户已给出
  明确的搜索词、筛选条件，那就是可以规则化的，应该纳入 batch）。
* **分支决策无法预先确定**——需要用户在执行过程中根据上下文实时判断
  下一步走哪条路，而不是用户在触发 skill 时就能一次性给定所有参数。
* 整个 skill 只有一次工具调用（无需 batch 封装）。

即使流程中存在需要人工判断的环节，也要**尽量把可以合并的连续步骤整理
成 batch**。这意味着一个 skill 可能包含多个 batch 文件——例如
`scripts/phase1.json`（获取数据阶段）和 `scripts/phase2.json`（处理
结果阶段），中间由 agent 基于语义判断决定如何衔接。能自动化的部分越多
越好。

#### SKILL.md 正文结构（当使用 batch 时）

正文应以 batch 调用为主体，格式如下：

````markdown
### 执行

本 skill 附带了 batch JSON 文件 `scripts/<name>.json`。

**严格按照以下格式调用 `run_tool_batch`，使用 `file_path` 加载文件
执行。不要自行构造 `actions` 列表内联传入。**

`run_tool_batch` 的 `file_path` 需要**绝对路径**。你在读取本 SKILL.md
时看到的目录路径即为本 skill 的绝对目录，请用它拼接出完整的
`file_path`。

```
run_tool_batch(
  file_path="<本skill目录>/scripts/<name>.json",
  args={
    "param1": "<实际示例值>",
    "param2": "<实际示例值>"
  }
)
```

### Batch 参数

逐项说明 `args` 中的每个参数。凡是 batch JSON 中出现
`${args.<name>}` 的变量，这里都必须列出，不能遗漏：

* `param1`：说明它控制什么；何时需要用户改；默认/推荐值是什么；示例：
  `<实际示例值>`。
* `param2`：说明它控制什么；何时需要用户改；默认/推荐值是什么；示例：
  `<实际示例值>`。

调用 `run_tool_batch` 时必须传入上面列出的所有参数。**不要传
`args={}`，也不要省略 `args`**，否则 `${args.<name>}` 不会展开，可能被
当作字面量文件名、URL 或命令参数使用。

### Batch 失败处理

如果 `run_tool_batch` 执行失败（返回 `ok: false` 或中途报错），请：
1. 先检查「Batch 参数」中列出的每个参数是否都已传入实际值，尤其不要
   使用空的 `args={}`；再根据错误信息修正参数后重试。
2. 如果仍然失败，可以尝试使用 `run_tool_batch` 的 `actions` 参数
   内联传入动作序列来执行。
3. 如果内联执行也失败，改为参照下方「分步参考」手动逐步执行完成任务。
4. 执行完毕后，提示用户：「本次 batch 执行遇到问题，已改为手动完成。
   是否需要我用 edit_file 调整和优化这个 skill 的 batch 脚本，以便下次
   能正常运行？」

### 分步参考

以下是 batch 中每一步的详细说明，仅在需要调试或手动执行时参考：

1. ...
2. ...

### 注意事项

（此处放置 skill 特定的注意事项，如参数优化建议、数据格式要求等。）

**执行方式提醒**：触发本 skill 时，直接使用上方的 `run_tool_batch(
file_path=..., args=...)` 调用即可完成全部流程，无需自己逐步编写每一个
action。只有当 batch 执行失败时，才参照「Batch 失败处理」中的降级方案。
````

> **路径说明**：`run_tool_batch` 只接受绝对路径。batch JSON 文件通过
> `materialize_skill` 的 `extra_files` 参数写入 skill 目录。agent 在
> system prompt 中会收到 skill 目录的绝对路径（即
> `Check "{dir}/SKILL.md"` 中的 `{dir}`），SKILL.md 正文中**必须**
> 明确告知 future agent 用该绝对目录拼出 `file_path`。

#### batch JSON 编写要点

* **`file_path` 必须是绝对路径**。SKILL.md 正文中应明确写出：
  「用你读取本 SKILL.md 时看到的目录路径拼接
  `scripts/xxx.json`」，让 future agent 构造出绝对路径。
* **用 `${args.<name>}` 参数化**所有因场景而变的值（文件路径、搜索关键
  词、URL 等）。固定不变的值直接写死。花括号语法是必须的，这样在
  shell 命令等混合内容字符串中不会产生歧义。
* **SKILL.md 必须包含 `### Batch 参数` 小节**。该小节要逐项解释 batch
  JSON 中每个 `${args.<name>}`：含义、何时需要用户修改、默认/推荐值、
  以及一个可直接用于试跑的实际示例值。`run_tool_batch` 示例中的
  `args` 必须填这些实际示例值，不能写 `{}`、`null`、`<说明>` 或只写
  占位描述。
* **用 `${steps.<index>.<path>}` 做步骤间引用**——后续步骤可引用前面步骤
  的输出。例如 `"content": "${steps.0.text}"` 引用第 0 步的文本结果。
  `<path>` 取决于上一步工具的实际返回值结构。`materialize_skill` 会
  自动分析 batch JSON 中的所有 `${steps}` 引用，并在返回中列出需要验证
  的引用关系。**你需要按提示逐个调用被引用的工具，确认其返回值确实
  包含所引用的字段**。如果字段不存在，用 `edit_file` 直接修正 skill
  目录下的 batch JSON 文件。
* 每个 action 使用 `"tool_name"` 和 `"arguments"` 字段（也兼容
  `"tool"` + `"args"`）。
* 一个 batch 文件最多 50 步。超过时拆成多个文件。
* JSON 文件通过 `extra_files` 打包进 skill 目录（详见步骤 3）。

### 2c. 补充分步说明（batch 的参考文档）

在 batch 调用之后，为每个步骤提供简要的分步说明。这些说明是 future
agent 在调试或手动执行时的参考，**不是主要执行指令**。

对每个步骤，**从会话事实出发**回答（不是凭常识猜）：

* **真正跑通的是哪个 tool、API、文件、命令？** 直接写真名。如果尝试
  过多个，**只**记录跑通的那个。
* **它使用的具体参数是什么？** 用会话中真实的参数值。
* **本路径上撞过哪些错？怎么提前避开？** 写成预防性提示。
* **哪些死路要跳过？** 失败路径**仅**以简短「避免 X」提醒带过。

如果会话里没有某个问题的真实答案，**省略**这一项，不要编造。编造参
数或错误提示是本 skill 最常见的失败模式。

当 skill 不适合 batch（需要分支决策），这些分步说明就是正文主体，
future agent 按步骤逐个执行。

### 2d. 可选小节

只在能帮到 future agent 时才加，没有固定 schema：

* **Prerequisites。** 环境变量、auth 凭证、期待的输入文件、工具版本。
* **Worked example。** 一个真实调用，input 到 output。
* **Failure modes and recovery。** 已知失败模式与处理方式。
* **Edge cases。** 未来 agent 可能踩到的意外。

不适用就跳过。**空章节比省略更糟。**

### 2e. 输出格式（仅当稳定时）

如果会话里输出形态固定下来（表格、JSON schema、markdown 模板），在产
出该输出的步骤顶部用 `ALWAYS use this template:` 块**写一次**即可：

```markdown
ALWAYS use this exact template:

| Ticker | Last close | Currency | Source |
|--------|-----------|----------|--------|
| <symbol> | <price> | <iso-4217> | <api-name> |
```

如果输出本质是自由形态，跳过本步。

### 2f. 持久化前自查

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
* **`extra_files`**（可选）：如果步骤 2c 中提取了 batch JSON 文件或其
  他辅助文件，通过此参数一并打包。key 是相对路径（如
  `"scripts/check-config.json"`），value 是文件内容字符串。示例：
  ```python
  materialize_skill(
      name="my-skill",
      description="Use this skill when ...",
      body="...",
      extra_files={
          "scripts/check-config.json": '{"actions": [...]}',
      },
  )
  ```
  `extra_files` 的 key 是相对于 skill 目录的路径。文件会被写入 skill
  目录下对应位置。SKILL.md 正文中应指引 future agent 用 skill 目录
  的绝对路径（system prompt 中可见）拼接出 `file_path` 的完整路径。

**不要**用 `write_file` 直接创建 SKILL.md 或附属文件。所有文件的首次
创建必须通过 `materialize_skill`。创建成功后如需修改，使用 `edit_file`。

## 步骤 4. 处理 `materialize_skill` 的返回

### 4a. 验证 `$steps` 引用（当包含 batch JSON 时）

当 `extra_files` 中包含 `run_tool_batch` 的 JSON 文件时，
`materialize_skill` 会自动分析其中所有的 `${steps.<index>.<path>}`
引用，并在返回中列出每条引用的来源工具和被引用字段。

**你需要对照返回的引用列表，逐条验证被引用工具的返回值是否确实包含
该字段。** 用 markdown 表格记录验证结果，格式如下：

| 引用表达式 | 来源工具 | 引用字段 | 验证方式 | 结果 |
|-----------|---------|---------|---------|------|
| `${steps.0.text}` | `read_file` | `text` | 查看本会话中之前的 `read_file` 调用结果 | ✅ 存在 |
| `${steps.2.content}` | `grep_search` | `content` | 用示例参数调用一次 `grep_search` 确认 | ❌ 字段不存在，应改为 `text` |

验证方式有两种，按优先级选择：

1. **查看本会话历史**：如果本会话中已经调用过该工具，直接检查之前的
   返回结果中是否包含该字段。
2. **重新调用测试**：如果本会话中没有调用过该工具，用示例参数调用
   一次，观察返回的 JSON 结构。

如果发现任何字段引用不正确：

1. 用 `edit_file` 直接编辑 skill 目录下对应的 batch JSON 文件，修正
   `$steps` path。skill 目录的绝对路径可从 `materialize_skill` 的成功
   返回中获取。
2. 如果 SKILL.md 正文中有引用相关说明也需要同步修正，同样用
   `edit_file` 直接编辑 skill 目录下的 `SKILL.md`。

不要重新调用 `materialize_skill`——skill 已经创建，直接编辑文件即可。

**所有引用验证通过后**，进入 4b 试跑。

### 4b. 试跑 batch（当包含 batch JSON 时）

引用验证通过后，尽量用示例参数实际跑一次 `run_tool_batch`，确认整条
链路能跑通：

```python
run_tool_batch(
    file_path="<skill目录>/scripts/<name>.json",
    args={
        "param1": "与 SKILL.md Batch 参数小节一致的实际示例值",
        ...
    }
)
```

如果 batch JSON 中包含任何 `${args.<name>}`，试跑时必须传入对应的实际
示例值。**禁止用 `args={}` 或 `args=None` 试跑**，否则不能验证参数展开
是否正确。

* 如果返回 `ok: true`，说明 batch 可正常工作，进入步骤 5。
* 如果返回错误，根据错误信息用 `edit_file` 修正 batch JSON 或辅助
  脚本，然后再跑一次。反复修正直到跑通或确认问题无法在当前环境修复
  （如缺少外部依赖、需要真实网络请求等）。
* 如果因环境限制无法试跑（例如需要浏览器、需要特定文件存在等），跳过
  试跑，在步骤 5 报告时告知用户：「batch 未经试跑，建议首次使用时关注
  执行结果。」

试跑通过后才能进入步骤 5。

### 4c. 命名冲突（skill 名已存在）

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

### 4d. 格式错误

修正 SKILL.md 内容（frontmatter 字段、正文章节等）再调一次。
**`materialize_skill` 没成功前不要**调 `finish_subtask`。

### 4e. 安全扫描拒绝

移除被 flag 的模式再重试。

### 4f. 其他错误

调整输入再重试，或如果不可恢复就 abandon 计划。

## 步骤 5. 收尾

步骤 4a 引用验证通过、4b 试跑通过（或因环境限制跳过）、
`materialize_skill` 返回成功后：

1. 对唯一的 subtask 调 `finish_subtask`。
2. 调 `finish_plan` with `state="completed"`。
3. 告知用户：新 skill 已创建并启用，可通过 `/<skill_name>` 调用。

---

## 完整流程总结

```
步骤 0  确定 focus → 派生 skill_name
         │
步骤 1  create_plan → 让出 turn → 用户 approve/refine/cancel
         │
      选择执行方式 → 让出 turn → 用户选择前台/后台
         │
         ├─ 前台 ─────────────────────────────────────────┐
         │                                                 │
         │  步骤 2  撰写 SKILL.md 正文（batch 优先）       │
         │  步骤 3  调用 materialize_skill 持久化          │
         │  步骤 4  验证引用 → 试跑 batch → 处理错误       │
         │  步骤 5  finish_subtask + finish_plan + 告知    │
         │                                                 │
         ├─ 后台 ─────────────────────────────────────────┐
         │                                                 │
         │  spawn_subagent(fork=True, background=True)     │
         │  主 agent 立即 finish_subtask + finish_plan     │
         │  subagent 执行步骤 2–4（无需 plan 工具）        │
         └─────────────────────────────────────────────────┘
```
