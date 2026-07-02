# -*- coding: utf-8 -*-
"""Review prompt templates for QwenPaw AI Review Bot.

The review methodology, coding standards, and anti-pattern checklist
live in the workspace persona files (SOUL.md, AGENTS.md) written by
setup_review_workspace.py.  This module only builds the *task* prompt
that tells the agent which PR to review and what output format to use.
"""


def build_review_prompt(pr_number: int, repo: str) -> str:
    """Build a task-oriented review prompt.

    Instead of embedding the full diff in the prompt, we tell QwenPaw
    to fetch the PR data itself using ``gh`` CLI commands.

    Args:
        pr_number: The pull request number to review.
        repo: The full repository name (owner/repo).
    """
    return f"""\
请对 **{repo}** 仓库的 **PR #{pr_number}** 进行全面但精准的代码审查。

## 第一步：获取 PR 信息

请使用以下命令自行获取 PR 数据：

1. 获取 PR 元信息：
   `gh pr view {pr_number} --repo {repo} --json \
number,title,body,author,baseRefName,headRefName,\
additions,deletions,files`

2. 获取完整 diff：
   `gh pr diff {pr_number} --repo {repo}`

## 第二步：分析与审查

根据 AGENTS.md 中的审查方法论，对获取到的 diff 进行逐维度分析。

## 第三步：输出审查报告

请严格按以下结构输出：

### 1. 概览

| 项目 | 内容 |
|------|------|
| PR 编号 | （从 gh 获取） |
| 作者 | （从 gh 获取） |
| 修改量 | （从 gh 获取） |
| 合并目标 | （从 gh 获取） |
| 关联 Issue | （从 PR body 中提取，如有） |

### 2. 问题背景

描述这个 PR 要解决的问题和动机。

### 3. 本次修改的核心内容

总结 PR 做了哪几件事（列表形式）。

### 4. 优点

列出做得好的地方，具体到文件和代码细节/设计决策。

### 5. 问题和建议

按严重度分级输出：

#### 高 (High)
#### 中等 (Medium)
#### 低 (Low)

每个问题包含：
- **引用代码**：展示问题所在的代码片段
- **问题说明**：解释为什么这是问题

如果该级别没有问题，写"无"。

### 6. 总结

- 一句话定性评价
- 合并前必须处理的 N 件事（如有）
- 可以 follow-up 的事项

最后，输出一个 JSON 代码块表示结论（注意包含各级别问题数量）：

```json
{{
  "verdict": "APPROVE 或 REQUEST_CHANGES",
  "high_count": 0,
  "medium_count": 0,
  "low_count": 0,
  "summary": "一句话总结审查结论"
}}
```

其中 `high_count`、`medium_count`、`low_count` 分别是高/中/低级别问题的数量。

## 关键原则提醒

- **聚焦变更**：只审查 diff 涉及的代码
- **区分阻塞和建议**：明确哪些必须改、哪些后续改
- **给出具体方案**：每个问题附带改进代码示例
- **承认优点**：好的设计要明确肯定
- **不做假设**：不确定的地方用"建议确认"
"""
