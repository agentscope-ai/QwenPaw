# Loop Engineering

In a normal conversation, the Agent replies once and waits for your next message. But some tasks cannot be completed in a single turn — fixing a chain of tests, implementing a full feature, or decomposing a large requirement into sub-tasks for different Agents to execute.

Loop Engineering lets the Agent **keep working across multiple turns** until the task is complete, the budget is exhausted, or you stop it manually.

---

## Which Mode Should I Use?

| Your task                                              | Recommended mode    |
| ------------------------------------------------------ | ------------------- |
| Quick Q&A, small fixes                                 | Normal conversation |
| A clear objective that needs sustained effort          | **Goal Mode**       |
| Research a topic and produce a comprehensive report    | **Goal Mode**       |
| A large project with multiple independent sub-tasks    | **Mission Mode**    |
| Complex requirements needing multi-Agent collaboration | **Mission Mode**    |

> **The key difference:** Goal Mode uses a single Agent in a persistent loop with **self-audit** — the Agent must prove the objective is achieved before stopping. Mission Mode uses multiple sub-Agents with **context isolation** — each worker focuses only on its own sub-task, preventing context corruption in long conversations.

---

## Loop Settings in Normal Mode

Even without Goal Mode or Mission Mode, QwenPaw has loop control mechanisms that protect Agent behavior. You can configure these in the Console under **Runtime Config → Agent Loop Settings**.

### Loop Templates

The Console provides three presets for one-click switching:

| Template    | Purpose                                         |
| ----------- | ----------------------------------------------- |
| **Default** | Normal conversation, moderate iteration limit   |
| **Goal**    | Parameters optimized for the `/goal` command    |
| **Mission** | Parameters optimized for the `/mission` command |

After selecting a template, the settings below are auto-filled with recommended values. You can also adjust them manually.

### Iteration Limit

Prevents the Agent from looping infinitely. Forces a stop when the reasoning-acting (ReAct) iteration count reaches the limit.

| Setting                | Default | Description                           |
| ---------------------- | ------- | ------------------------------------- |
| Enable iteration limit | On      | Whether to enable                     |
| Max iterations         | 50      | Agent stops after reaching this count |

> **What counts as one iteration?** Each cycle of "think → call a tool → get result" or "think → output text" counts as one iteration. A complex task may require dozens of iterations.

### Repetition Protection

Detects when the Agent is stuck in a "doom loop" — repeatedly doing the same thing (e.g., calling the same tool with the same arguments).

The system uses a sliding window to track recent tool calls and calculates similarity. When a repetitive pattern is detected, it escalates in stages:

1. **Stage 1 (mild repetition):** Injects a prompt suggesting the Agent try a different approach
2. **Stage 2 (severe repetition):** Forces the loop to stop

Enabled by default; no manual adjustment needed in most cases.

### Completion Check

Some large language models may output text without calling any tools, causing the Agent to stop prematurely. When enabled, if the Agent only outputs text (no tool calls), the system automatically injects a reminder asking it to confirm whether the task is truly complete.

| Setting                 | Default                          | Description                |
| ----------------------- | -------------------------------- | -------------------------- |
| Enable completion check | Off                              | Whether to enable          |
| Check prompt            | _"You did not call any tool..."_ | The reminder text injected |
| Max interventions       | 1                                | Max reminders per turn     |

> **When should I enable this?** If you notice the Agent often stops after outputting text without actually finishing the task, turn this on.

### Corresponding agent.json Configuration

The Console settings above map to the `running.loop` field in `agent.json`:

```json
{
  "running": {
    "loop": {
      "iteration": {
        "enabled": true,
        "max_iterations": 50
      },
      "doom_loop": {
        "enabled": true,
        "window_size": 6,
        "similarity_threshold": 0.8,
        "stages": [
          { "after": 2, "action": "modify_prompt", "message": "..." },
          { "after": 4, "action": "stop", "message": "..." }
        ]
      },
      "rubric": {
        "enabled": false,
        "prompt": "You did not call any tool in the last turn...",
        "max_interventions": 1
      }
    }
  }
}
```

---

## Goal Mode

Set an objective, and the Agent works autonomously until it is done. Not limited to coding — any task with a clear goal works.

### Quick Start

Type in the chat:

```
/goal Research the context window lengths of mainstream LLMs in 2026 and compile a comparison table
```

More examples:

```
/goal Fix all failing unit tests and ensure 100% pass rate
/goal Translate the project documentation from Chinese to English, keeping formatting consistent
/goal Analyze last week's user feedback data and generate a trends report
```

The Agent keeps working — using tools, analyzing results, adjusting its approach — until the goal is complete or the budget runs out.

### Goal Tools

Goal Mode automatically enables three dedicated tools for the Agent. No manual configuration needed:

| Tool          | Purpose                                                                        |
| ------------- | ------------------------------------------------------------------------------ |
| `get_goal`    | Agent checks current progress — iteration count, token usage, remaining budget |
| `update_goal` | Agent marks the goal as `complete` or `blocked`                                |
| `create_goal` | Agent creates a new goal in conversation (only when you explicitly ask)        |

### When Does the Loop Stop?

| Condition              | Description                                                                        |
| ---------------------- | ---------------------------------------------------------------------------------- |
| Goal complete          | Agent confirms all requirements are met and calls `update_goal(status="complete")` |
| Goal blocked           | Agent reports a persistent blocker after multiple consecutive turns                |
| Iterations exhausted   | Reaches the max iteration count (default: 20)                                      |
| Token budget exhausted | Token usage exceeds the budget (default: 300,000)                                  |
| You stop manually      | Click the stop button                                                              |

### Completion Quality

The Agent does not casually declare "I'm done." Before marking a goal complete, it:

- Derives concrete requirements from your goal description
- Checks each requirement against actual evidence (e.g., running tests, inspecting files)
- Treats items without definitive evidence as "not complete"

This makes Goal Mode more reliable than normal conversation — the Agent must **prove** the task is done, not just "feel" it is done.

---

## Mission Mode

Decomposes large tasks into multiple user stories, completed automatically through a **master → worker → verifier** pipeline. Each sub-Agent handles only its own sub-task with fully isolated context, preventing quality degradation from information mixing in long conversations.

### Quick Start

```
/mission Create a CLI TODO app in Python with add, delete, list, and mark-complete features, saving data to local JSON file
```

Optional parameters:

```
/mission Create Web API --max-iterations 30 --verify "pytest tests/"
```

Check progress and history:

```
/mission status    # Current progress
/mission list      # All missions
```

### Workflow

**Phase 1 — Task Decomposition**

The Agent analyzes your task and generates a PRD (Product Requirements Document) containing multiple user stories. After you confirm the PRD, it proceeds to Phase 2.

**Phase 2 — Autonomous Execution**

1. Master agent assigns each user story to a worker agent
2. Worker agent implements the feature independently
3. Verifier agent independently validates whether each story meets acceptance criteria
4. Failed stories are automatically retried until all pass or iterations are exhausted

### Progress Display

```
Mission Status — mission-20260415-123456
- Phase: execution
- Progress: 2/4 stories passed

  ✅ US-001: Add Task Feature
  ✅ US-002: List Tasks Feature
  ⬜ US-003: Delete Task Feature
  ⬜ US-004: Mark Complete Feature
```

### Important Notes

1. **Session isolation**: Each session's missions run independently without interference
2. **Tool restrictions**: In Phase 2, the master agent cannot directly edit files or use the browser — it must delegate to worker agents
3. **Security note**: Worker and verifier agents automatically bypass the security guard (since background sessions cannot respond to `/approve`). Use Mission Mode only in fully trusted codebases

---

## Mode Comparison

| Feature                 | Normal Chat        | Goal Mode                       | Mission Mode                             |
| ----------------------- | ------------------ | ------------------------------- | ---------------------------------------- |
| **Use case**            | Simple tasks       | Clear-objective sustained tasks | Large complex tasks                      |
| **Agent count**         | 1                  | 1                               | Multiple (master + workers + verifiers)  |
| **Loop behavior**       | Reply once, stop   | Persistent loop + self-audit    | Multi-Agent pipeline + context isolation |
| **Completion criteria** | Agent outputs text | Agent calls update_goal         | All PRD stories pass                     |
| **Budget control**      | Iteration limit    | Iteration + token budget        | Iteration limit                          |
| **Tool restrictions**   | None               | None                            | Master restricted                        |

---

## Developing Loop Plugins

> The following content is for plugin developers. If you only use Goal Mode or Mission Mode, the sections above are sufficient.

QwenPaw's loop system is fully pluggable. You can register custom loop behavior through the plugin API, implementing your own "when to stop, when to continue" logic.

### Core Concept

The heart of loop control is the **Gate** — after each iteration, the system asks all registered Gates: "Should we stop?" Each Gate has three possible answers:

- **STOP** — Request to stop the loop
- **CONTINUE** — Request to continue (can include a message injected into the conversation)
- **None** — No opinion, don't intervene

The first Gate that returns STOP or CONTINUE determines the result for that turn.

### Writing a Gate

```python
from qwenpaw.loop.gates.base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)


class TimeoutGate(StopGate):
    """Example: stop after N minutes."""

    def __init__(self, max_minutes=30):
        self._max = max_minutes * 60
        self._start = None

    @property
    def name(self):
        return "timeout"

    @property
    def priority(self):
        return 50  # lower = runs earlier

    async def check(self, ctx):
        import time

        if self._start is None:
            self._start = time.time()
        elapsed = time.time() - self._start
        if elapsed > self._max:
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=f"Timeout after {self._max}s",
            )
        return None  # no opinion
```

`ctx` is a dictionary containing context for the current iteration:

| Field            | Description                                              |
| ---------------- | -------------------------------------------------------- |
| `agent`          | The Agent instance                                       |
| `final_msg`      | Agent's last message (`None` means tool calls this turn) |
| `iteration`      | Current iteration number                                 |
| `has_tool_calls` | Whether there are tool calls this turn                   |

### Registering in a Plugin

```python
from qwenpaw.loop.gates import StopHandler
from qwenpaw.plugins.api import PluginAPI


class MyLoopPlugin(PluginAPI):
    def on_load(self):
        handler = StopHandler()
        handler.register(TimeoutGate(max_minutes=30))

        self.register_agent_stop_handler(
            handler=handler,
            priority=100,
            name="timeout-loop",
        )
```

Once registered, your Gate runs at the end of every ReAct iteration alongside built-in Gates. Loop plugins you develop can be published to the QwenPaw plugin marketplace, letting other users install new loop capabilities with one click — such as controlling loops based on external API status, deciding whether to continue based on code coverage, or integrating custom quality evaluation services.

### Scope Isolation

You can set `scope` during registration to control when the handler activates:

| scope        | Behavior                                                           |
| ------------ | ------------------------------------------------------------------ |
| `""` (empty) | Always runs, regardless of current mode                            |
| `"default"`  | Only runs in normal chat; auto-skipped when Goal/Mission is active |
| Custom value | Only runs when the corresponding mode is active                    |

---

## Design Principles

### Gate System

QwenPaw uses a **Gate system** to manage loop termination logic. Think of Gates as quality checkpoints on an assembly line — after each round of work, all Gates are checked in sequence.

```
Agent completes one round of work
      ↓
   Gate 1 (iteration limit)  →  Limit reached? → STOP
      ↓ no opinion
   Gate 2 (doom loop detection)  →  Repeating? → STOP or inject prompt
      ↓ no opinion
   Gate 3 (completion check)  →  Text-only output? → CONTINUE + reminder
      ↓ no opinion
   Gate 4 (plugin Gate)  →  Custom logic
      ↓ all Gates have no opinion
   Agent stops (no active loop)
```

Each Gate has three responses:

- **STOP**: Request to stop the loop
- **CONTINUE**: Request to continue (can inject a message)
- **No opinion**: Don't intervene, pass to the next Gate

The first Gate that gives a definitive answer determines the result. Gates execute in priority order (lower number = runs first), giving you precise control over the precedence of different Gates.

### Scope Isolation

Gates from different modes don't interfere with each other. When Goal Mode or Mission Mode is active, default Gates automatically yield, and only the corresponding mode's Gates run. When the mode ends, default Gates automatically resume.

This means:

- Normal chat → Only default Gates run (iteration limit, doom loop, etc.)
- `/goal` activated → Default Gates yield, Goal Mode Gates take over
- `/mission` activated → Default Gates yield, Mission Mode Gates take over
- Mode ends → Default Gates automatically resume

### Deferred Execution

When the Agent is executing tool calls, STOP signals don't take effect immediately — the system waits for the tools to finish and the Agent to receive results before stopping. This prevents tools from being interrupted mid-execution.

### Session Isolation

Each user session's Gate state is completely independent. When multiple users share the same Agent, their loops don't affect each other.

---

## What's Coming

We're working to make Loop Engineering even more accessible and powerful:

**Zero-code Gate orchestration** — Currently, custom Gates require writing Python plugins. We plan to provide a visual Gate orchestration interface in the Console: drag and drop different Gates, set priorities and trigger conditions, and preview the results directly in the browser. This means product managers and operators can customize Agent loop strategies without developer involvement.

**Declarative configuration** — Beyond the visual interface, we will also support defining Gate chains declaratively via YAML/JSON. This lets you version-control loop strategies, replicate them across environments with one click, or automate deployment in CI/CD pipelines.
