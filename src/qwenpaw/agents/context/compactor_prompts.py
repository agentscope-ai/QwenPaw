# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Compactor prompt templates for context compression."""

SYSTEM_PROMPT_EN = """\
You are a context compaction assistant. Your role is to create structured summaries of conversations
that can be used to restore context in future sessions. Focus on preserving critical information while reducing token count."""

SYSTEM_PROMPT_ZH = """\
你是一个上下文压缩助手。你的角色是创建对话的结构化摘要，
这些摘要可以在未来会话中用于恢复上下文。专注于保留关键信息，同时减少token数量。"""

SUMMARY_PROMPT_EN = """\
# Summary of previous conversation
Previous conversation logs are offloaded to dialog/YYYY-MM-DD.jsonl (or nearby date files).
Here is the summary:
{summary}
The above is a summary of previous conversation, use it as context to maintain continuity."""

SUMMARY_PROMPT_ZH = """\
# 之前对话的摘要
之前的对话日志已转储到 dialog/YYYY-MM-DD.jsonl（或相近日期的文件）。
以下是摘要：
{summary}
以上是之前对话的摘要，请将其作为上下文以保持对话的连续性。"""

INITIAL_USER_MESSAGE_EN = """\
# Task
Create a structured summary from the conversation above.

# Rules:
- Keep each section concise
- Preserve exact file paths, function names, and error messages

# Output Format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

Output the structured summary following the format above."""

INITIAL_USER_MESSAGE_ZH = """\
# 任务
根据上面的对话创建一个结构化摘要。

# 规则：
- 保持每个部分简洁
- 保留确切的文件路径、函数名称和错误消息

# 输出示例：

## 目标
[用户试图完成什么？如果会话涵盖不同任务，可以有多个项目。]

## 约束和偏好
- [任何用户提到的约束、偏好或要求]
- [或者如果没有提到则为"(none)"]

## 进展
### 已完成
- [x] [已完成的任务/更改]

### 进行中
- [ ] [当前工作]

### 阻塞
- [如果有任何阻碍进展的问题]

## 关键决策
- **[决策]**: [简短理由]

## 下一步
1. [接下来应该发生的事情的有序列表]

## 关键上下文
- [任何继续工作所需的数据、示例或参考资料]
- [或者如果不适用则为"(none)"]

请按照上面示例的格式，输出结构化摘要。"""

UPDATE_USER_MESSAGE_EN = """\
# Task
Update the structured summary with new conversation messages.

# Rules:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it

# Output Format:

## Goal
[Preserve existing goals, add new ones if the task expanded]

## Constraints & Preferences
- [Preserve existing, add new ones discovered]

## Progress
### Done
- [x] [Include previously done items AND newly completed items]

### In Progress
- [ ] [Current work - update based on progress]

### Blocked
- [Current blockers - remove if resolved]

## Key Decisions
- **[Decision]**: [Brief rationale] (preserve all previous, add new)

## Next Steps
1. [Update based on current state]

## Critical Context
- [Preserve important context, add new if needed]

Output the structured summary following the format above."""

UPDATE_USER_MESSAGE_ZH = """\
# 任务
使用新的对话内容来更新结构化摘要。

# 规则：
- 保留来自先前摘要的所有现有信息
- 从新消息中添加新的进展、决策和上下文
- 更新进度部分：当完成时将项目从"进行中"移到"已完成"
- 根据已完成的内容更新"下一步"
- 保留确切的文件路径、函数名称和错误消息
- 如果某些内容不再相关，您可以删除它

# 输出示例：

## 目标
[保留现有目标，如果任务扩展则添加新目标]

## 约束和偏好
- [保留现有内容，添加发现的新内容]

## 进展
### 已完成
- [x] [包含以前完成的项目和新完成的项目]

### 进行中
- [ ] [当前工作 - 根据进展更新]

### 阻塞
- [当前阻塞问题 - 如果解决则删除]

## 关键决策
- **[决策]**: [简短理由]（保留所有之前的内容，添加新的）

## 下步
1. [根据当前状态更新]

## 关键上下文
- [保留重要上下文，如需要则添加新的]

请按照上面示例的格式，输出结构化摘要。"""
