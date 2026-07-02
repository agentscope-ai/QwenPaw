# -*- coding: utf-8 -*-
"""Review prompt templates for QwenPaw AI Review Bot.

Customize HERE: Modify this file to change how reviews work.
"""
import re


def build_review_prompt(meta: dict, diff: str) -> str:
    """Build the full review prompt from PR metadata and diff.

    Args:
        meta: PR metadata dict with keys:
            number, title, body, author, base, head,
            file_count, additions, deletions, changed_files
        diff: The full diff text (may be truncated)
    """
    changed_files_list = "\n".join(
        f"  - {f}" for f in meta.get("changed_files", [])[:30]
    )

    # Build PR link if repo info available
    repo = meta.get("repo", "")
    pr_link = (
        f"https://github.com/{repo}/pull/{meta['number']}"
        if repo
        else f"PR #{meta['number']}"
    )

    return f"""\
请对以下 Pull Request 进行全面但精准的代码审查。

---

## PR 信息

| 项目 | 内容 |
|------|------|
| PR | [{pr_link}]({pr_link}) |
| 标题 | {meta['title']} |
| 作者 | @{meta['author']} |
| 分支 | `{meta['head']}` → `{meta['base']}` |
| 修改量 | {meta['file_count']} 个文件, +{meta['additions']}/-{meta['deletions']} 行 |
| 关联 Issue | {_extract_issue_ref(meta.get('body', ''))} |

## PR 描述（作者写的）

{meta.get('body') or '（无描述）'}

## 涉及的文件

{changed_files_list}

## 代码变更（Diff）

{diff}

---

# 审查指令

## 阶段一：逐维度分析

按以下维度审查（根据改动范围选择相关维度，小 fix 可能只需要 1、4、7）：

| # | 维度 | 核心检查项 |
|---|------|-----------|
| 1 | 正确性 | 逻辑是否正确？边界条件？空值/None？类型匹配？并发安全？跨平台兼容（路径、换行符、编码）？ |
| 2 | 安全性 | 注入漏洞、path traversal、权限绕过、密钥泄露、不安全依赖？ |
| 3 | 一致性 | 与项目已有风格/模式一致？API 设计对齐？ |
| 4 | 健壮性 | 错误处理完整？异常路径覆盖？异常处理粒度？ |
| 5 | 可维护性 | 命名清晰？逻辑复杂度？重复代码？必要注释？ |
| 6 | 性能 | 不必要开销？热路径重复计算？同步 IO/网络调用阻塞异步事件循环？ |
| 7 | 国际化 | 涉及 i18n 时所有语言是否同步？翻译准确？ |
| 8 | CI/CD | 涉及 workflow 时是否安全？secrets 处理？ |

**只报告真正的问题**，不要为了凑数而写无意义的建议。\
未涉及的维度不需要输出。

## 阶段二：问题分级

**高 (High) — 合并前必须修复：**
- 安全漏洞（注入、越权、密钥泄露）
- 数据丢失或损坏风险
- 逻辑错误（会导致功能不正确）
- 未处理的 breaking change

**中等 (Medium) — 建议合并前修复，可讨论：**
- 边界条件缺失（不常见但可触发）
- API 不一致或设计不合理
- 性能问题（非热路径可降为低）
- 正确但有更好做法的实现

**低 (Low) — 可以合并后 follow-up：**
- 代码风格 / 命名优化
- 注释缺失
- PR 描述 / commit message 不规范
- 无关变更混入
- 文档缺失

## 阶段三：生成审查文档

请严格按以下结构输出：

### 1. 概览

| 项目 | 内容 |
|------|------|
| PR 编号 | #{meta['number']} |
| 作者 | @{meta['author']} |
| 修改量 | {meta['file_count']} 文件, +{meta['additions']}/-{meta['deletions']} |
| 合并目标 | {meta['base']} |
| 关联 Issue | （如有） |

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

最后，输出一个 JSON 代码块表示结论：

```json
{{"verdict": "APPROVE 或 REQUEST_CHANGES", "summary": "一句话总结审查结论"}}
```

---

## 判断标准

- **APPROVE**: 没有 High 级问题，代码质量可接受，可以合并
- **REQUEST_CHANGES**: 存在 High 级问题（安全漏洞、明显 bug、\
严重设计缺陷、breaking change 未处理）

**注意：** 风格偏好、可选优化（Medium/Low）\
不应作为 REQUEST_CHANGES 的理由。\
只有真正影响功能、安全或可靠性的问题才应该阻止合并。

## 关键原则提醒

- **聚焦变更**：只审查 diff 涉及的代码
- **区分阻塞和建议**：明确哪些必须改、哪些后续改
- **给出具体方案**：每个问题附带改进代码示例
- **承认优点**：好的设计要明确肯定
- **不做假设**：不确定的地方用"建议确认"
"""


def _extract_issue_ref(body: str) -> str:
    """Extract issue references from PR body text."""
    if not body:
        return "未填写"

    patterns = [
        r"[Ff]ixes?\s+#(\d+)",
        r"[Cc]loses?\s+#(\d+)",
        r"[Rr]elates?\s+to\s+#(\d+)",
        r"[Rr]elated\s+[Ii]ssue.*?#(\d+)",
    ]
    refs = []
    for pattern in patterns:
        matches = re.findall(pattern, body)
        refs.extend(f"#{m}" for m in matches)
    return ", ".join(refs) if refs else "未填写"
