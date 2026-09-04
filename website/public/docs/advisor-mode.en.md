# Advisor Mode

Advisor Mode pairs two models on one task: a stronger **advisor** and the **worker**, the agent that does the work.

- Before the agent's first step in a conversation, the advisor writes a strategic plan for the task. The plan is injected into the agent's context as a `consult_advisor` tool call and result, so the agent reads it as something it asked for.
- While the agent works, Advisor Mode watches its tool results. When the agent keeps failing (several failures in a row, or failures recurring over the last few steps), the advisor is consulted again with the recent calls. It replies **CONTINUE** (nothing is injected) or **ADJUST** followed by a short revised plan, which is injected as a `consult_advisor_followup` call.
- The agent can also ask on its own: `consult_advisor` is a real tool in Advisor Mode. The agent is told to use it at a genuine decision point (before committing to a costly route, or when it is unsure whether to abandon an approach), not for routine steps. The advisor answers in free text with the agent's recent calls attached, and the exchange shares the same conversation as the plan and any interventions.

The stronger model is called only a few times per task, while the cheaper model runs every step.

> Advisor Mode is experimental. It is off by default.

---

## Which models are used

By default Advisor Mode reuses the two model slots an agent already has:

| Role    | Default model slot                          |
| ------- | ------------------------------------------- |
| Advisor | the agent's **primary model** (`active_model`) |
| Worker  | the **sub-agent model** (`subagent_model`)  |

When no sub-agent model is configured the worker keeps running on the primary model. Advisor Mode still plans and intervenes, it just does not save tokens.

Either role can be pinned to another model: when you pick **Advisor** in the Loop mode menu of the chat input, an **Advisor models** panel opens next to the mode pill with an *Advisor model* and a *Worker model* pick, prefilled with the defaults above. In an Advisor conversation the model pill in the chat header shows the pair (advisor → worker) instead of a single model and reopens the same panel. The choice is saved for the agent (`advisor_mode.advisor_model` / `advisor_mode.worker_model` in `agent.json`, also accepted by `POST /api/advisor-mode`) and does not touch the primary or sub-agent slots. Pick the default entry again to go back to them. The **Advisor and worker models** card of the Advisor loop template and `/advisor status` show the models in effect.

The advisor's own calls have a separate thinking level, `advisor_mode.advisor_thinking` (**Advisor thinking** on the same card): `off` by default, so the plan arrives quickly even with a thinking model. `inherit` follows the agent and model defaults, `low` / `medium` / `high` set a level for the advisor only. Turn it up when plan quality matters more than latency.

The advisor is called through the same model factory as every other QwenPaw model call, so provider routing, retries, rate limiting and token accounting all apply.

---

## Turning it on

**Switch it on for the agent**: Agent → Configuration → **Agent Loop Settings** → the **Advisor** loop template (the gear icon in the Loop mode menu takes you there). The first switch makes Advisor Mode available for the agent: it adds **Advisor** to the Loop mode menu and enables `/advisor`. It does not change how conversations start — they still begin in the default loop. Below it, the **Advisor and worker models** card shows the models in effect, and three more cards switch each capability on its own, so each can be evaluated separately: **Opening plan** (the advisor writes a plan before the agent's first step), **Mid-run auto intervention** (QwenPaw watches tool results and calls the advisor when the agent keeps failing) and **On-demand consultation** (the `consult_advisor` tool).

**Use it in a conversation (chat input)**: open the Loop mode menu in the chat input bar (the pill that shows `default`) and pick **Advisor**, then send the task as usual. The first message is sent as `/advisor <task>`: the conversation switches into Advisor Mode and the agent runs the task right away. The conversation stays in Advisor Mode for its later messages until you leave it. While it is active the chat input shows it like any other loop mode, and the other loop modes (`/goal`, mission) cannot be started in the same conversation.

The same works anywhere slash commands do (chat, TUI, channels, cron prompts):

```text
/advisor <task>   # start Advisor Mode for this conversation and run the task
/advisor on       # switch it on for this conversation
/advisor off      # leave it (or /new, /clear)
/advisor status   # show the advisor and worker models and the current state
```

While the agent switch is off, `/advisor on` and `/advisor <task>` reply with where to turn it on instead of starting the mode.

The per-conversation switch lives in memory, like the Goal and custom loop modes: after QwenPaw restarts, a conversation is back in the default loop (and the advisor's memory of its plan is gone) until you pick Advisor again. The agent-level switch and everything else in the Advisor template are stored in `agent.json` and survive restarts.

**API**: `GET /api/advisor-mode` returns the state (the switches, the models in effect and the defaults they fall back to). `POST /api/advisor-mode` with any of `{"enabled": true}`, `{"plan_enabled": false}`, `{"followup_enabled": false}`, `{"on_demand_enabled": false}`, `{"max_consults": 5}`, `{"advisor_model": {"provider_id": "…", "model": "…"}}`, `{"worker_model": null}` or `{"advisor_thinking": "off"}` updates it. Fields left out are unchanged and `null` clears a model override.

The setting is stored per agent in `agent.json`:

```json
{
  "advisor_mode": {
    "enabled": true,
    "plan_enabled": true,
    "followup_enabled": true,
    "on_demand_enabled": true,
    "max_consults": 32,
    "intervention": {
      "consecutive_failures": 3,
      "window_size": 10,
      "window_failures": 4,
      "cooldown_steps": 0,
      "max_interventions": 3
    },
    "advisor_model": null,
    "worker_model": null,
    "advisor_thinking": "off"
  }
}
```

`max_consults` caps the agent's own questions per conversation (default 32). Past the cap the tool answers with a short notice and the agent carries on. Automatic interventions have their own cap (`max_interventions`, see below). With the opening plan switched off, the advisor is only consulted automatically (auto intervention) or by the agent (`consult_advisor`). The follow-up and consultation requests always carry the task itself, so they work without a plan.

Advisor Mode composes with Coding Mode. In this version it is a loop mode of its own, so a conversation is either in Advisor Mode or in another loop mode (`/goal`, mission, custom loops), not both.

It takes effect on the next message. No restart is needed.

---

## What the agent sees

The injected plan and any follow-up advice appear in the conversation as tool calls named `consult_advisor` and `consult_advisor_followup`. The agent's own questions appear as ordinary `consult_advisor` calls. The injected calls show up the moment the advisor is asked and their output streams in while the advisor writes, like any other tool result, so a long plan is visible as it takes shape rather than after the agent's first step. The agent's own `consult_advisor` calls stream the same way: the tool is a streaming tool and its result grows as the advisor answers. A follow-up consultation that ends in CONTINUE is shown too (with the advisor's verdict) even though nothing is added to the agent's context. For the injected ones the arguments shown to the agent are a short fixed question ("Before I start, how should I approach this task?"), not the full request sent to the advisor, which keeps the agent's context small.

In a multi-turn chat the plan is written once, for the first message of the conversation. Later turns get no new opening plan and rely on the mid-run intervention and on the agent's own `consult_advisor` questions, both of which carry the message the agent is answering now. The advisor remembers the plan and its earlier answers for the whole session. `/new` or `/clear` starts the advisor over, plan included.

The advisor's request includes the agent's tool list and a shallow listing of the working directory (the Coding Mode project directory when one is set, otherwise the agent workspace), so its plan is grounded in what is actually there.

---

## When the advisor steps in

The intervention trigger looks only at signals the tool layer itself emits (`Command failed …`, `Input validation failed …`, `Error: …`, tool-not-found, denied or timed-out approvals) plus a few tool-scoped checks (a shell run that printed `[FAIL]` or a traceback, a search with no matches, a fetch that landed on an error page). Page _content_ that merely mentions "Not Found" does not count.

By default it fires on three failures in a row, or four failures within the last ten steps. Counters reset after each intervention, and there are at most three interventions per run. When the same call is repeated verbatim the advisor is told the agent is looping and asked to be directive.

The thresholds are per agent: the **Mid-run auto intervention** card of the Advisor loop template exposes _failures in a row_, _failures in the window_, _window size_, _max interventions per run_ and _cooldown_, stored as `advisor_mode.intervention` in `agent.json` (`consecutive_failures`, `window_failures`, `window_size`, `max_interventions`, `cooldown_steps`) and accepted as a partial object by `POST /api/advisor-mode`.

---

## Transcripts

Every advisor exchange (plan request, plan, interventions and verdicts) is written to `~/.qwenpaw/advisor/<agent_id>/<session_id>.json`, outside the agent workspace on purpose, so the agent's own file searches never pick the advisor's log up as task material.
