# Advisor Mode

Advisor Mode pairs two models on one task: a stronger **advisor** ("teacher") and the agent that does the work (the "student").

- Before the agent's first step in a conversation, the advisor writes a strategic plan for the task. The plan is injected into the agent's context as a `consult_advisor` tool call and result, so the agent reads it as something it asked for.
- While the agent works, Advisor Mode watches its tool results. When the agent keeps failing (several failures in a row, or failures recurring over the last few steps), the advisor is consulted again with the recent calls. It replies **CONTINUE** (nothing is injected) or **ADJUST** followed by a short revised plan, which is injected as a `consult_advisor_followup` call.
- The agent can also ask on its own: `consult_advisor` is a real tool in Advisor Mode. The agent is told to use it at a genuine decision point (before committing to a costly route, or when it is unsure whether to abandon an approach), not for routine steps. The advisor answers in free text with the agent's recent calls attached, and the exchange shares the same conversation as the plan and any interventions.

This is how a cheap model gets most of the benefit of an expensive one: the expensive model speaks twice or three times per task, the cheap model runs every step.

> Advisor Mode is experimental. It is off by default.

## Which models are used

By default Advisor Mode reuses the two model slots an agent already has:

| Role              | Default model slot                          |
| ----------------- | ------------------------------------------- |
| Advisor (teacher) | the agent's **main model** (`active_model`) |
| Agent (student)   | the **sub-agent model** (`subagent_model`)  |

Set both in the Console: open the model selector in the chat header, pick the main model, then open **Agent model settings** and pick a **Sub-agent model**. When no sub-agent model is configured the agent keeps running on the main model; Advisor Mode still plans and intervenes, it just does not save tokens.

Either role can also be given its own model: the **Advisor and agent models** card of the Advisor loop template (Agent → Configuration → Agent Loop Settings → Advisor) shows which models are in use and lets you pick a different advisor model or agent model. The choice is stored with the agent (`advisor_mode.teacher_model` / `advisor_mode.student_model` in `agent.json`) and does not touch the main or sub-agent slots; pick the default entry again to go back to them. `/advisor status` reports the models in effect.

The advisor is called through the same model factory as every other QwenPaw model call, so provider routing, retries, rate limiting and token accounting all apply.

## Turning it on

**Switch it on for the agent**: Agent → Configuration → **Agent Loop Settings** → the **Advisor** loop template (the gear icon in the composer's mode menu takes you there). The first switch makes Advisor Mode available for the agent: it adds **Advisor** to the composer's mode menu and enables `/advisor`. It does not change how conversations start — they still begin in the default loop. The same card has three more switches, one per capability, so each can be evaluated on its own: _Opening plan_ (the advisor writes a plan before the agent's first step), _Mid-run auto intervention_ (the harness watches tool results and calls the advisor when the agent keeps failing) and _Let the agent proactively ask the advisor via the `consult_advisor` tool_.

**Use it in a conversation (chat composer)**: open the mode menu in the chat input bar (the pill that shows `default`) and pick **Advisor**, then send the task as usual. The first message is sent as `/advisor <task>`: the conversation switches into Advisor Mode and the agent runs the task right away. The conversation stays in Advisor Mode for its later messages until you leave it; while it is active the composer shows it like any other loop mode, and the other loop modes (`/goal`, mission) cannot be started in the same conversation.

The same works anywhere slash commands do (chat, TUI, channels, cron prompts):

```text
/advisor <task>   # start Advisor Mode for this conversation and run the task
/advisor on       # switch it on for this conversation
/advisor off      # leave it (or /new, /clear)
/advisor status   # show advisor / agent models and the current state
```

While the agent switch is off, `/advisor on` and `/advisor <task>` reply with where to turn it on instead of starting the mode.

**API**: `GET /api/advisor-mode` returns the state (the switches, the models in effect and where each comes from), `POST /api/advisor-mode` with any of `{"enabled": true}`, `{"plan_enabled": false}`, `{"followup_enabled": false}`, `{"on_demand_enabled": false}`, `{"max_consults": 5}`, `{"teacher_model": {"provider_id": "…", "model": "…"}}` or `{"student_model": null}` updates it; fields left out are unchanged and `null` clears a model override.

The setting is stored per agent in `agent.json`:

```json
{
  "advisor_mode": {
    "enabled": true,
    "plan_enabled": true,
    "followup_enabled": true,
    "on_demand_enabled": true,
    "max_consults": 32,
    "teacher_model": null,
    "student_model": null
  }
}
```

`max_consults` caps the agent's own questions per conversation (default 32); past the cap the tool answers with a short notice and the agent carries on. Automatic interventions have their own cap (3 per run). With the opening plan switched off, the advisor is only consulted by the harness (auto intervention) or by the agent (`consult_advisor`); the follow-up and consultation requests always carry the task itself, so they work without a plan. Advisor Mode composes with Coding Mode. In this version it is a loop mode of its own, so a conversation is either in Advisor Mode or in another loop mode (`/goal`, mission, custom loops), not both.

It takes effect on the next message; no restart is needed.

## What the agent sees

The injected plan and any follow-up advice appear in the conversation as tool calls named `consult_advisor` and `consult_advisor_followup`; the agent's own questions appear as ordinary `consult_advisor` calls. The injected calls show up the moment the advisor is asked and their output streams in while the advisor writes, like any other tool result, so a long plan is visible as it takes shape rather than after the agent's first step. The agent's own `consult_advisor` calls stream the same way: the tool is a streaming tool and its result grows as the advisor answers. A follow-up consultation that ends in CONTINUE is shown too (with the advisor's verdict) even though nothing is added to the agent's context. For the injected ones the arguments shown to the agent are a short fixed question ("Before I start, how should I approach this task?"), not the full request sent to the advisor, which keeps the agent's context small.

In a multi-turn chat the plan is written once, for the first message of the conversation; later turns get no new opening plan and rely on the mid-run intervention and on the agent's own `consult_advisor` questions, both of which carry the message the agent is answering now. The advisor remembers the plan and its earlier answers for the whole session; `/new` or `/clear` starts the advisor over, plan included.

The advisor's request includes the agent's tool list and a shallow listing of the working directory (the Coding Mode project directory when one is set, otherwise the agent workspace), so its plan is grounded in what is actually there.

## When the advisor steps in

The intervention trigger looks only at signals the tool layer itself emits (`Command failed …`, `Input validation failed …`, `Error: …`, tool-not-found, denied or timed-out approvals) plus a few tool-scoped checks (a shell run that printed `[FAIL]` or a traceback, a search with no matches, a fetch that landed on an error page). Page _content_ that merely mentions "Not Found" does not count.

By default it fires on three failures in a row, or four failures within the last ten steps; counters reset after each intervention and there are at most three interventions per run. When the same call is repeated verbatim the advisor is told the agent is looping and asked to be directive.

The thresholds are per agent: the **Mid-run auto intervention** card of the Advisor loop template exposes _failures in a row_, _failures in the window_, _window size_, _max interventions per run_ and _cooldown_, stored as `advisor_mode.intervention` in `agent.json` (`consecutive_failures`, `window_failures`, `window_size`, `max_interventions`, `cooldown_steps`) and accepted as a partial object by `POST /api/advisor-mode`.

## Transcripts

Every advisor exchange (plan request, plan, interventions and verdicts) is written to `~/.qwenpaw/advisor/<agent_id>/<session_id>.json`, outside the agent workspace on purpose, so the agent's own file searches never pick the advisor's log up as task material.
