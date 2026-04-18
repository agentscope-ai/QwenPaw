---
name: chat_with_agent
description: Use this skill when you need to consult another agent, ask for help, or involve a specific agent the user asked for.
metadata:
  builtin_skill_version: "1.1"
  qwenpaw:
    emoji: "💬"
---

# Chat with Agent

## When to Use

Use this skill when you need to **ask another agent a question, seek help, request a plan, request a review, request decision support, or engage in any form of communication**.
If the **user explicitly asks to talk to a specific agent**, you should also use this skill.

### Should Use

- You need another agent's expertise, judgment, or second opinion
- You need to request a plan, review, or recommendation from an agent
- The user explicitly asks a specific agent to participate, assist, or answer
- You need to continue an existing agent session while preserving context

### Should Not Use

- You can complete the task yourself and the user has not explicitly asked to involve another agent
- It is a simple Q&A that does not require a specialized agent
- The target agent is unclear — you should ask for clarification or list available agents first
- You just received a message from an agent and are about to immediately call back the same agent, which may cause a loop

## Decision Rules

1. **If the user explicitly requests a specific agent, follow that request — but still look up the agent first; do not guess the ID**
2. **If you can complete the task yourself, do not call another agent**
3. **When continuing a conversation, you must pass `session_id`**
4. **By default, prefer using `list_agents()` and `chat_with_agent(...)` for foreground conversations — do not resort to other methods**
5. **If the task should run in the background, use `submit_to_agent(...)` to submit it, then `check_agent_task(...)` to check the status**

## Usage Flow

Follow this flow strictly when using this skill:

1) Ensure your tool list includes both `list_agents()` and `chat_with_agent(...)` built-in tools

  - These two tools are the foundation for communicating with other agents — do not remove or disable them
  - If you do not have these tools, inform the user that you need them to talk to other agents, and ask the user to add them

2) Use `list_agents()` to view the currently available agents, and select one by extracting its ID

  - Choose the most appropriate agent based on the user's needs and each agent's description
  - If no suitable agent is found and you are not the Default Agent, use the Default Agent
  - Otherwise, inform the user that no suitable agent is available, and suggest they create a new agent or adjust existing agent descriptions for better matching

3) Call `chat_with_agent(...)` to initiate a foreground conversation. Key parameters include:
  - `to_agent`: the target agent's ID (note: this is the ID, not the name)
  - `text`: what you want to say to the target agent
  - `session_id`: (optional) if you need multiple rounds of conversation with the same agent, pass the same `session_id` starting from the second round to maintain context continuity
  - `timeout`: (optional) estimated time needed for the foreground wait, to avoid premature timeouts

4) If the task is better suited for background execution, use the background tool path:
  - `submit_to_agent(...)`: submit a background task — only requires `to_agent`, `text`, and optionally `session_id`
  - `check_agent_task(...)`: check task status by `task_id`; returns the final result when complete

## Minimal Call Examples

### New Conversation

```text
list_agents()

chat_with_agent(
  to_agent="<target_agent_id>",
  text="[Agent <your_agent_id> requesting] I need your help determining the approach for this issue.",
)
```

### Continuing an Existing Conversation

```text
chat_with_agent(
  to_agent="<target_agent_id>",
  text="[Agent <your_agent_id> requesting] Please continue expanding on point 2 based on the previous conclusion.",
  session_id="<previous_session_id>",
)
```

### Background Submission and Status Check

```text
submit_to_agent(
  to_agent="<target_agent_id>",
  text="[Agent <your_agent_id> requesting] Please complete this longer task in the background.",
)

check_agent_task(
  task_id="<task_id>",
)
```


## Important Notes

- **Add a conversation identifier**: it is recommended to start your message with:

```text
[Agent <your_agent_id> requesting]
```
This helps the other agent clearly identify who is speaking, improving communication efficiency and accuracy.


- **Reuse sessions wisely**: if you need multiple rounds of conversation with the same agent, be sure to pass the same `session_id` to maintain context continuity. Otherwise, each call is treated as a new conversation, and the other agent may not correctly understand your needs. You can obtain the `session_id` from the first round's response, for example:

  ```text
  [SESSION: xxx]
  ```

  where `xxx` is the `session_id` value. This value is typically system-generated and has a long, unique format. Save this `session_id` and continue using it in subsequent conversations with the same agent.
