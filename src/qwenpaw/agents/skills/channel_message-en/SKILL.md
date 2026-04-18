---
name: channel_message
description: Use this skill to proactively send a one-way message to a user/session/channel, usually only when the user explicitly asks to send to a channel/session or when proactive notification is needed. First query sessions with qwenpaw chats list, then push with qwenpaw channels send.
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "📤"
---

# Channel Message

## When to Use

Use this skill only when the **user explicitly asks you to send a message to a channel/session**, or when you need to **proactively push a notification** (e.g., task completion, reminders, alerts).
This is a **one-way send** — **no reply is returned**.

### Should Use
- The user explicitly asks to send to a specific channel/session
- Proactively notifying the user after a task completes
- Scheduled reminders, alerts, or status updates
- Pushing async results back to an existing session
- The user explicitly says "notify me when done"

### Should Not Use
- If you are simply replying in the current session, **do not use `qwenpaw channels send`**
- You need a two-way conversation and expect an immediate reply
- You do not know which target session to use
- You are guessing `target-user` or `target-session`

## Decision Rules

1. **Only use this when the user explicitly asks to send to a channel/session, or proactive notification is needed**
2. **You must query sessions before sending**
3. **Do not guess `target-user` or `target-session`**
4. **If multiple sessions are found, prefer the most recently active one**
5. **`channel send` is a one-way push — no user reply is returned**

---

## Most Common Commands

### 1) Query available sessions first

```bash
qwenpaw chats list --agent-id <your_agent> --channel <channel>
```

You can also filter by user:

```bash
qwenpaw chats list --agent-id <your_agent> --user-id <user_id>
```

### 2) Send a message

```bash
qwenpaw channels send \
  --agent-id <your_agent> \
  --channel <channel> \
  --target-user <user_id> \
  --target-session <session_id> \
  --text "..."
```

---

## Minimal Workflow

```
1. Determine: is the user explicitly requesting a send, or is proactive notification needed?
2. qwenpaw chats list — query the target session
3. Extract user_id and session_id from the results
4. If multiple sessions exist, prefer the most recently active one
5. qwenpaw channels send — send the message
6. Done (no reply)
```

---

## Key Rules

### Required Parameters

`qwenpaw channels send` requires all of the following:
- `--agent-id`
- `--channel`
- `--target-user`
- `--target-session`
- `--text`

### Must Query First

Before sending, run:

```bash
qwenpaw chats list --agent-id <your_agent> --channel <channel>
```

Extract from the results:
- `user_id` → `--target-user`
- `session_id` → `--target-session`

If there are multiple candidate sessions, prefer the one with the most recent `updated_at`.

### One-Way Push

`qwenpaw channels send` only sends — it does not wait for a reply.

---

## Brief Examples

### User explicitly asks to send to a channel

```bash
qwenpaw chats list --agent-id notify_bot --channel feishu

qwenpaw channels send \
  --agent-id notify_bot \
  --channel feishu \
  --target-user manager_id \
  --target-session manager_session \
  --text "Weekly report is ready, please review"
```

### Task completion notification

```bash
qwenpaw chats list --agent-id task_bot --channel console

qwenpaw channels send \
  --agent-id task_bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "Task completed"
```

### Async result push-back

```bash
qwenpaw chats list --agent-id analyst_bot --user-id alice

qwenpaw channels send \
  --agent-id analyst_bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "Data analysis is complete. Results saved to report.pdf"
```

---

## Common Mistakes

### Mistake 1: Using channel send for a normal reply

If you are replying to the user in the current session, do not use `qwenpaw channels send`.

### Mistake 2: Sending without querying sessions first

Do not guess `target-user` or `target-session`. First run:

```bash
qwenpaw chats list --agent-id <your_agent> --channel <channel>
```

### Mistake 3: Missing required parameters

All five are required: `--agent-id`, `--channel`, `--target-user`, `--target-session`, `--text`.

### Mistake 4: Expecting a reply from send

There is no reply. It only pushes the message.

### Mistake 5: Picking an arbitrary session when the user has multiple

Prefer the most recently active session.

---

## Optional Commands

### List all sessions

```bash
qwenpaw chats list --agent-id <your_agent>
```

### List sessions for a specific user

```bash
qwenpaw chats list --agent-id <your_agent> --user-id <user_id>
```

### List available channels

```bash
qwenpaw channels list --agent-id <your_agent>
```

---

## Difference from Agent Chat

- **qwenpaw agents chat**: sends to another agent, two-way, returns a reply
- **qwenpaw channels send**: sends to a user/session/channel, one-way, no reply

**Selection principle**:
- Need to collaborate with another agent → `qwenpaw agents chat`
- Need to proactively push a message to a user → `qwenpaw channels send`

---

## Full Parameter Reference

### qwenpaw chats list

**Required parameters**:
- `--agent-id`: Agent ID

**Optional parameters**:
- `--channel`: filter by channel
- `--user-id`: filter by user
- `--base-url`: override API address

### qwenpaw channels send

**Required parameters** (5):
- `--agent-id`: sender agent ID
- `--channel`: target channel (console/dingtalk/feishu/discord/imessage/qq/...)
- `--target-user`: target user ID (obtained from `qwenpaw chats list`)
- `--target-session`: target session ID (obtained from `qwenpaw chats list`)
- `--text`: message content

**Optional parameters**:
- `--base-url`: override API address

---

## Help

Use `-h` at any time to view detailed help:

```bash
qwenpaw channels -h
qwenpaw channels send -h
qwenpaw chats -h
qwenpaw chats list -h
```
