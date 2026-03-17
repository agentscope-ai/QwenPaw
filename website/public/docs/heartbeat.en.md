# Heartbeat

In CoPaw, **heartbeat** means: on a fixed interval, ask CoPaw the
“questions” you wrote in a file, and optionally send the CoPaw’s reply to
**the channel where you last chatted**. Good for “regular check-ins, daily
digests, scheduled reminders” — CoPaw runs without you sending a
message.

If you haven’t read [Introduction](./intro), skim the short “terms” there
(heartbeat, channels) first.

---

## How heartbeat works

1. You have a file **HEARTBEAT.md** (by default under the working dir
   `~/.boostclaw/`). Its content is **what to ask CoPaw each time** (one
   block of text; CoPaw sees it as one user message).
2. The system runs on your **interval** (e.g. every 30 minutes): read
   HEARTBEAT.md → send that as the user message → CoPaw replies.
3. **Whether the reply is sent to a channel** is controlled by **target** in
   config:
   - **main** — Run CoPaw only; do not send the reply anywhere (e.g. for
     local check-ins or logs).
   - **last** — Send the CoPaw’s reply to **the channel/session where you
     last talked to CoPaw** (e.g. if you last used DingTalk, the
     heartbeat reply goes to DingTalk).

You can also set **active hours**: heartbeat runs only in that time window each
day (e.g. 08:00–22:00).

---

## Step 1: Write HEARTBEAT.md

Default path: `~/.boostclaw/HEARTBEAT.md`. Content = “what to ask each time.”
Plain text or Markdown; the whole thing is sent as one user message.

Example (customize as you like):

```markdown
# Heartbeat checklist

- Scan inbox for urgent email
- Check calendar for next 2h
- Review stuck todos
- Light check-in if quiet for 8h
```

If you ran `copaw init` without `--defaults`, you were prompted to edit
HEARTBEAT.md; the default editor would open. You can also edit the file anytime;
the next heartbeat run will use the new content.

---

## Step 2: Configure heartbeat in config.json

**Interval, target, and active hours** are in `config.json` (usually
`~/.boostclaw/config.json`), under `agents.defaults.heartbeat`:

| Field       | Meaning                                    | Example                                        |
| ----------- | ------------------------------------------ | ---------------------------------------------- |
| every       | How often to run                           | `"30m"`, `"1h"`, `"2h30m"`, `"90s"`            |
| target      | Where to send the reply                    | `"main"` = don’t send; `"last"` = last channel |
| activeHours | Optional; only run in this window each day | `{ "start": "08:00", "end": "22:00" }`         |

Example (run every 30m, no channel):

```json
"agents": {
  "defaults": {
    "heartbeat": {
      "every": "30m",
      "target": "main"
    }
  }
}
```

Example (send to last channel, every 1h, only 08:00–22:00):

```json
"agents": {
  "defaults": {
    "heartbeat": {
      "every": "1h",
      "target": "last",
      "activeHours": { "start": "08:00", "end": "22:00" }
    }
  }
}
```

Save config; if the server is running, the new settings take effect (some
setups may require a restart).

---

## Heartbeat vs cron jobs

|              | Heartbeat                                    | Cron jobs                                               |
| ------------ | -------------------------------------------- | ------------------------------------------------------- |
| **Count**    | One prompt file (HEARTBEAT.md)               | As many as you need                                     |
| **Schedule** | One global interval                          | Each job has its own schedule                           |
| **Delivery** | Optional: send to last channel or don't send | Each job specifies its own channel and user             |
| **Best for** | One fixed check-in / digest                  | Multiple jobs at different times with different content |

> Need "send Good morning at 9am" or "every 2h ask todos and send to DingTalk"? Use [CLI](./cli) `copaw cron create` (cron jobs), not heartbeat.

---

## Related pages

- [Introduction](./intro) — What the project can do
- [Channels](./channels) — Connect a channel first so target=last has somewhere to send
- [CLI](./cli) — Configure heartbeat at init, manage cron jobs
- [Config & working dir](./config) — config.json and working directory
