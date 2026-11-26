# Backup & Restore

**Backup & Restore** lets you create snapshots of your QwenPaw instance: visually create, export, import, and restore your entire agent environment. It is designed for scenarios such as **rolling back before a version upgrade, migrating between machines, or keeping a safety net before risky changes**.

> Sidebar: **Settings → Backup**

---

## What's Inside a Backup

A backup is a single zip file (stored at `~/.qwenpaw.backups/<backup_id>.zip`) that may contain up to four kinds of content:

| Module               | Path                                | Actual content                                                                                                                                                                                                            |
| -------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Agent workspaces** | `~/.qwenpaw/workspaces/<agent_id>/` | Every file inside each agent's workspace, including persona, memory, skills, chat history, channel config, plus public mail configuration, local mail indexes, and `credentials.yaml` with encrypted mailbox credentials. |
| **Global settings**  | `~/.qwenpaw/config.json`            | Runtime parameters, security rules, and other global settings.                                                                                                                                                            |
| **Skill pool**       | `~/.qwenpaw/skill_pool/`            | The globally shared skill repository.                                                                                                                                                                                     |
| **Secrets**          | `~/.qwenpaw.secret/`                | **LLM provider configuration (including API keys)**, plus environment variables used by tools and skills.                                                                                                                 |

> **Not packaged**: local model weights (too large — re-download on the target machine), runtime caches, and temporary files.

The internal layout of a backup zip looks like this:

```
<backup_id>.zip
├─ meta.json                        # Backup metadata (id / name / created at / scope / agent count)
└─ data/
   ├─ config.json                   # Only present when "Global settings" is included
   ├─ workspaces/<agent_id>/...     # Packaged per the agents you selected
   ├─ skill_pool/...                # Only present when "Skill pool" is included
   └─ secrets/...                   # Only present when "Secrets" is included
```

A backup ID has the format `qwenpaw-<version>-<timestamp>-<short8>`, which makes it easy to identify the source version and creation time across machines.

> **Tip**: An LLM provider's API key belongs to **Secrets**, **not Global settings**. If you only back up the global settings without the secrets, you will need to re-enter your model API keys in the Console after restoring.

### Conversation history protection

Instance backup preserves a complete, consistent copy of every selected
agent's conversation history without requiring you to stop the service. If
history cannot be saved completely, the backup fails with an error rather than
reporting success for an archive that silently omitted conversations.

During restore, QwenPaw checks conversation history again before replacing the
workspace. If the check fails, the existing workspace remains unchanged.

---

## Creating a Backup

Console → **Settings → Backup**. Click **Create Backup** in the top-right corner. The dialog creates a **Full backup** by default; you can also switch to a **Partial backup**:

| Mode               | Behavior                                                                                                                                                                                                 |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Full backup**    | **Packages all four kinds of content in one click**: every agent workspace + global settings + skill pool + **secrets**. No checkboxes to tick, but the dialog explicitly warns about sensitive content. |
| **Partial backup** | Tick exactly what to include: ① agent workspaces (and pick which agents), ② global settings, ③ skill pool, ④ secrets. **Secrets are unchecked by default** to avoid leaking credentials by accident.     |

> Even a "Full backup" only covers the four kinds of static assets above — local model weights are never included and must be re-downloaded on the target machine.

### Full backup

![Create a full backup](https://img.alicdn.com/imgextra/i3/O1CN01nDFWLECS5DE3FPfU_!!6000000001747-2-tps-1600-1000.png)

A full backup is best used as a complete snapshot:

1. Click **Create Backup** in the top-right corner.
2. Leave the dialog in **Full backup** mode (the default) — no options to tweak.
3. Fill in the backup name and an optional description.
4. Note the red **sensitive-content warning** — a full backup also packages the secrets directory.
5. Click **Confirm**.

### Partial backup

A partial backup is best for migrating only specific modules or syncing only a few agents:

1. Click **Create Backup** and switch to **Partial backup**.
2. Tick what you need:
   - **Agent workspaces**: after enabling this, pick the specific agent workspaces to back up.
   - **Global settings**: whether to include the global settings (i.e. `config.json`).
   - **Skill pool**: whether to include the skill pool (i.e. the `skill_pool/` directory).
   - **Secrets**: whether to include the secrets (i.e. the `~/.qwenpaw.secret/` directory). Off by default; turning it on shows the same red sensitive-content warning.
3. Fill in the name and description, then click **Confirm**.

---

## Restoring a Backup

> ⚠️ Restore is **irreversible**. Read the "Pre-restore backup" section before you proceed.

### Pre-restore backup

![Create a pre-restore backup](https://img.alicdn.com/imgextra/i4/O1CN01WTOgxlegjmL3FPfU_!!6000000003383-2-tps-1600-1000.png)

When you click the **Restore** button on any backup row, QwenPaw first opens the **Pre-restore backup** dialog:

Choose **Yes, create backup first** to keep a snapshot of the current state. When that backup finishes, the restore options open; nothing has been restored yet. This automatic snapshot includes agent workspaces, global settings and the skill pool, but excludes the secrets directory. If you need to roll back secrets too, create and securely store a full backup before restoring.

### Two restore modes

Restore scope and security strategy are separate choices. Even in full mode, check whether you are keeping the current instance’s security guards and MCP configuration or restoring those settings from the backup.

| Mode               | When to use                                                       | Behavior                                                                                                                        |
| ------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **Full restore**   | Roll back completely to the moment of the backup; full migration  | Restores agents, global settings, skill pool, and secrets from the full backup, subject to the strategy for protected settings. |
| **Custom restore** | Migrate only some modules; keep modules outside the restore scope | Pick **per item** which modules and which agents to restore; anything outside the restore scope is **left untouched**.          |

### Full restore

Restores the following contents, subject to the selected strategy for protected settings:

- All agent workspaces in the current instance are overwritten by the agent workspaces contained in the backup.
- Global settings, skill pool, and secrets are replaced as well.

Steps:

1. A full backup opens with **Full restore** selected. This mode is unavailable for partial backups.
2. Manually tick "I confirm I want to restore this backup" as a second confirmation.
3. Click **Confirm** to submit the restore. If prompted to verify the backup’s origin, check it before proceeding.

![Full Restore selected for a full backup, with strategy options for security and MCP settings](https://img.alicdn.com/imgextra/i2/O1CN01w5I1hh9dkID3FPfU_!!6000000004951-2-tps-1600-1000.png)

### Custom restore

**Fine-grained control** over what gets restored, to avoid accidental deletions:

- **Pick agents one by one**: restore only the agents you tick; agents outside the restore scope are kept as they are. You can also specify the default storage location for newly added agents at restore time; if unspecified, they go to `~/.qwenpaw/workspaces/<agent_id>/`.
- **Global settings / skill pool / secrets**: each can be toggled independently. If toggled on, it fully replaces the current instance's content.

Steps:

1. A partial backup opens in **Custom restore**. For a full backup, switch to this mode. Only modules included in the backup are shown.
2. Fill in the default location for new agents (only when the backup contains agents not yet on this machine).
3. Tick the agents you want to restore in the agent list.
4. Decide whether to restore the global settings / skill pool / secrets.
5. Review the scope and security strategy, tick the restore confirmation, then click **Confirm**.

![Custom restore options for a partial backup containing one agent workspace and global settings](https://img.alicdn.com/imgextra/i2/O1CN01MGCfmrebkYD3FPfU_!!6000000006266-2-tps-1600-1000.png)

---

## Export / Import / Delete

| Action     | Description                                                                                                                                                                                                      |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Export** | Click **Export** on a row to download the backup's `.zip` file — handy for archiving or moving it to another machine.                                                                                            |
| **Import** | Click **Import Backup** at the top of the page and pick a local `.zip` file. If the backup ID conflicts with an existing one, an **overwrite confirmation** appears — confirm to overwrite without re-uploading. |
| **Delete** | Delete a single backup or batch-delete by selection; the underlying zip file on disk is removed immediately.                                                                                                     |

---

## Security Notes

- Backup files **may contain sensitive credentials**: a full backup may package model API keys, the encryption master key, Console login credentials, and other secrets. Even a partial backup that includes an agent workspace can contain channel credentials (`bot_token`, `app_secret`, etc.) and encrypted mailbox credentials in `credentials.yaml`. `agent.json` and `drivers/mcp/qwenpawmail.yaml` no longer store a plaintext mailbox authorization code, but any backup containing both encrypted credentials and decryption material remains highly sensitive. **Keep backup files safe and do not share them with others.**
- When migrating across machines, **local model weights are not included** — re-download the models you need on the target machine.
- **Restart the service** after a restore so the new configuration takes full effect.

---

## Typical Use Cases

| Scenario                          | Recommended action                                                                               |
| --------------------------------- | ------------------------------------------------------------------------------------------------ |
| Before a major version upgrade    | Create a "Full backup" so you can roll back in one click if the upgrade goes wrong               |
| Before risky/experimental changes | Create a backup before the change. If you restore later, take another snapshot before restoring. |
| Migrating only some agents        | Create a partial backup with only the agents you need, and use **Custom restore** when restoring |

---

## Backup File Storage

| Item             | Path / Default                 |
| ---------------- | ------------------------------ |
| Backup directory | `~/.qwenpaw.backups/`          |
| Single backup    | `<backup-dir>/<backup_id>.zip` |

---

## Notes for Docker Users

The backup directory inside a Docker container is `/app/working.backups`. If you deploy with Docker, you need to mount this directory to persist backup data — otherwise all backups will be lost when the container is recreated.

Add `-v qwenpaw-backups:/app/working.backups` to your `docker run` command:

```bash
docker run -p 127.0.0.1:8088:8088 \
  -v qwenpaw-data:/app/working \
  -v qwenpaw-secrets:/app/working.secret \
  -v qwenpaw-backups:/app/working.backups \
  agentscope/qwenpaw:latest
```

---

## FAQ

**Q: Will the backup include local models I downloaded?**
A: No. Models are too large; backups only cover small assets such as configuration, skills, and memory. Re-download the models you need after migrating to a new machine.

**Q: I see "Backup already exists" when importing — what should I do?**
A: QwenPaw shows an overwrite confirmation; confirm it to continue importing and overwrite the existing backup.

**Q: What's the real difference between Full restore and Custom restore?**
A: Full restore uses all modules in a full backup. Custom restore applies only to the selected modules and agents. In both cases the restore strategy determines whether local security guards and MCP settings are preserved.

---

## Related Pages

- [Console](./console) — the Backup page lives in the "Settings" group
- [Configuration & Working Directory](./config) — `config.json`, working directory, environment variables
- [Multi-Agent](./multi-agent) — agent workspace structure
- [Skills](./skills) — relationship between the skill pool and per-agent skills
- [Mailbox Management](./mailbox) — mailbox credentials and workspace state files
