---
name: multi_agent_collaboration
description: Use this skill when another agent's expertise or context is needed, or when the user explicitly asks to involve another agent. First list agents, then use qwenpaw agents chat for two-way communication with replies.
metadata:
  builtin_skill_version: "1.4"
  qwenpaw:
    emoji: "🤝"
---

# Multi-Agent Collaboration

## When to Use

Use this skill when you **need another agent's expertise, context, workspace content, or collaborative support**.
If the **user explicitly asks a specific agent to participate/assist/answer**, you should also use this skill.

### Should Use
- The current task is clearly better suited for a specialized agent
- You need another agent's workspace / files / context
- You need a second opinion or expert review
- The user explicitly asks for a specific agent to participate or to invoke another agent

### Should Not Use
- You can complete the task on your own and the user has not explicitly asked to invoke another agent
- It is just a normal Q&A that does not require a specialized agent
- Information is insufficient -- you should ask the user for clarification first
- You just received a message from Agent B -- **do not call Agent B again** to avoid loops

## Decision Rules

1. **If the user explicitly requests invoking another agent, prioritize following the request**
2. **Otherwise, if you can do it yourself, do not invoke another agent**
3. **Check agents before invoking -- do not guess IDs**
4. **When context continuation is needed, you must pass `--session-id`**
5. **Do not call back the source agent**

---

## Most Common Commands

### 1) First Query Available Agents

```bash
qwenpaw agents list
```

### 2) Start a New Conversation (Real-time Mode)

```bash
qwenpaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --text "[Agent <your_agent> requesting] ..."
```

### 3) Submit a Complex Task (Background Mode)

**Complex tasks** include: data analysis, report generation, batch processing, external API calls, etc.

```bash
qwenpaw agents chat --background \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --text "[Agent <your_agent> requesting] ..."
```

**Output**:
```
[TASK_ID: xxx-xxx-xxx]
[SESSION: ...]
```

### 4) Query Background Task Status

```bash
qwenpaw agents chat --background --task-id <task_id>
```

**Important**: Do not query frequently! After submitting a task:
1. **Do not block** - Continue handling other tasks or work
2. **Wait a reasonable time before querying** - Choose based on task complexity:
   - Simple analysis: query after 10-20 seconds
   - Complex analysis: query after 30-60 seconds
   - Batch processing: query after 1-3 minutes
3. **During the wait** - You can reply to the user, handle other requests, or execute other tasks

### 5) Continue an Existing Conversation

```bash
qwenpaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --session-id "<session_id>" \
  --text "[Agent <your_agent> requesting] ..."
```

**Key points**:
- Not passing `--session-id` = new conversation
- Passing `--session-id` = continue conversation (context preserved)
- Use `--background` for complex tasks; record the task_id after submission

---

## Task Mode Selection

### Real-time Mode vs Background Mode

| Task Type | Mode to Use | Command |
|-----------|-------------|---------|
| Simple quick query | Real-time mode | `qwenpaw agents chat` |
| Complex task (data analysis, batch processing, etc.) | Background mode | `qwenpaw agents chat --background` |

**Examples of complex tasks**:
- Analyzing large amounts of data or log files
- Generating detailed reports
- Batch processing files (10+ files)
- Calling slow external APIs
- Independent tasks that need parallel execution

**Decision criteria**: If you are unsure how long a task will take, or if the task is complex, prefer background mode.

---

## Minimal Workflow

### Real-time Mode Workflow

```
1. Determine whether another agent is needed, or whether the user explicitly requested it
2. qwenpaw agents list
3. qwenpaw agents chat to start a conversation
4. Record [SESSION: ...] from the output
5. Include --session-id when context continuation is needed later
```

### Background Mode Workflow

```
1. Determine whether the task is complex (data analysis, report generation, etc.)
2. qwenpaw agents list
3. qwenpaw agents chat --background to submit the task
4. Record [TASK_ID: ...] from the output
5. Continue handling other work
6. Wait a reasonable time (30-60 seconds) before querying status
7. Use --background --task-id to query results
```

---

## Key Rules

### Required Parameters

`qwenpaw agents chat` must include all of the following:
- `--from-agent`
- `--to-agent`
- `--text`

### Identity Prefix

Messages should begin with the following prefix:

```text
[Agent my_agent requesting] ...
```

### Session Reuse

The first call will return:

```text
[SESSION: your_agent:to:target_agent:...]
```

For subsequent follow-ups, you must copy this session_id and pass it via `--session-id`.

---

## Brief Examples

### User Explicitly Requests Invoking Another Agent

```bash
qwenpaw agents list

qwenpaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --text "[Agent scheduler_bot requesting] User explicitly asked to consult finance_bot. Please answer what pending financial tasks are there."
```

### New Conversation

```bash
qwenpaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --text "[Agent scheduler_bot requesting] What pending financial tasks are there today?"
```

### Continue Conversation

```bash
qwenpaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --session-id "scheduler_bot:to:finance_bot:1710912345:a1b2c3d4" \
  --text "[Agent scheduler_bot requesting] Expand on item 2"
```

---

## Common Mistakes

### Mistake 1: Not checking agents first

Do not guess agent IDs. First run:

```bash
qwenpaw agents list
```

### Mistake 2: Wanting to continue a conversation but not passing session-id

This will create a new conversation, losing context.

### Mistake 3: Calling back the source agent

If you just received a message from Agent B, do not call Agent B again.

---

## Optional Commands

### View Existing Sessions

```bash
qwenpaw chats list --agent-id <your_agent>
```

### Streaming Output

```bash
qwenpaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --mode stream \
  --text "[Agent <your_agent> requesting] ..."
```

### JSON Output

```bash
qwenpaw agents chat \
  --from-agent <your_agent> \
  --to-agent <target_agent> \
  --json-output \
  --text "[Agent <your_agent> requesting] ..."
```

---

## Full Parameter Reference

### qwenpaw agents list

**Parameters**:
- `--base-url` (optional): Override the API address

**No required parameters** -- just run it directly.

### qwenpaw agents chat

**Required parameters** (real-time mode):
- `--from-agent`: Sender agent ID
- `--to-agent`: Target agent ID
- `--text`: Message content

**Background task parameters**:
- `--background`: Background task mode
- `--task-id`: Query task status (used together with --background)

**Optional parameters**:
- `--session-id`: Reuse session context (copy from previous output)
- `--new-session`: Force create a new session (even if session-id is passed)
- `--mode`: stream (streaming) or final (complete, default)
- `--timeout`: Timeout in seconds (default 300)
- `--json-output`: Output full JSON instead of plain text
- `--base-url`: Override the API address

---

## Background Task Mode Details

### When to Use Background Mode?

When the task is a **complex task**, use `--background` to submit it to the background:

**Should use background mode**:
- Data analysis (analyzing logs, computing statistics)
- Report generation (generating long reports or documents)
- Batch processing (processing multiple files)
- External API calls (calling slow services)
- Complex tasks with uncertain duration

**Does not need background mode**:
- Simple quick queries
- Tasks that are clearly going to complete quickly

### Background Task Examples

#### Submitting a Complex Task

```bash
qwenpaw agents chat --background \
  --from-agent scheduler \
  --to-agent data_analyst \
  --text "[Agent scheduler requesting] Analyze user behavior in /data/logs/2026-03-26.log and generate a detailed report"
```

**Output**:
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[SESSION: scheduler:to:data_analyst:1774516703206:ec02e542]

✅ Task submitted successfully

Check status with:
  qwenpaw agents chat --background --task-id 20802ea3-...
```

#### Querying Task Status

**Important**: Do not block after submitting!

1. **Continue handling other work** - Reply to other user questions, execute other tasks
2. **Query at the right time** - After finishing other work, or when the user asks about progress
3. **If you must wait** - Use a reasonable interval (10-60 seconds); do not query immediately

```bash
# Method 1: Query after handling other tasks (recommended)
# After submitting the task, continue with the user's other requests
# Query at an appropriate time:
qwenpaw agents chat --background \
  --task-id 20802ea3-832d-4fb4-86f0-666ad79fcc80

# Method 2: If you must wait, use a reasonable interval
sleep 30 && qwenpaw agents chat --background \
  --task-id 20802ea3-832d-4fb4-86f0-666ad79fcc80
```

**Status Descriptions**:

Task status has two layers:
- **Outer status** (API response): `submitted` -> `pending` -> `running` -> `finished`
- **Inner status** (only when outer status is `finished`): `completed` (success) or `failed` (failure)

**Possible outputs**:

1. **Submitted** (may be seen when querying immediately after submission):
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: submitted]

📤 Task submitted, waiting to start...

💡 Don't wait - continue with other work!
   Check again in a few seconds:
  qwenpaw agents chat --background --task-id 20802ea3-...
```

2. **Pending**:
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: pending]

⏸️  Task is pending in queue...

💡 Don't wait - handle other work first!
   Check again in a few seconds:
  qwenpaw agents chat --background --task-id 20802ea3-...
```

4. **Running**:
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: running]

⏳ Task is still running...
   Started at: 1774516703

💡 Don't wait - continue with other tasks first!
   Check again later (10-30s):
  qwenpaw agents chat --background --task-id 20802ea3-...
```

5. **Completed successfully**:
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: finished]

✅ Task completed

(Task result content...)
```

6. **Failed**:
```
[TASK_ID: 20802ea3-832d-4fb4-86f0-666ad79fcc80]
[STATUS: finished]

❌ Task failed

Error: (Error message...)
```

### Query Interval Strategy

**Do not query frequently!** After submitting a task, you should:

1. **Continue handling other work** - Do not block; go complete other tasks
2. **Wait a reasonable time before querying** - Choose the interval based on task complexity
3. **Avoid blocking the current flow** - This is the core value of background tasks

| Task Type | Suggested First Query | Subsequent Interval | What to Do While Waiting |
|-----------|----------------------|--------------------|-----------------------|
| Simple analysis | After 10 seconds | 5-10 seconds | Handle other user requests |
| Complex analysis | After 30 seconds | 10-20 seconds | Complete other parts of the current conversation |
| Batch processing | After 1 minute | 20-30 seconds | Execute other independent tasks |
| Very large tasks | After 2 minutes | 30-60 seconds | Continue with the user's other work |

#### Recommended Approach

**Method 1: Query after handling other tasks** (recommended)
```bash
# 1. Submit the task, record the task_id
qwenpaw agents chat --background ...
# Returns task_id

# 2. Continue handling the user's other requests or tasks
# (e.g., answer other questions, perform other operations)

# 3. Query the result at an appropriate time
# (e.g., after finishing the current task, or when the user asks about progress)
qwenpaw agents chat --background --task-id <id>
```

**Method 2: Timed polling** (if you must wait)
```bash
# Incrementally increasing intervals, fast first then slow
sleep 10 && qwenpaw agents chat --background --task-id <id>
sleep 20 && qwenpaw agents chat --background --task-id <id>
sleep 30 && qwenpaw agents chat --background --task-id <id>
```

#### Do Not Do This

```bash
# Wrong: querying too frequently
while true; do
    qwenpaw agents chat --background --task-id <id>
    sleep 1  # Too frequent!
done
```

---

## Help Information

Use `-h` at any time to view detailed help:

```bash
qwenpaw agents -h
qwenpaw agents list -h
qwenpaw agents chat -h
```
