# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Dream memory optimization prompts."""


# Memory guidance prompts - explains how agent should use memory files
MEMORY_GUIDANCE_ZH_TEMPLATE = """\
## 记忆

每次会话都是全新的；工作目录下的文件是你的记忆延续。

- **MEMORY.md** — 长期记忆：持久的事实、偏好与决策。这是你精选、提炼的记忆（不是原始日志）；后台有一个定期运行的总结进程（dream），会自动把每日笔记里值得长期保留的内容整理进来。
- **每日笔记**（`{daily_dir}/YYYY-MM-DD.md`）— 运行中的上下文与观察；这是轻量的短期记录，也是上述总结进程的来源。
- **重要：** 避免覆盖 — 先 `read_file`，再用 `write_file` / `edit_file`。除非用户明确要求，否则不要记录敏感信息。

因此你通常不必手动维护 MEMORY.md。只有当用户明确要求你记住某事，或形成了值得长期保留的决策或偏好时，才直接编辑它。

### 🔍 检索工具
`memory_search` 用于查你**精选的长期记忆** — 持久的偏好、用户/画像事实、已确定的决策与未完成的待办。当问题取决于这些内容时，优先用它：
1. 对 MEMORY.md 和 `{daily_dir}/*.md` 运行 `memory_search`
2. 要读某一天的笔记，直接用 `read_file` 打开 `{daily_dir}/YYYY-MM-DD.md`
"""

MEMORY_GUIDANCE_EN_TEMPLATE = """\
## Memory

Each session is fresh; the working-directory files are your memory continuity.

- **MEMORY.md** — long-term memory: durable facts, preferences, and decisions. Your curated, distilled memory (not a raw log); a background summarization job (the periodic "dream" process) automatically consolidates worthwhile daily-note content into it.
- **Daily notes** (`{daily_dir}/YYYY-MM-DD.md`) — running context and observations; the lightweight short-term log that the summarization job draws from.
- **Important:** Avoid overwriting — `read_file` first, then `write_file` / `edit_file`. Unless the user explicitly asks, do not record sensitive information.

So you usually don't need to maintain MEMORY.md by hand. Edit it directly only when the user explicitly asks you to remember something, or a decision or preference worth keeping long-term is settled.

### 🔍 Retrieval Tool
`memory_search` is your lookup for **curated long-term memory** — durable preferences, profile/personal facts, settled decisions, and open to-dos. Reach for it first when a question turns on one of these:
1. Run `memory_search` over MEMORY.md and `{daily_dir}/*.md`.
2. To read a specific day's notes, open `{daily_dir}/YYYY-MM-DD.md` directly with `read_file`."""

MEMORY_GUIDANCE_TEMPLATES = {
    "zh": MEMORY_GUIDANCE_ZH_TEMPLATE,
    "en": MEMORY_GUIDANCE_EN_TEMPLATE,
}


def build_memory_guidance_prompt(
    language: str = "zh",
    *,
    daily_dir: str,
) -> str:
    """Build memory guidance using the configured daily memory directory."""
    return MEMORY_GUIDANCE_TEMPLATES.get(
        language,
        MEMORY_GUIDANCE_EN_TEMPLATE,
    ).format(daily_dir=daily_dir)
