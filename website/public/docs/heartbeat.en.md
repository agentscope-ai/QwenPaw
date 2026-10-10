# Heartbeat

In QwenPaw, **heartbeat** means: on a fixed interval, ask QwenPaw the
“questions” you wrote in a file, and optionally send the QwenPaw’s reply to
**the channel where you last chatted**. Good for “regular check-ins, daily
digests, scheduled reminders” — QwenPaw runs without you sending a
message.

With **multiple agents**, each agent has its own **HEARTBEAT.md** and
**heartbeat** settings under that agent’s workspace. You can also turn heartbeat
on or off and change the interval in the [Console](./console) (**Control →
Heartbeat**).

If you haven’t read [Introduction](./intro), skim the short notes there on
heartbeat and channels.

---

## How heartbeat works

1. In the current agent’s workspace there is a **heartbeat query file** (default
   name **HEARTBEAT.md**; rename with env **`QWENPAW_HEARTBEAT_FILE`**). Its
   content is **what to ask QwenPaw on each run** (one or more paragraphs; QwenPaw
   treats it as one user message).
2. When **`enabled` is true** in config, the system runs on your **every**
   value (**interval string** or **five-field cron**): read that file → send as
   the user message → QwenPaw replies.
3. **Whether the reply goes to a channel** is set by **target**:
   - **main** — Run QwenPaw only; don’t send the reply to any channel (e.g. local
     self-check, logs).
   - **last** — Send the reply to the **channel/session where you last talked
     to QwenPaw** (e.g. if you last used DingTalk, the heartbeat reply goes to
     DingTalk).

You can also set **active hours**: heartbeat only runs in that daily window
(e.g. 08:00–22:00).

---

## Step 1: Write HEARTBEAT.md

**Path (multi-agent, usual case):**
`<QWENPAW_WORKING_DIR>/workspaces/<agent_id>/HEARTBEAT.md`.
Default `QWENPAW_WORKING_DIR` is `~/.qwenpaw` (override with **`QWENPAW_WORKING_DIR`**);
`<agent_id>` is the current agent id (e.g. `default`).

The default filename is `HEARTBEAT.md`; use **`QWENPAW_HEARTBEAT_FILE`** to change
it. The full path is always **that agent’s workspace root + that filename**.

The file is simply “what to ask each time.” Plain text or Markdown; the whole
thing is one user message.

Example (customize as you like):

```markdown
# Heartbeat checklist

- Scan inbox for urgent email
- Check calendar for next 2h
- Review stuck todos
- Light check-in if quiet for 8h
```

If you ran `qwenpaw init` without `--defaults`, you may be prompted to edit
HEARTBEAT.md; choosing yes opens it in your default editor. You can edit the
file anytime; after save, the **next** heartbeat uses the new content.

---

## Step 2: Configure heartbeat

![heartbeat](https://img.alicdn.com/imgextra/i2/O1CN01yJmAht1oFMh9j9osZ_!!6000000005195-2-tps-3822-2070.png)

Prefer configuring on the Console **Heartbeat** page. To edit **`agent.json`**
instead, use the following.

**Interval, on/off, target, execution timeout, and active hours** are read from
**`heartbeat`** in the current agent’s **`workspaces/<agent_id>/agent.json`**
(same as what the Console saves). After migration from older layouts, legacy
**`agents.defaults.heartbeat`** in root **`config.json`** may have been merged
into the default agent’s **`agent.json`** — treat **`agent.json`** as the
source of truth for new changes.

| Field              | Meaning                                                                                                                                                                                                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **enabled**        | Heartbeat on/off. **Default false**; the schedule runs only when **true**.                                                                                                                                                                                                |
| **every**          | How often: an interval string (`"30m"`, `"1h"`, `"2h30m"`, `"90s"`) **or** a space-separated **five-field cron** (minute hour day month weekday — same shape as cron jobs, e.g. daily 09:00: `"0 9 * * *"`). Cron is interpreted in the **process scheduler’s timezone**. |
| **target**         | **main** — don’t send to a channel; **last** — send using that agent's **`state/last_dispatch.json`** runtime state; **inbox** — send to Inbox.                                                                                                                           |
| **timeoutSeconds** | Maximum execution time for one heartbeat run, in seconds. **Default 300**, valid range **1–3600**.                                                                                                                                                                        |
| **activeHours**    | Optional daily window: `{ "start": "08:00", "end": "22:00" }`.                                                                                                                                                                                                            |

If **every** is omitted, the built-in default applies (currently about **6
hours** — confirm in your installed version). If **every** is present but
empty, unparsable, or not positive, the scheduler falls back to **30 minutes**
(the unparsable case also logs a warning).

Example (heartbeat on, QwenPaw only, no channel, every 30m) — in that agent’s
**`agent.json`**:

```json
{
  "heartbeat": {
    "enabled": true,
    "every": "30m",
    "target": "main"
  }
}
```

Example (send to last conversation channel, every 1h, only 08:00–22:00):

```json
{
  "heartbeat": {
    "enabled": true,
    "every": "1h",
    "target": "last",
    "timeoutSeconds": 300,
    "activeHours": { "start": "08:00", "end": "22:00" }
  }
}
```

Save the file; a running service applies the change in place, without a restart
(see **Runtime semantics** below).

---

## Runtime semantics

These behaviors follow from how heartbeat is implemented rather than from the
fields above, and they are the ones users most often trip over.

### Nothing to report is not filtered

- **main** (default): the run happens, but its output is never delivered — the
  silence is a side effect of not sending. The turn is still written to the
  agent’s `main` session history.
- **last**: every event of the run is streamed to the last channel/session, so
  staying quiet is the model’s job — say so in HEARTBEAT.md.
- **inbox**: no channel delivery; the run writes one Inbox entry —
  `heartbeat_result` on success, `heartbeat_timeout` on timeout,
  `heartbeat_error` on failure.

A tick is skipped without any channel message (debug log only) when the current
time is outside `activeHours`, when the heartbeat file does not exist, or when
the file is empty. `target: "last"` with no usable last dispatch — none recorded,
or recorded without a channel or a user/session — also falls back to running
without delivery.

### Overlapping runs

The heartbeat job sets no concurrency limit of its own, so the scheduler default
applies: a tick that comes due while the previous run is still executing is
**skipped, not queued** (the job uses APScheduler’s default `max_instances=1`;
its `misfire_grace_time` is 60s and governs only how late a firing may be). Ticks
bypass the channel queue and the per-job concurrency limit that cron jobs use,
and always run on the agent’s `main` session. If another turn is already running
on that session (for example a Console request that passes an explicit session
id), both runs proceed concurrently; each saves the session state, and the later
save replaces the earlier one.

### The agent does not answer its own messages

Many bundled channels drop inbound events whose sender is the agent’s own
account early in their message handlers — Matrix compares the event sender with
the agent’s own user id, DingTalk skips messages flagged `is_bot`, and
Mattermost compares the sender with the bot id. Not every channel does this. The
drop is what keeps a heartbeat → reply → room echo from becoming a loop; it is a
per-channel convention, not a heartbeat setting.

### HEARTBEAT.md is not the AGENTS.md heartbeat section

- **HEARTBEAT.md** is read on every tick: the whole trimmed file becomes one
  **user** message on the `main` session. The turn is tagged as coming from
  heartbeat, which also makes the agent skip automatic memory search for it.
- The **`AGENTS.md` section** between `<!-- heartbeat:start -->` and
  `<!-- heartbeat:end -->` is part of the system prompt. While heartbeat is
  enabled the markers are removed and the text is kept; while it is disabled the
  whole section is stripped, so an agent with heartbeat off never sees those
  instructions.

### Config changes apply without a restart

Enabling, disabling, or editing any heartbeat field takes effect in place: a
save from the Console reschedules the job, and a direct `agent.json` edit is
picked up by the config watcher (about 2s) through an agent reload that
re-registers the job. No service restart is needed.

> **“Heartbeat” names several unrelated mechanisms.** Besides the agent
> self-wake on this page, the codebase also calls an SSE idle keep-alive, a
> tool-approval keep-alive, per-channel WebSocket pings, and a cron event-loop
> watchdog “heartbeat”. Only the first is configured by `heartbeat` in
> `agent.json`.

---

## Heartbeat vs cron jobs

|              | Heartbeat                     | Cron jobs                       |
| ------------ | ----------------------------- | ------------------------------- |
| **Count**    | One file (HEARTBEAT.md)       | Many jobs                       |
| **Schedule** | One global interval           | Each job has its own schedule   |
| **Delivery** | Optional last channel or none | Each job sets channel and user  |
| **Best for** | One fixed checklist / digest  | Many tasks, times, and contents |

> Want “good morning at 9” or “every 2h ask todos and send to DingTalk” style
> multi-task automation? Use [Scheduled Tasks](./cron) (or
> [CLI](./cli) `qwenpaw cron create`) instead of heartbeat.

---

## Related pages

- [Introduction](./intro) — What the project can do
- [Console](./console) — Turn heartbeat on/off and change interval in the web UI
- [Channels](./channels) — Connect channels first so target=last has somewhere to send
- [Scheduled Tasks](./cron) — Manage multiple independent scheduled jobs
- [CLI](./cli) — Heartbeat at init, cron jobs
- [Config & working dir](./config) — config.json, agent.json, working directory
