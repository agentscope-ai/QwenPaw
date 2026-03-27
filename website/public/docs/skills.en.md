# Skills

**Skills**: Several are built-in, and you can add custom skills or import skills from the Skills Hub.

Two ways to manage skills:

- **Console** — Use the [Console](./console) under **Agent → Skills**
- **Working directory** — Follow the steps below to edit files directly

> If you're new to channels, heartbeat, or cron, read [Introduction](./intro) first.

Each workspace stores its local skills in `skills/` and controls whether they
are active through `skill.json`. Any subdirectory containing a `SKILL.md` is
recognized as a skill; no extra registration is needed.

All newly created or imported skills are **disabled by default**. You must
explicitly enable them in the Console or CLI before they take effect.

---

## Built-in skills overview

The following skills are built-in. They are available through the local skill
pool and can be broadcast into a workspace when needed; once present in a
workspace, you can enable or disable them there.

| Skill                        | Description                                                                                                                                                                 | Source                                                         |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| **cron**                     | Scheduled jobs. Create, list, pause, resume, or delete jobs via `copaw cron` or Console **Control → Cron Jobs**; run on a schedule and send results to a channel.           | Built-in                                                       |
| **file_reader**              | Read and summarize text-based files (.txt, .md, .json, .csv, .log, .py, etc.). PDF and Office are handled by the skills below.                                              | Built-in                                                       |
| **dingtalk_channel_connect** | Helps with DingTalk channel onboarding: guides you through the developer console, key fields, credential lookup (`Client ID` / `Client Secret`), and required manual steps. | Built-in                                                       |
| **himalaya**                 | Manage emails via CLI (IMAP/SMTP). Use `himalaya` to list, read, search, and organize emails from the terminal; supports multiple accounts and attachments.                 | https://github.com/openclaw/openclaw/tree/main/skills/himalaya |
| **news**                     | Fetch and summarize latest news from configured sites; categories include politics, finance, society, world, tech, sports, entertainment.                                   | Built-in                                                       |
| **pdf**                      | PDF operations: read, extract text/tables, merge/split, rotate, watermark, create, fill forms, encrypt/decrypt, OCR, etc.                                                   | https://github.com/anthropics/skills/tree/main/skills/pdf      |
| **docx**                     | Create, read, and edit Word documents (.docx), including TOC, headers/footers, tables, images, track changes, comments.                                                     | https://github.com/anthropics/skills/tree/main/skills/docx     |
| **pptx**                     | Create, read, and edit PowerPoint (.pptx), including templates, layouts, notes, comments.                                                                                   | https://github.com/anthropics/skills/tree/main/skills/pptx     |
| **xlsx**                     | Read, edit, and create spreadsheets (.xlsx, .xlsm, .csv, .tsv), clean up formatting, formulas, and data analysis.                                                           | https://github.com/anthropics/skills/tree/main/skills/xlsx     |
| **browser_visible**          | Launch a real, visible (headed) browser window for demos, debugging, or scenarios requiring human interaction (e.g. login, CAPTCHA).                                        | Built-in                                                       |

---

## Managing skills in the Console

In the [Console](./console), go to **Agent → Skills** to:

- See all loaded skills and their enabled state;
- **Enable or disable** a skill with a toggle;
- **Create** a custom skill by entering a name and content (no need to create a directory);
- **Edit** an existing skill's name or content.

Changes are written to the workspace `skills/` directory and `skill.json`, and
take effect for that workspace. Handy if you prefer not to edit files directly.

---

## Built-in skill: Cron (scheduled tasks)

The **Cron** skill is built in and can be added to a workspace from the skill
pool. It provides "run on a schedule and send results to a channel." You
manage jobs with the [CLI](./cli) (`copaw cron`) or in the Console under
**Control → Cron Jobs**; no need to edit skill files.

Common operations:

- Create a job: `copaw cron create --type agent --name "xxx" --cron "0 9 * * *" ...`
- List jobs: `copaw cron list`
- Check state: `copaw cron state <job_id>`

---

## Skill Pool

The **Skill Pool** is a shared, local skill repository at `~/.copaw/skill_pool/`.
It stores built-in skills and any custom skills you choose to share across
workspaces.

```
~/.copaw/
  skill_pool/                # Shared pool
    skill.json               # Pool manifest (source of truth)
    pdf/
      SKILL.md
    cron/
      SKILL.md
    my_shared_skill/
      SKILL.md
  workspaces/
    default/
      skill.json             # Workspace manifest (enabled/channels/config)
      skills/                # This workspace's local copies
        pdf/
          SKILL.md
        my_skill/
          SKILL.md
```

Key points:

- Pool skills are **not directly used** by any workspace. A workspace must
  **broadcast** (copy) a skill before it can be enabled.
- Each workspace's `skill.json` is the source of truth for which skills are
  enabled, which channels they apply to, and their config.
- Built-in skills in the pool can be deleted and later imported back from the
  packaged source. They still cannot be overwritten in-place by a customized
  skill with the same name.

### Broadcast from pool (pool → workspace)

To use a pool skill in a workspace, broadcast it:

1. Go to the **Skill Pool** page in the Console.
2. Browse the pool and click **Broadcast** on the skill you want.
3. Select target workspace(s) and confirm.
4. The skill is copied into the workspace's `skills/` directory, **disabled by default**.
5. Enable it with the toggle on the **Agent → Skills** page.

If a skill with the same name already exists in the workspace, the broadcast
will report a conflict and suggest a renamed alternative.

The workspace tracks the relationship via `sync_to_pool`:

| Status       | Meaning                                                         |
| ------------ | --------------------------------------------------------------- |
| `synced`     | Workspace copy matches the pool version                         |
| `not_synced` | No corresponding pool entry (e.g. created locally)              |
| `conflict`   | Both exist but content differs (locally edited after broadcast) |

### Upload to pool (workspace → pool)

To share a workspace skill across agents, upload it to the pool:

1. On the **Agent → Skills** page, click **Upload**.
2. Select the skill(s) you want to upload and confirm.
3. If a pool skill with the same name exists, rename or delete the existing one first.
4. After upload, the workspace entry is marked `synced` with a link to the pool copy.

If a builtin with the same name already exists, upload/create/save will report
a conflict. Save it under a different name, or delete the builtin first if you
really want a customized replacement with the same name.

### Importing built-in skills

When CoPaw is upgraded, packaged built-in skills under `src/` may be newer than
what is in your local pool, or some builtins may have been deleted from the
pool intentionally.

To import built-ins from source into the pool:

1. Go to the Skill Pool page in the Console.
2. Click **Import Builtin**.
3. Select the builtins you want to import and confirm.
4. Missing builtins are copied into the pool. Builtins already up-to-date are
   left unchanged. Builtins whose pool copy differs from the packaged version
   are reported as conflicts — approve to overwrite, or skip to keep the
   current copy.

To update a single outdated builtin, click **Update** on its card in the pool
page.

You can also delete a builtin from the pool and import it back later.

---

## Import skills

You can import skills from these URL sources in the Console:

- `https://skills.sh/...`
- `https://clawhub.ai/...`
- `https://skillsmp.com/...`
- `https://lobehub.com/...`
- `https://market.lobehub.com/...` (LobeHub direct download endpoint)
- `https://github.com/...`
- `https://modelscope.cn/skills/...`

### Steps

1. Open the [Console](./console) → **Agent → Skills**, click **Import Hub**.

   ![skill](https://img.alicdn.com/imgextra/i2/O1CN01gQN4gv1HCj5HVBeq1_!!6000000000722-2-tps-3410-1978.png)

2. Paste a skill URL in the pop-up window (see the **URL acquisition example** below for the acquisition method).

   ![url](https://img.alicdn.com/imgextra/i1/O1CN01YSoLHy1dZ5yWnMM3N_!!6000000003749-2-tps-3410-1978.png)

3. Confirm and wait for import to finish.

   ![click](https://img.alicdn.com/imgextra/i4/O1CN013idFsl1CiGHBEIWx2_!!6000000000114-2-tps-3410-1978.png)

4. After a successful import, the newly added skills can be seen in the Skill list.

   ![check](https://img.alicdn.com/imgextra/i1/O1CN014LNdGd1wFNcq6JWbY_!!6000000006278-2-tps-3410-1978.png)

### URL acquisition examples

1. Use `skills.sh` as an example (the same URL acquisition flow applies to `clawhub.ai`, `skillsmp.com`, `lobehub.com`, and `modelscope.cn`): open the corresponding marketplace page.
2. Pick the skill you need (for example, `find-skills`).

   ![find](https://img.alicdn.com/imgextra/i4/O1CN015bgbAR1ph8JbtTsIY_!!6000000005391-2-tps-3410-2064.png)

3. Copy the URL from the top address bar; this is the Skill URL used for import.

   ![url](https://img.alicdn.com/imgextra/i2/O1CN01d1l5kO1wgrODXukNV_!!6000000006338-2-tps-3410-2064.png)

   LobeHub also exposes a direct download endpoint on `https://market.lobehub.com/...`, and that URL is accepted as well.

4. To import Skills from GitHub, open a page that contains `SKILL.md` (for example, `skill-creator` in the anthropics skills repo), then copy the URL from the top address bar.

   ![github](https://img.alicdn.com/imgextra/i2/O1CN0117GbZa1lLN24GNpqI_!!6000000004802-2-tps-3410-2064.png)

### Notes

- Imported skills are **disabled by default**. Enable them after import.
- If a skill with the same name already exists, import does not overwrite by default. Check the existing one in the list first.
- If import fails, first check URL completeness, supported domains, and outbound network access. If GitHub rate-limits requests, add `GITHUB_TOKEN` in Console → Settings → Environments. See GitHub docs: [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

---

## Channel routing

Each skill can be restricted to specific channels. By default, skills apply to
**all channels** (`channels: ["all"]`).

To limit a skill to certain channels:

1. In **Agent → Skills**, click the channel setting on a skill.
2. Select the channels where this skill should be active (e.g. `discord`,
   `telegram`, `console`).

When the agent runs on a given channel, only skills whose `channels` list
includes that channel (or `"all"`) are loaded. This lets you have
channel-specific skills — for example, a DingTalk-only onboarding skill that
doesn't appear on Discord.

---

## Custom skills (in the working directory)

To add your own instructions or capabilities via the file system, add a custom
skill under a workspace's `skills/` directory.

### Steps

1. Create a directory under `~/.copaw/workspaces/{agent_id}/skills/`, e.g.
   `my_skill`.
2. Add a `SKILL.md` file in that directory. The file **must** start with YAML front matter containing both `name` and `description` fields. Write Markdown body after the front matter to describe the capability for the agent. If the skill depends on external binaries or environment variables, declare them in `metadata.requires`; CoPaw exposes them as `require_bins` and `require_envs` metadata, but does not disable the skill automatically.

### Example SKILL.md

```markdown
---
name: my_skill
description: My custom capability
metadata:
  requires:
    bins: [ffmpeg]
    env: [MY_SKILL_API_KEY]
---

# Usage

This skill is used for…
```

`name` and `description` are **required**. `metadata` is optional.

Manually placed skills are detected on the next manifest reconcile and added
to `skill.json` as **disabled**. Enable them in the Console or CLI.

---

## Skill config

Each skill can have a `config` object stored in its manifest entry. This config
is not just stored metadata — when a skill is effective for the current
workspace and channel, CoPaw injects that config into the runtime environment
for that agent turn, then restores the environment after the turn completes.

You can set config per skill in the Console (**Agent → Skills** → click the
config icon on a skill) or via the API.

### How it works

Config keys that match a `metadata.requires.env` entry in SKILL.md are
injected as environment variables. Keys not declared in `requires.env` are
skipped (but still available via the full JSON variable). If a required key
is missing from the config, a warning is logged.

The full config is always available as `COPAW_SKILL_CONFIG_<SKILL_NAME>`
(JSON string), regardless of `requires.env`.

Existing host environment variables are never overwritten.

### Example

If `SKILL.md` declares:

```markdown
---
name: my_skill
description: demo
metadata:
  requires:
    env: [MY_API_KEY, BASE_URL]
---
```

And the config is:

```json
{
  "MY_API_KEY": "sk-demo",
  "BASE_URL": "https://api.example.com",
  "timeout": 30
}
```

The skill can read:

- `MY_API_KEY` ← from config, matches `requires.env`
- `BASE_URL` ← from config, matches `requires.env`
- `timeout` ← not in `requires.env`, only available via the full JSON below
- `COPAW_SKILL_CONFIG_MY_SKILL` ← full JSON config (always injected)

Python example:

```python
import json
import os

api_key = os.environ.get("MY_API_KEY", "")
base_url = os.environ.get("BASE_URL", "")
cfg = json.loads(os.environ.get("COPAW_SKILL_CONFIG_MY_SKILL", "{}"))
timeout = cfg.get("timeout", 30)
```

Config is also preserved across pool ↔ workspace sync: uploading a workspace
skill copies its config to the pool entry, and downloading copies the pool
config into the workspace entry.

### Config priority

When a skill runs, the effective config follows this priority (highest wins):

1. **Host environment** — existing env vars on the machine are never overwritten.
2. **Workspace config** — the `config` object in the workspace manifest entry (`skill.json`). This is what you edit in the Console per agent.
3. **Pool config** — when downloading a pool skill to a workspace, the pool's `config` is copied as the initial workspace config. Subsequent workspace edits take precedence.

For `requires` metadata, the parser checks keys in order: `metadata.openclaw.requires` → `metadata.copaw.requires` → `metadata.requires`. The first one found is used.

---

## Upgrading from Earlier Versions

Introduced in the latest version. Converts legacy `active_skills/` and `customized_skills/` directories into the unified workspace skill layout.

All migrations run automatically on first start. No manual file operations required.

| Before               | After                                                                    |
| -------------------- | ------------------------------------------------------------------------ |
| `active_skills/`     | Workspace `skills/` (enabled)                                            |
| `customized_skills/` | Workspace `skills/` (disabled unless also active with identical content) |

- Same skill name with **different content** in both directories: both copies kept with `-active` / `-customize` suffixes.
- Builtin skills are managed separately and always synced from the packaged version.
- To share a workspace skill across agents, upload it to the skill pool manually via the UI.

---

## Related pages

- [Introduction](./intro) — What the project can do
- [Console](./console) — Manage skills and channels in the Console
- [Channels](./channels) — Connect DingTalk, Feishu, iMessage, Discord, QQ
- [Heartbeat](./heartbeat) — Scheduled check-in / digest
- [CLI](./cli) — Cron commands in detail
- [Config & working dir](./config) — Working dir and config
