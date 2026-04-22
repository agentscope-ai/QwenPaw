---
name: task_progress
description: 当你需要查看后台任务的详细进度时使用此技能，尤其是当你想了解 agent 当前正在执行哪个子任务时。
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "📋"
---

# 任务进度追踪

## 何时使用

当你需要**监控通过 `submit_to_agent` 提交的后台任务的详细进度**时使用此技能。与只返回生命周期状态（运行中 / 已完成）的 `check_agent_task` 不同，此技能提供实时进度详情，包括当前执行的工具、计划进度和子任务状态。

### 应该使用

- 你提交了后台任务，想知道目标 agent 当前在做什么
- 你需要追踪 PlanNotebook 子任务进度（哪个子任务正在进行，完成了多少）
- 你想查看最后一次工具调用、其输入/输出，或 agent 最新的推理
- 用户问"agent X 现在在做什么？"或"任务进展到哪了？"

### 不应使用

- 你只需要知道任务是否已完成或仍在运行（改用 `check_agent_task`）
- 你在等待任务结果，不需要中间进度
- 你想与目标 agent 交互（改用 `chat_with_agent`）

## 使用说明

### 第一步：确认任务

你需要 `submit_to_agent` 返回的 `task_id`，以及可选的目标 agent 的 `agent_id`。

### 第二步：查询任务详情

使用 task_id 和 agent_id 调用 `query_task_detail`：

```
query_task_detail(task_id="<task_id>", agent_id="<agent_id>")
```

### 第三步：解读结果

`live_status` 字段包含进度快照：

- **`hook_type`**：捕获此数据的钩子类型（如 `post_acting`、`plan_change`）
- **`last_update`**：最后更新的 Unix 时间戳
- **`last_tool`** / **`last_tool_input`** / **`last_tool_output`**：最近的工具调用（来自 `post_acting` 钩子）
- **`plan_name`** / **`plan_progress`** / **`current_subtask`**：计划进度（当 PlanNotebook 启用时）

### 第四步：向用户汇报

以人类可读的格式总结进度。例如：

- "Agent `qa_agent` 当前正在对 `test_results.json` 执行 `read_file` 工具"
- "计划 `QA Pipeline` 已完成 3/5。当前子任务：`运行集成测试`"

## 提示

- 如果 `live_status` 为 null，目标 agent 可能未在配置中启用 `progress_observing`
- 进度支持会话感知：同一 agent 的并发会话会被独立追踪
- 你可以多次调用 `query_task_detail` 以获取任务进展的最新状态
