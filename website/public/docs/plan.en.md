# Plan Mode

**Plan mode** helps the agent break complex requests into **trackable steps**: it builds a structured plan with **subtasks**, waits for your confirmation before execution, and shows live progress in the console sidebar.

Plan mode is **off by default**; only agents that have it enabled will load plan-related functionality in chat.

> Introduced as an opt-in feature in **v1.1.4**.

If you haven't read [Introduction](./intro) yet, skim the notes there on agents and the console first.

---

## What plan mode provides

| Capability                   | Description                                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **Structured decomposition** | Splits the user request into ordered subtasks, each with a name, description, and measurable expected outcome |
| **Human-in-the-loop**        | After creating or revising a plan, the agent presents it and waits before executing subtasks                  |
| **State tracking**           | Both the overall plan and each subtask have states (todo / in_progress / done / abandoned)                    |
| **Visualization**            | When enabled, the chat page can open a **Plan** drawer for live plan and subtask progress                     |

---

## Step 1: Enable plan mode

### In the console (recommended)

1. Open the [Console](./console) and switch to the target agent.
2. Go to **Settings -> Agents** and expand that agent's configuration card (React Agent card).
3. Toggle **Plan Mode** on.

The setting is saved to `plan.enabled` in that agent's `agent.json` workspace file.

### Edit `agent.json` directly

In `$QWENPAW_WORKING_DIR/workspaces/<agent_id>/agent.json`:

```json
{
  "plan": {
    "enabled": true
  }
}
```

Save the file; the next request picks up the new value (restart or refresh if your deployment requires it).

For the full list of configuration fields, see [Config & working dir](./config).

---

## Step 2: Start a structured task

With plan mode enabled, send:

```
/plan <short description of what you want>
```

**Example:**

```
/plan Tidy up the project README and API docs — fill in missing sections and fix broken links
```

What happens:

1. **Prefix stripped** — The model receives only your description as the user message, keeping the task intent clear.
2. **Plan first** — This turn requires the model to call `create_plan` before using any other tools, so execution doesn't run ahead of the plan.
3. **Wait for confirmation** — After creating the plan, the agent presents it and waits for your go-ahead. You can:
   - Confirm (e.g. "go ahead", "start", "ok") — the agent begins the first subtask
   - Request changes — the agent revises or rebuilds the plan and asks again
   - Cancel — the agent abandons the plan

> If plan mode is on but you don't use the `/plan` prefix, everyday chat is unaffected. The "plan first" flow only triggers when you explicitly send `/plan`.

---

## Execution flow

Once you confirm, the agent works through subtasks in order, calling the appropriate tools for each one:

1. The first subtask is marked **in_progress** and execution begins
2. Each turn advances the subtask with tool calls; when done, the outcome is recorded and the subtask is marked **done**
3. The agent automatically moves to the next subtask until all are finished
4. The overall plan is then marked **done**

Notes:

- **Minor revisions** — If small tweaks are needed mid-execution (e.g. changing a subtask description or adding a step), the agent can use `revise_current_plan`. After revising it presents the updated plan and waits for confirmation again.
- **Full rewrites** — If you ask to throw the plan away and start over, the agent abandons the current plan and builds a fresh one rather than revising repeatedly.
- **Tool calls required** — Each turn, prompts remind the agent to include at least one tool call so the ReAct loop keeps moving.

---

## Subtask states

Plans and subtasks share the same state values:

| State           | Meaning                  |
| --------------- | ------------------------ |
| **todo**        | Not started              |
| **in_progress** | Currently being executed |
| **done**        | Completed successfully   |
| **abandoned**   | Stopped / discarded      |

The Plan drawer's progress bar counts both **done** and **abandoned** subtasks toward the numerator.

---

## Plan drawer in the console

When plan mode is enabled, the chat toolbar shows a **Plan** icon. Opening it reveals a right-hand drawer with:

- Plan title, description, and overall state
- Subtasks (name, description, state, optional outcome)
- An overall progress bar

The drawer receives plan changes via **SSE (server-sent events)** in real time, with a polling fallback every ~5 seconds in case an event is missed. If the panel looks empty, close it and reopen to trigger a fresh fetch.

---

## Plan state and conversation context

- Plan state is persisted as part of the session, so an unfinished plan can resume within the same conversation.
- Running [magic commands](./commands) that reset the conversation — `/clear` or `/new` — also clears the plan state. The console Plan drawer updates to empty accordingly.

---

## Compared with regular chat

| Scenario                              | Behavior                                                                                            |
| ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Plan mode on, no `/plan` prefix       | Normal chat — no forced "must plan first" for every message                                         |
| User sends `/plan ...`                | "Plan first" flow: plan must be created and confirmed before execution                              |
| A plan just finished or was cancelled | The agent responds to the **latest user message** directly, or starts a new plan if you ask for one |

This means the same agent works for both occasional structured tasks and everyday quick questions.

---

## Related pages

- [Introduction](./intro) — What the project can do
- [Console](./console) — Web UI and agent switching
- [Magic commands](./commands) — `/plan`, `/clear`, `/new`, and more
- [Config & working dir](./config) — `agent.json` and the `plan` field
- [RESTful API](./api-tutorial) — Query and control plan state via API
