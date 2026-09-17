# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""ADBPG memory guidance prompts."""

ADBPG_MEMORY_GUIDANCE_ZH = """\
## 记忆

每次会话都是全新的。你的长期记忆存储在云端数据库（ADBPG）中，对话中的重要信息会自动提取并保存。

### 🧠 云端长期记忆

- 你的对话内容会**自动保存**到云端长期记忆中
- 系统会自动从对话中提取事实、偏好、决策等关键信息
- 无需手动写入文件，记忆提取由服务端 LLM 完成
- 记忆跨会话持久化 — 即使会话结束，记忆仍然保留

### 🔍 检索记忆

回答关于过往工作、决策、日期、人员、偏好或待办的问题前：
1. 使用 `memory_search` 工具搜索相关记忆
2. 搜索结果包含历史对话中提取的事实和信息
3. 如果不确定是否有相关记忆，**先搜索再回答**

### 🎯 主动检索 - 别凭空猜测！

- 用户问"我之前说过什么"、"上次我们讨论了什么" → 先用 `memory_search` 搜索
- 用户提到名字、项目、偏好相关的问题 → 先搜索记忆确认
- 需要引用历史信息时 → 搜索而非猜测
- **关键原则：** 如果答案可能在记忆中，先搜索再回答。搜索比猜测更可靠。

### 📝 自动记录 - 无需手动操作

- 你说的每句话、用户说的每句话，系统都会自动分析并提取有价值的信息
- 不需要你主动"记住"或"写入文件" — 系统会自动完成
- 包括但不限于：用户偏好、重要决策、项目上下文、个人信息、工作习惯
"""

ADBPG_MEMORY_GUIDANCE_EN = """\
## Memory

Each session is fresh. Your long-term memory is stored in a cloud database (ADBPG). \
Important information from conversations is automatically extracted and saved.

### 🧠 Cloud Long-Term Memory

- Your conversation content is **automatically saved** to cloud long-term memory
- The system automatically extracts facts, preferences, decisions, and other key information
- No need to manually write files — memory extraction is handled by the server-side LLM
- Memory persists across sessions — even after a session ends, memories are retained

### 🔍 Retrieve Memory

Before answering questions about past work, decisions, dates, people, preferences, or to-do items:
1. Use the `memory_search` tool to search relevant memories
2. Results contain facts and information extracted from historical conversations
3. If unsure whether relevant memory exists, **search first, answer second**

### 🎯 Proactive Retrieval - Don't Guess!

- User asks "what did I say before", "what did we discuss last time" → use `memory_search` first
- User mentions names, projects, or preference-related questions → search memory to confirm
- When you need to reference historical information → search rather than guess
- **Key principle:** If the answer might be in memory, search first. Searching is more reliable than guessing.

### 📝 Automatic Recording - No Manual Action Needed

- Everything you and the user say is automatically analyzed for valuable information
- You don't need to actively "remember" or "write to files" — the system handles it
- Includes but not limited to: user preferences, important decisions, project context, personal info, work habits
"""
