# -*- coding: utf-8 -*-
"""Memory guidance prompts."""

MEMORY_GUIDANCE = {
    "zh": (
        "# 长期记忆\n\n"
        "工作目录下保存着你的个人知识库。当问题涉及用户过去的事实、偏好、"
        "决策或经验时，先使用 `memory_search` 检索相关信息。检索结果中会包含"
        "相关内容片段及其文件路径；如果片段不足以回答问题，再使用 `read_file` "
        "按路径渐进式展开，只读取当前任务所需的内容。"
    ),
    "en": (
        "# Long-term Memory\n\n"
        "Your personal knowledge base is stored in the working directory. "
        "When a question involves the user's past facts, preferences, "
        "decisions, or experience, first use `memory_search` to retrieve "
        "relevant information. Search results include relevant excerpts and "
        "their file paths; if an excerpt is insufficient, use `read_file` on "
        "its path to progressively expand the "
        "context, reading only what the current task requires."
    ),
}


def build_memory_guidance_prompt(
    language: str = "zh",
    *,
    memory_search_enabled: bool = True,
) -> str:
    """Build guidance for the memory capabilities exposed to the agent."""
    if not memory_search_enabled:
        return ""
    return MEMORY_GUIDANCE.get(language, MEMORY_GUIDANCE["en"])
