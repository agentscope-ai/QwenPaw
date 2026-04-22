---
name: task_progress
description: Use this skill when you need to check the detailed progress of a background task, especially when you want to know what subtask an agent is currently working on.
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "📋"
---

# Task Progress Tracking

## When to Use

Use this skill when you need to **monitor the detailed progress of a background task** that was dispatched via `submit_to_agent`. Unlike `check_agent_task` which only returns lifecycle status (running / finished), this skill provides live progress details including the current tool being executed, plan progress, and subtask status.

### Should Use

- You submitted a background task and want to know what the target agent is currently doing
- You need to track PlanNotebook subtask progress (which subtask is in_progress, how many are done)
- You want to see the last tool call, its input/output, or the agent's latest reasoning
- The user asks "what is agent X doing right now?" or "how far along is the task?"

### Should Not Use

- You only need to know whether a task is finished or still running (use `check_agent_task` instead)
- You are waiting for a task result and don't need intermediate progress
- You want to interact with the target agent (use `chat_with_agent` instead)

## Instructions

### Step 1: Identify the Task

You need the `task_id` that was returned by `submit_to_agent`, and optionally the `agent_id` of the target agent.

### Step 2: Query Task Detail

Call `query_task_detail` with the task_id and agent_id:

```
query_task_detail(task_id="<task_id>", agent_id="<agent_id>")
```

### Step 3: Interpret the Result

The `live_status` field contains the progress snapshot:

- **`hook_type`**: Which hook captured this data (e.g., `post_acting`, `plan_change`)
- **`last_update`**: Unix timestamp of the last update
- **`last_tool`** / **`last_tool_input`** / **`last_tool_output`**: The most recent tool call (from `post_acting` hook)
- **`plan_name`** / **`plan_progress`** / **`current_subtask`**: Plan progress (when PlanNotebook is enabled)

### Step 4: Report to User

Summarize the progress in a human-readable format. For example:

- "Agent `qa_agent` is currently running tool `read_file` on `test_results.json`"
- "Plan `QA Pipeline` is 3/5 complete. Current subtask: `Run Integration Tests`"

## Tips

- If `live_status` is null, the target agent may not have `progress_observing` enabled in its config
- Progress is session-aware: concurrent sessions on the same agent are tracked independently
- You can call `query_task_detail` multiple times to get updates as the task progresses
