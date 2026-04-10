# Skills

**Skills** can come from packaged built-ins, the local skill pool, Skills Hub
imports, or files you add yourself.

Two ways to manage skills:

- **Console:** Use the [Console](./console) under **Workspace → Skills**.
- **Working directory:** Edit skill files directly under `$QWENPAW_WORKING_DIR`
  (default `~/.qwenpaw`), including `$QWENPAW_WORKING_DIR/skill_pool/` and each
  workspace's `$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/`.

> If you're new to channels, heartbeat, or cron, read [Introduction](./intro) first.

Skills are organized between the shared pool and each workspace's local runtime
copies. The structure and creation paths are described below.

---

## Skill Structure

QwenPaw skills are organized in two layers:

- **Skill Pool:** Shared local repository at `$QWENPAW_WORKING_DIR/skill_pool/`
  (default `~/.qwenpaw/skill_pool/`).
- **Workspace Skills:** The local runtime copy at
  `$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/`
  (default `~/.qwenpaw/workspaces/{agent_id}/skills/`).

```
$QWENPAW_WORKING_DIR/                      # Default ~/.qwenpaw
  skill_pool/                # Shared pool
    skill.json               # Pool manifest
    pdf/
      SKILL.md
    cron/
      SKILL.md
    my_shared_skill/
      SKILL.md
  workspaces/
    default/
      skill.json             # Workspace manifest
      skills/                # Runtime copies actually used by this workspace
        pdf/
          SKILL.md
        my_skill/
          SKILL.md
```

![Skill pool and workspace visual](https://img.alicdn.com/imgextra/i3/O1CN01BY2oPh1KqykMev8jC_!!6000000001216-2-tps-1919-1080.png)

### Skill Pool

The pool is where built-ins and reusable shared skills live. Pool entries are
**not executed directly** by a workspace. To use one, you must broadcast it to
a workspace first.

Pool-side operations:

- **Broadcast:** Copy a pool skill into one or more workspaces.
- **Add to pool:** Create in the pool UI, import built-ins, import from a URL,
  upload a zip, upload from a workspace, or place files on disk manually.
- **Edit / rename:** Saving a normal shared skill under the same name edits
  that pool entry in place. Saving it under a new name creates a renamed
  entry. Builtin skills cannot be customized in place under the same name. To
  customize a builtin, save it under a new name and keep the builtin slot
  untouched.
- **Conflict handling:** If save, import, upload, or broadcast would land on a
  name that already exists, QwenPaw returns a conflict instead of silently
  overwriting. The UI/API includes a suggested renamed target so you can retry
  with that name.

Adding skills to the pool:

1. **Import built-ins**.
   Built-in skill IDs come from packaged skill directory names.

   | Skill ID                      | Description                                                                                                                     | Source                                                         |
   | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
   | **browser_cdp**               | Connect to or launch Chrome with CDP / remote-debugging enabled. Use only when the user explicitly wants CDP mode.              | Built-in                                                       |
   | **browser_visible**           | Launch a real, visible (headed) browser window for demos, debugging, or scenarios requiring human interaction.                  | Built-in                                                       |
   | **channel_message**           | Proactively send a one-way message to a session or channel after first locating the target session.                             | Built-in                                                       |
   | **QA_source_index**           | Internal QwenPaw source/doc index skill for quickly mapping keywords to source paths and local docs.                            | Built-in                                                       |
   | **cron**                      | Scheduled jobs. Create, list, pause, resume, or delete jobs via `qwenpaw cron` or Console **Control → Cron Jobs**.              | Built-in                                                       |
   | **dingtalk_channel**          | Helps with DingTalk channel onboarding through a visible browser flow and required manual steps.                                | Built-in                                                       |
   | **docx**                      | Create, read, and edit Word documents (.docx), including TOC, headers/footers, tables, images, track changes, comments.         | https://github.com/anthropics/skills/tree/main/skills/docx     |
   | **file_reader**               | Read and summarize text-based files (.txt, .md, .json, .csv, .log, .py, etc.). PDF and Office are handled by dedicated skills.  | Built-in                                                       |
   | **guidance**                  | Answer QwenPaw installation and configuration questions by consulting local docs first.                                         | Built-in                                                       |
   | **himalaya**                  | Manage emails via CLI (IMAP/SMTP). Use `himalaya` to list, read, search, and organize emails from the terminal.                 | https://github.com/openclaw/openclaw/tree/main/skills/himalaya |
   | **multi_agent_collaboration** | Coordinate with another agent when the user explicitly asks for it or another agent's context is needed.                        | Built-in                                                       |
   | **news**                      | Fetch and summarize latest news from configured sites; categories include politics, finance, society, world, tech, sports, etc. | Built-in                                                       |
   | **pdf**                       | PDF operations: read, extract text/tables, merge/split, rotate, watermark, create, fill forms, encrypt/decrypt, OCR, etc.       | https://github.com/anthropics/skills/tree/main/skills/pdf      |
   | **pptx**                      | Create, read, and edit PowerPoint (.pptx), including templates, layouts, notes, and comments.                                   | https://github.com/anthropics/skills/tree/main/skills/pptx     |
   | **xlsx**                      | Read, edit, and create spreadsheets (.xlsx, .xlsm, .csv, .tsv), clean up formatting, formulas, and data analysis.               | https://github.com/anthropics/skills/tree/main/skills/xlsx     |

   In the pool UI, built-ins can show statuses such as **up-to-date** or
   **out-of-date**. Use **Update Built-in Skills** to add missing built-ins
   or refresh out-of-date ones from the packaged source.

   The **Cron** built-in provides scheduled job management. Use the
   [CLI](./cli) (`qwenpaw cron`) or Console **Control → Cron Jobs**:

   - Create: `qwenpaw cron create --type agent --name "xxx" --cron "0 9 * * *" ...`
   - List: `qwenpaw cron list`
   - Check state: `qwenpaw cron state <job_id>`

2. **Create directly in the pool UI**.
   This creates a shared pool skill without first creating it in a workspace.

3. **Import from URL into the pool**.
   The pool page also supports importing from supported Hub / GitHub URLs.

4. **Upload a zip into the pool**.
   This is useful when you already have one or more packaged skill folders.

5. **Upload from a workspace**.
   On **Workspace → Skills**, click **Sync to Skill Pool** to publish a workspace skill to the
   pool.

6. **Manual filesystem changes**.
   You can place folders directly under `$QWENPAW_WORKING_DIR/skill_pool/`, but this is not
   recommended. Direct pool edits can be lost or overwritten more easily,
   especially for customized skills. Be careful and treat this as an advanced
   workflow.

### Workspace Skills

Every workspace runs from its own local copies under
`$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/`. Those copies are what the agent
actually loads at runtime.

---

## Workspace

The normal order for creating skills in a workspace is:

### 1. From pool

This is the preferred path for both built-ins and shared reusable skills.

1. Open **Skill Pool** in the Console.
2. Click **Broadcast** on the skill you want.
3. Select target workspace(s) and confirm.
4. The skill is copied into the workspace and **enabled by default**.

If the target workspace already has a skill with the same name, broadcast
returns a conflict and suggests a renamed target.

### 2. Create via UI

In [Console](./console) → **Workspace → Skills**, you can create a skill by
entering a name and content. The new workspace skill is written into
`skills/` and `skill.json`, and is **enabled by default**.

When editing a workspace skill in the drawer, the page also provides **AI
Optimize**. This is only a **beta** feature. It may help rewrite or restructure
skill content, but it does **not** guarantee a valid or working result. Always
review the generated content manually before saving.

### 3. Import from zip

The workspace skill page also supports zip import. This is similar to adding a
skill into the pool, except the target is the current workspace. Imported
skills are **enabled by default**.

### 4. Import from URL

The workspace skill page supports importing from the following URL sources:

- `https://skills.sh/...`
- `https://clawhub.ai/...`
- `https://skillsmp.com/...`
- `https://lobehub.com/...`
- `https://market.lobehub.com/...` (LobeHub direct download endpoint)
- `https://github.com/...`
- `https://modelscope.cn/skills/...`

#### Steps

1. In [Console](./console) → **Workspace → Skills**, click **Import from Skills Hub**.

   ![skill](https://img.alicdn.com/imgextra/i1/O1CN01a1iK2K1mfoKagiCXr_!!6000000004982-2-tps-2910-1552.png)

2. Paste a skill URL in the pop-up window (see **URL acquisition example**
   below).

   ![url](https://img.alicdn.com/imgextra/i1/O1CN01PGa9Kl1pzuYoGENBi_!!6000000005432-2-tps-2940-1554.png)

3. Confirm and wait for import to finish.

   ![click](https://img.alicdn.com/imgextra/i2/O1CN01Lsn0sR27p4GcJ1Ux0_!!6000000007845-2-tps-2940-1614.png)

4. After a successful import, the skill appears in the skill list and is
   **enabled by default**.

   ![check](https://img.alicdn.com/imgextra/i1/O1CN01Dk2bKZ1kitllHcWDl_!!6000000004718-2-tps-2940-1556.png)

#### URL acquisition example

1. Open a supported marketplace page (e.g. `skills.sh`; the same flow applies
   to `clawhub.ai`, `skillsmp.com`, `lobehub.com`, `modelscope.cn`).
2. Pick the skill you need (e.g. `find-skills`).

   ![find](https://img.alicdn.com/imgextra/i4/O1CN015bgbAR1ph8JbtTsIY_!!6000000005391-2-tps-3410-2064.png)

3. Copy the URL from the address bar — this is the Skill URL used for import.

   ![url](https://img.alicdn.com/imgextra/i2/O1CN01d1l5kO1wgrODXukNV_!!6000000006338-2-tps-3410-2064.png)

   LobeHub also exposes a direct download endpoint on
   `https://market.lobehub.com/...`, which is accepted as well.

4. To import from GitHub, open a page containing `SKILL.md` (e.g.
   `skill-creator` in the anthropics skills repo) and copy the URL.

   ![github](https://img.alicdn.com/imgextra/i2/O1CN0117GbZa1lLN24GNpqI_!!6000000004802-2-tps-3410-2064.png)

#### Notes

- If a skill with the same name already exists, import does not overwrite.
  Check the existing one first.
- If import fails, check URL completeness, supported domains, and outbound
  network access. If GitHub rate-limits requests, add `GITHUB_TOKEN` in
  Console → Settings → Environments. See GitHub docs:
  [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

### 5. Create manually in the workspace

You can also create a workspace skill directly by writing files under
`$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/`, including using QwenPaw itself to help
generate those files.

This is flexible, but the write location and resulting skill quality are not
always fully controlled. You should supervise the creation process carefully,
verify that files land in the right workspace path, and review the skill
content before relying on it.

Create a directory under `$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/`, add a
`SKILL.md`, and make sure it includes YAML front matter with `name` and
`description`. If the skill depends on external binaries or environment
variables, declare them in `metadata.requires`; QwenPaw exposes them as
`require_bins` and `require_envs` metadata, but does not disable the skill
automatically.

#### Example SKILL.md

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

Common workspace operations:

- **Enable / disable:** Turn a skill on or off without changing its files.
- **Delete:** Delete a workspace skill. If the skill is currently enabled, it
  is automatically disabled first.
- **Upload to pool:** Publish a workspace skill to the shared pool for reuse by
  other workspaces.
- **Edit channel scope / config:** Adjust where the skill applies and what
  runtime config it receives in this workspace.

---

## Channel routing

Each skill can be restricted to specific channels. By default, skills apply to
**all channels** (`channels: ["all"]`).

To limit a skill to certain channels:

1. In **Workspace → Skills**, click the channel setting on a skill.
2. Select the channels where this skill should be active (e.g. `discord`,
   `telegram`, `console`).

When the agent runs on a given channel, only skills whose `channels` list
includes that channel (or `"all"`) are loaded. This lets you keep
channel-specific skills. For example, a DingTalk-only onboarding skill does
not need to appear on Discord.

---

## Skill config

Each skill can have a `config` object stored in its manifest entry. This config
is not just stored metadata. When a skill is effective for the current
workspace and channel, QwenPaw injects that config into the runtime environment
for that agent turn, then restores the environment after the turn completes.

You can set config per skill in the Console (**Workspace → Skills** → click the
config icon on a skill) or via the API.

### How it works

Config keys that match a `metadata.requires.env` entry in SKILL.md are
injected as environment variables. Keys not declared in `requires.env` are
skipped (but still available via the full JSON variable). If a required key
is missing from the config, a warning is logged.

The full config is always available as `QWENPAW_SKILL_CONFIG_<SKILL_NAME>`
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

- `MY_API_KEY` comes from config and matches `requires.env`.
- `BASE_URL` comes from config and matches `requires.env`.
- `timeout` is not in `requires.env`, so it is only available via the full
  JSON below.
- `QWENPAW_SKILL_CONFIG_MY_SKILL` always contains the full JSON config.

Python example:

```python
import json
import os

api_key = os.environ.get("MY_API_KEY", "")
base_url = os.environ.get("BASE_URL", "")
cfg = json.loads(os.environ.get("QWENPAW_SKILL_CONFIG_MY_SKILL", "{}"))
timeout = cfg.get("timeout", 30)
```

Config is also preserved across pool ↔ workspace sync: uploading a workspace
skill copies its config to the pool entry, and downloading copies the pool
config into the workspace entry.

### Config priority

When a skill runs, the effective config follows this priority (highest wins):

1. **Host environment:** Existing env vars on the machine are never
   overwritten.
2. **Workspace config:** The `config` object in the workspace manifest entry
   (`skill.json`). This is what you edit in the Console per agent.
3. **Pool config:** When downloading a pool skill to a workspace, the pool's
   `config` is copied as the initial workspace config. Subsequent workspace
   edits take precedence.

For `requires` metadata, the parser checks keys in order: `metadata.openclaw.requires` → `metadata.qwenpaw.requires` → `metadata.requires`. The first one found is used.

---

## Upgrading from Earlier Versions

Converts legacy `active_skills/` and `customized_skills/` directories into the
unified workspace `skills/` layout.

Migration runs automatically on first start. Skills are **copied**, not moved —
the original `active_skills/` and `customized_skills/` directories are
preserved. Back up any important custom skill content before upgrading.
Migration reduces manual work, but you should still manage valuable skills
carefully and keep your own copies when needed. After verifying the migration
result, you can manually delete the old directories. **Skills in the old
`active_skills/` and `customized_skills/` directories are no longer read.**

| Before               | After                                                                    |
| -------------------- | ------------------------------------------------------------------------ |
| `active_skills/`     | Workspace `skills/` (enabled)                                            |
| `customized_skills/` | Workspace `skills/` (disabled unless also active with identical content) |

If the same skill name exists in both directories with **different content**,
both copies are kept with `-active` / `-customize` suffixes. To share a
workspace skill across agents, upload it to the skill pool via the UI.

---

## Related pages

- [Introduction](./intro) — What the project can do
- [Console](./console) — Manage skills and channels in the Console
- [Channels](./channels) — Connect DingTalk, Feishu, iMessage, Discord, QQ
- [Heartbeat](./heartbeat) — Scheduled check-in / digest
- [CLI](./cli) — Cron commands in detail
- [Config & working dir](./config) — Working dir and config
