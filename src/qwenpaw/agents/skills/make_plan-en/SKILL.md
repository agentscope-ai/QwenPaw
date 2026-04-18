---
name: make_plan
description: For external plan request scenarios, guides the Agent to request a clear, actionable, step-by-step plan from a stronger Agent via list_agents and chat_with_agent, emphasizing that the plan is executed by the requester, not by the consulted Agent.
metadata:
  builtin_skill_version: "1.1"
  qwenpaw:
    emoji: "🗺️"
---

# Make Plan

Use this Skill when you need to make an **external plan request** to a stronger Agent.

The goal of this Skill is not to outsource a task, but rather to:
- Request a plan from a stronger Agent
- The plan must consist of **clear, actionable steps**
- **You execute the plan yourself**
- Do not ask the consulted Agent to execute the task directly

How to invoke:
- Use `list_agents()` to check available Agents
- Use `chat_with_agent(...)` to request the stronger Agent to "make a plan"
- In `text`, explicitly include the prompt: **only provide a step-by-step executable plan, do not execute**
- To supplement or refine the original plan in a follow-up, pass `session_id`

Recommended invocation skeleton:

```text
list_agents()

chat_with_agent(
  to_agent="<stronger_agent>",
  text="[Agent <auto> requesting] Please help me create an execution plan for the following task. You do not need to execute the task -- just output clear, actionable steps in order.",
)
```

## Core Rules

This Skill handles one thing only:
1. Find a stronger Agent
2. Request that Agent to output an execution plan
3. Require the plan to be step-by-step, actionable, and in sequential order
4. You execute the plan yourself rather than asking the other Agent to do it for you

If what you truly need is a "plan", use this Skill.
If what you need is a final answer, architectural judgment, review conclusion, or direct execution, do not misuse this Skill.

## Applicable Scenarios

The following scenarios are suitable for making an external plan request:
- The task requires multi-step decomposition
- Steps have dependencies between them
- A clear sequence, checkpoints, or verification points are needed
- Multiple modules, files, systems, or roles are involved
- The user explicitly requests a plan before execution
- You want to obtain a more complete and reliable execution path first

## Do Not Use This Way

Do not use this Skill in the following situations:
- You actually want the other Agent to do the task for you
- What you really lack is a small piece of factual information, not a plan
- What you truly need is an architectural judgment or solution comparison
- You have not yet clearly understood the task objective

## What to Ask the Stronger Agent For

When calling `chat_with_agent(...)`, clearly state:
- **You need a plan, not execution**
- **Steps must be concrete, not just abstract advice**
- **Preferably include verification methods and completion criteria**

## Tool Invocation Rules

Execute in this order by default:
1. Call `list_agents()` to confirm available stronger Agents
2. Select the most suitable target Agent for creating the plan
3. Call `chat_with_agent(...)` to request the generation of an execution plan
4. After receiving the plan, execute it yourself -- do not continue outsourcing the task to the other Agent

When requesting the plan, explicitly state:
- Only the plan is needed, not execution
- Steps must be specific, not general advice
- Clearly request sequence, dependencies, checkpoints, and verification methods when needed

Common parameters for `chat_with_agent`:
- `to_agent`: Target Agent ID
- `text`: Request content; must explicitly state "only output the plan, do not execute the task"
- `session_id`: Optional; pass this to continue an existing conversation

Notes:
- `base_url` generally does not need to be provided; the tool will automatically resolve the current API address
- Not passing `session_id` will automatically create a new session

## Request Template

Please help me create an execution plan for the following task.
You **do not need to execute the task itself** -- just output the plan.

Task:
[What needs to be done]

Goal:
[What the final outcome should be]

Constraints:
- [...]
- [...]

Plan requirements:
1. Break it down into clear, executable steps
2. Indicate the recommended order
3. Point out dependencies, checkpoints, or verification methods where necessary
4. If there are obvious risks, include key points to watch out for

Output format:
[e.g., Output 5-8 numbered steps, 1-3 sentences each]

Example:

```text
chat_with_agent(
  to_agent="strong_reasoner",
  text="""
Please help me create an execution plan for the following task.
You do not need to execute the task itself -- just output the plan.

Task:
Modify a multi-module feature.

Goal:
Complete the change with low risk and avoid missing integration points.

Constraints:
- Minimize rework
- Include verifiable intermediate checkpoints

Plan requirements:
1. Break it down into actionable steps
2. Indicate the recommended order
3. Mark key dependencies and checkpoints
4. Include verification methods where possible

Output format:
Please output 3-5 numbered steps, each as specific as possible.
""",
)
```

For follow-up conversations:

```text
chat_with_agent(
  to_agent="strong_reasoner",
  text="Based on the previous plan, please further refine the checkpoints for steps 3 and 4. Still only provide the plan -- do not execute the task.",
  session_id="<previous_session_id>",
)
```

## What to Do After Receiving the Plan

Treat the stronger Agent's reply as "execution plan input", not as "the task is already done".

What you should do:
1. Distill the truly executable steps
2. Determine whether adjustments are needed for your environment
3. Execute the steps yourself
4. If new uncertainties arise, continue refining the plan

Do not deliver the plan as-is to the user as a final result, unless the user specifically asked for the plan itself.

## Plan Quality Standards

A qualified plan should at least meet the following criteria:
- Has clear steps, not vague advice
- Step order is clear
- Each step is an executable action
- Key dependencies are identified
- Necessary verification points are included
- Does not secretly delegate "task execution" to the consulted Agent

If what you receive is vague advice such as "first analyze, then implement, then test", it is not sufficient -- follow up to request refinement.

## Behavioral Guardrails

- Do not turn "please help me plan" into "please do the whole thing for me"
- Do not request the other Agent to execute code, commands, or changes on your behalf
- Do not accept answers that only provide direction without steps
- Do not request a plan when the task objective is not yet clear
- Do not stop thinking after receiving the plan -- still evaluate it against your current environment

## Final Principle

When you lack an execution path, request a plan first.
The plan must be step-by-step, specific, and actionable.
The consulted Agent is responsible for producing the plan, not for executing it.
After receiving the plan, the requester executes it themselves.
