---
name: skill-maker
description: "用于把当前会话沉淀为可复用的 workspace skill —— 当用户希望把当前对话、工作流或排错路径写成 SKILL.md 时使用。触发表达包括「把这个变成 skill」「记住我是怎么做 X 的」「保存这个工作流」「make a skill from this」以及任何 /make-skill <focus> 调用。读取与 focus 相关的对话历史，起草完整 SKILL.md 正文，并通过 materialize_skill 工具持久化。"
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

# Skill Maker

把当前会话里 `focus` 是如何被完成的，沉淀为一个可复用的 workspace skill。完整读完本文件后按步执行，最后通过 `materialize_skill` 工具持久化 —— **不要**用 `write_file` 直接写 SKILL.md。

## 本 skill 期待的上下文

本 skill 由 `/make-skill <focus>` 在用户 approve 计划之后调用。读到这里时，以下信息已可用：

- `focus` —— 用户输入的 focus 字符串（在 subtask 上下文里传入）。
- `plan.name` —— 标准化后的 skill 目录名。
- `plan.description` —— 用户已 approve 的精简 preview，分两部分：
  - **Part 1**：触发预览（goal + 触发表达 + I/O 形态）。
  - **Part 2**：编号 **步骤大纲**（每行一个动词短语）。
- 当前会话的完整 memory。

如果用户在 approve 阶段对 plan 做了 refine，**以 refined 版本为准**，原始草稿作废。

## 范围：一切围绕 `focus`

正文的每个章节、段落、示例，都必须服务于"在 THIS session 里完成 `focus`"这条主线。无关的旁支即使技术上有趣、即使发生在同一会话，也要忽略 —— 未来读这条 skill 的 agent 不应被与 focus 无关的内容分心。

## 写作风格

使用祈使句，把读者视作下次执行本 skill 的 agent。

对**非显而易见**的指令简要解释 WHY —— 现代 LLM 有 theory of mind，会基于原因做适配，一句解释比硬邦邦的 `MUST` / `ALWAYS` 更耐用。死规则会随上下文变化失效，原因不会。

正文目标 < ~500 行。接近上限时把细节拆到子小节并加清晰指针，不要靠堆叠灌水。

## 步骤 1 —— 与已 approve 的步骤大纲 1-to-1 对齐

正文主章节必须与 `plan.description` Part 2 一一对应：同序、同范围。每章节的标题用对应步骤的动词短语。

如果用户在 approve 阶段对 Part 2 做了 refine（增、删、重排），**按 refined 版本**写，不要补回已删的步骤、不要改序。

## 步骤 2 —— 每个步骤从对话取实料

对每个步骤，正文必须从会话事实出发回答四个具体问题（不是凭常识猜）：

- **真正跑通的是哪个 tool / API / 文件 / 命令？** 直接写真名。如果尝试过多个，**只**记录跑通的那个。
- **它使用的具体参数是什么？** 用会话中真实的参数值，不要占位符。未来的 agent 要能照搬直接跑。
- **本路径上撞过哪些错？怎么提前避开？** 写成预防性提示，例如：*"注意：该 endpoint 每秒被调用超过一次就返回 429 —— 直接传 `delay=2` 避开之前出现的重试循环。"*
- **哪些死路要跳过？** 试过三条路、一条跑通时，只把跑通的那条完整写出；失败的那几条**仅**以简短的「避免 X」提醒带过，不要展开成子流程。

如果会话里没有某个步骤的真实答案，**省略**这一项，不要编造 —— 编造参数或错误提示是本 skill 最常见的失败模式。

## 步骤 3 —— 可选小节

只在能帮到未来 agent 时再加额外小节，没有固定 schema：

- **Prerequisites**：环境变量、auth 凭证、期待的输入文件、工具版本。
- **Worked example**：一个真实的调用 —— input → output。
- **Failure modes & recovery**：已知失败模式与处理方式。
- **Edge cases / gotchas**：未来 agent 可能踩到的意外。

不适用就跳过 —— 空章节比省略更糟。

## 步骤 4 —— 输出格式（仅当稳定时）

如果会话里输出形态已固定下来（一个固定的表格布局、一个 JSON schema、一个 markdown 模板），在产出该输出的步骤顶部用 `ALWAYS use this template:` 块**写一次**即可，例如：

```markdown
ALWAYS use this exact template:

| Ticker | Last close | Currency | Source |
|--------|-----------|----------|--------|
| <symbol> | <price> | <iso-4217> | <api-name> |
```

如果 skill 的输出本质上是自由形态（一段总结、一次重构、一段研究笔记），跳过本步骤。

## 步骤 5 —— 通过 `materialize_skill` 持久化

正文写完后，**先做调用前自查**，从头到尾通读一遍，逐项确认：

- **精简** —— 无冗余，不重复前面章节或 description 已说过的内容。
- **覆盖 `focus` end-to-end** —— `plan.description` Part 2 的每个步骤都已落到正文且有事实支撑；正文呈现完整路径（input → output）。
- **正确** —— 每个 tool 名、API 名、参数值、错误提示都准确反映 THIS session 真实发生的事。**没有编造的事实，没有猜测的参数**。

任何一项不通过就回去修。

自查通过后调用 `materialize_skill`：

- `name` = `plan.name`（已标准化的 skill 目录名）。
- `description` = 从 `plan.description` Part 1 浓缩出的紧凑 `Use this skill when …` 串，≤ 200 字符。**保留** preview 中的同义词与邻近表达 —— LLM 倾向于**少触发** skill，描述稍微"推一下"比窄定义更可靠。
- `body` = 你刚写完的 SKILL.md 正文（**不含 frontmatter** —— 工具会自己渲染）。

**不要**用 `write_file` 直接写 SKILL.md ——  `materialize_skill` 内部跑安全扫描、写 manifest、原子启用 skill，绕过它会让 workspace 处于不一致状态。

如果 `materialize_skill` 返回错误（format / scan / 命名冲突），修正对应输入再调一次。**不要**在 `materialize_skill` 成功前调用 `finish_subtask`。
