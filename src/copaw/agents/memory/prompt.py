SUMMARY_USER = """
  Memory Pre-compression Flush Cycle Initiated
  The current session is about to enter the automatic compression phase. Please capture persistent memory and write it to disk.

  Current date: {date}
  Working directory: {working_dir}

  Immediately store persistent memory to: {memory_dir}/YYYY-MM-DD.md

  Workflow:
  1. First, `read` {memory_dir}/YYYY-MM-DD.md (if the file doesn’t exist, an error message will be returned).
  2. Intelligently merge new information with existing content (skip merging if the file doesn’t exist):
     - Avoid duplicating already recorded information
     - Enrich existing entries with new details where relevant
     - Maintain chronological order wherever applicable
  3. Write the updated content:
     - Prefer using `edit` to update specific sections when possible
     - Use `write` to overwrite the entire file only if substantial restructuring is required

  Principles:
  - Always preserve timestamps and any date/time-related context
  - Add only genuinely new or meaningfully enriching information
  - Keep entries concise yet complete
  - If there’s nothing to store, respond with [SILENT]
"""

SUMMARY_USER_ZH = """
  预压缩内存刷新轮次。
  当前会话即将进入自动压缩阶段；请将持久化记忆捕获并写入磁盘。

  当前日期：{date}
  工作目录：{working_dir}

  立即存储持久化记忆（使用路径 {memory_dir}/YYYY-MM-DD.md）。

  工作流程：
  1. 先 `read` {memory_dir}/YYYY-MM-DD.md（如文件不存在，会返回错误提示）
  2. 智能合并新信息与现有内容（若文件不存在则跳过合并）：
     - 避免重复已记录的信息
     - 在相关时丰富现有条目的新细节
     - 在适用时保持时间顺序
  3. 写入更新后的内容：
     - 尽可能使用 `edit` 更新特定部分
     - 如需大幅重构则使用 `write` 覆盖整个文件

  原则：
  - 始终保留时间戳、日期和时间相关上下文
  - 仅添加真正新的或有丰富价值的信息
  - 保持条目简洁但完整
  - 若无内容可存储，请回复 [SILENT]
"""

COMPACT_SYSTEM = """
  You are a context compaction assistant. Your role is to create structured summaries of conversations
  that can be used to restore context in future sessions. Focus on preserving critical information while reducing token count.
"""

COMPACT_SYSTEM_ZH = """
  你是一个上下文压缩助手。你的角色是创建对话的结构化摘要，
  这些摘要可以在未来会话中用于恢复上下文。专注于保留关键信息，同时减少token数量。
"""

INITIAL_USER = """
  The messages above are a conversation to summarize. Create a structured context checkpoint summary
  that another LLM will use to continue the work.

  Use this EXACT format:

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

  Keep each section concise. Preserve exact file paths, function names, and error messages.
"""

INITIAL_USER_ZH = """
  上述消息是一场需要总结的对话。创建一个结构化的上下文检查点摘要，
  以便另一个LLM可以用来继续工作。

  使用此确切格式：

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

  保持每个部分简洁。保留确切的文件路径、函数名称和错误消息。
"""

UPDATE_USER = """
  The messages above are NEW conversation messages to incorporate into the existing summary provided in
  <previous-summary> tags.

  <previous-summary>
  {previous_summary}
  </previous-summary>

  Update the existing structured summary with new information. RULES:
  - PRESERVE all existing information from the previous summary
  - ADD new progress, decisions, and context from the new messages
  - UPDATE the Progress section: move items from "In Progress" to "Done" when completed
  - UPDATE "Next Steps" based on what was accomplished
  - PRESERVE exact file paths, function names, and error messages
  - If something is no longer relevant, you may remove it

  Use this EXACT format:

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

  Keep each section concise. Preserve exact file paths, function names, and error messages.
"""

UPDATE_USER_ZH = """
  上述消息是要整合到现有摘要中的新对话消息，这些消息在<previous-summary>标签中提供。

  <previous-summary>
  {previous_summary}
  </previous-summary>

  用新信息更新现有的结构化摘要。规则：
  - 保留来自先前摘要的所有现有信息
  - 从新消息中添加新的进展、决策和上下文
  - 更新进度部分：当完成时将项目从"进行中"移到"已完成"
  - 根据已完成的内容更新"下一步"
  - 保留确切的文件路径、函数名称和错误消息
  - 如果某些内容不再相关，您可以删除它

  使用此确切格式：

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

  ## 下一步
  1. [根据当前状态更新]

  ## 关键上下文
  - [保留重要上下文，如需要则添加新的]

  保持每个部分简洁。保留确切的文件路径、函数名称和错误消息。
"""
