# Console

The **Console** is CoPaw's built-in web interface. After running `copaw app`,
open `http://127.0.0.1:8088/` in your browser to enter the Console.

**In the Console, you can:**

- Chat with CoPaw in real time
- Enable/disable/configure messaging channels
- View and manage all chat sessions
- Manage scheduled jobs and heartbeat
- Edit CoPaw's persona and behavior files
- Enable/import skills to extend CoPaw's capabilities
- Toggle tools on or off
- Manage MCP clients
- Modify runtime configuration
- Manage multiple agents
- Configure LLM providers and select models
- Manage environment variables required by tools
- Manage security options for tools and skills
- View LLM token usage statistics
- Configure how voice messages are handled

The sidebar on the left groups features into **Chat**, **Control**, **Agent**,
and **Settings**. Click any item to switch pages. The sections below walk
through each feature in order.

> **Not seeing the Console?** Make sure the frontend has been built. See
> [CLI](./cli).

---

## Chat

> Sidebar: **Chat → Chat**

This is where you talk to CoPaw. It is the default page when the Console
opens.

![Chat](https://img.alicdn.com/imgextra/i4/O1CN01iuGyNc1mNwsUU5NQI_!!6000000004943-2-tps-3822-2070.png)

**Choose a model:**
Use the control at the top-left of the chat page to pick the model for the
current agent.

**Send a message:**
Type in the input box at the bottom, then press **Enter** or click the send
button (↑). CoPaw replies in real time.

**Voice input:**
The composer supports **voice input** (browser and OS microphone permission
required). Behavior matches **Voice transcription** settings (e.g. transcribe
first, then send text to the model).

**Attachments:**
You can attach **files** such as documents, images, and audio/video (follow
on-screen limits; per-file size caps apply).

**Create a new session:**
Click the **+ New Chat** button at the top of the chat sidebar to start a new
conversation. Each session keeps separate history.

**Switch sessions:**
Click any session name in the chat sidebar to load its history.

**Delete a session:**
Click the **···** button on a session item, then click the **trash** icon.

---

## Channels

> Sidebar: **Control → Channels**

Manage messaging channels (Console, DingTalk, Feishu, Discord, QQ, WeChat,
iMessage, etc.): enable/disable and credentials.

![Channels](https://img.alicdn.com/imgextra/i4/O1CN01tUJBg121ZbBnC5fjx_!!6000000006999-2-tps-3822-2070.png)

**Enable a channel:**

1. Click the channel card you want to configure.
2. A settings panel slides out on the right. Turn on **Enable**.

   ![Channel Configuration](https://img.alicdn.com/imgextra/i1/O1CN01dbZiw21S5MUOUFJ06_!!6000000002195-2-tps-3822-2070.png)

3. Fill in required credentials — each channel differs; see [Channels](./channels).

4. Click **Save**. Changes take effect in seconds, no restart required.

**Disable a channel:**
Open the same panel, turn off **Enable**, then click **Save**.

> For credential setup details, see [Channels](./channels).

---

## Sessions

> Sidebar: **Control → Sessions**

View, filter, and clean up chat sessions across all channels.

![Sessions](https://img.alicdn.com/imgextra/i2/O1CN0142DXNW1NkyOX07sJ7_!!6000000001609-2-tps-3822-2070.png)

**Find sessions:**
Use the search box to filter by user, or use the dropdown to filter by
channel. The table updates immediately.

**Rename a session:**
Click **Edit** on a row → change the name → click **Save**.

**Delete one session:**
Click **Delete** on a row → confirm.

**Batch delete:**
Select rows → click **Batch Delete** → confirm.

---

## Cron Jobs

> Sidebar: **Control → Cron Jobs**

Create and manage scheduled jobs that CoPaw runs automatically by time.

![Cron Jobs](https://img.alicdn.com/imgextra/i3/O1CN01JET1Aw1C9SAvXuIpk_!!6000000000038-2-tps-3822-2070.png)

**Create a new job:**

> If the cron job fails to be created, please refer to the **Troubleshooting Scheduled (Cron) Tasks** section in the [FAQ](https://copaw.agentscope.io/docs/faq) to identify the cause.

The **simplest way to create a cron job is to chat directly with CoPaw** and let it handle the creation for you. For example, if you want to receive a reminder to drink water on DingTalk, simply message CoPaw on DingTalk: "Help me create a cron job to remind me to drink water every 5 minutes." Once created, you can view the new task on the Cron Jobs page in the console.

Alternatively, you can create tasks directly via the Console interface:

1. Click **+ Create Job**.

   ![Create Cron Job](https://img.alicdn.com/imgextra/i2/O1CN01jFAcIZ1wCAqyxDGKX_!!6000000006271-2-tps-3822-2070.png)

2. Fill in each section:
   - **Basic info** — Job ID (e.g. `job-001`), display name (e.g. "Daily summary"),
     and enable the job.
   - **Schedule** — Pick a schedule; if presets are not enough, enter a **cron
     expression** (five fields, e.g. `0 9 * * *` = 9:00 daily). Timezone defaults
     to the current agent's user timezone; you can change it here.
   - **Task type & content** — **Text**: send fixed text from **Message content**.
     **Agent**: fill **Request content**; on each run CoPaw receives the text
     from `content.text` as the request.
   - **Delivery** — Target channel (Console, DingTalk, etc.), target user,
     target session id, and mode (**Stream** = token stream, **Final** = one
     complete reply).
   - **Advanced** — Optional: max concurrency, timeout, misfire grace time.
3. Click **Save**.

**Enable/disable a job:**
Toggle the switch in the row.

**Edit a job:**
**Disable** the job first, click **Edit** → change fields → **Save**.

**Run once immediately:**
Click **Execute Now** → confirm.

**Delete a job:**
**Disable** the job first, click **Delete** → confirm.

---

## Heartbeat

> Sidebar: **Control → Heartbeat**

<!--TODO: figure-->

Configure periodic "self-check" for the **currently selected agent**: on each
tick, send the contents of `HEARTBEAT.md` as a user message to CoPaw, and
optionally deliver the reply to a target.

**Common options:**

- **Enable** — Must be on for the schedule to run.
- **Interval** — Number + unit (minutes / hours).
- **Delivery target** — `main` runs in the main session only; `last` can send
  results to the channel from your last user conversation.
- **Active hours** (optional) — Only fire within a daily window to avoid night
  noise.

Click **Save** to apply. See [Heartbeat](./heartbeat) for semantics and file
layout.

---

## Workspace

> Sidebar: **Agent → Workspace**

Edit files that define CoPaw's persona and behavior — `SOUL.md`, `AGENTS.md`,
`HEARTBEAT.md`, etc. — directly in the browser.

> **Multi-agent:** Starting from **v0.1.0**, CoPaw supports **multi-agent**
> mode. You can run multiple independent agents in one CoPaw instance, each with
> its own workspace, configuration, memory, and history. Agents can collaborate.
> Use the agent switcher at the top to change the active agent. See
> [Multi-Agent](./multi-agent).

![Workspace](https://img.alicdn.com/imgextra/i3/O1CN01APrwdP1NqT9CKJMFt_!!6000000001621-2-tps-3822-2070.png)

**Edit files:**

1. Click a file in the list (e.g. `SOUL.md`).
2. The editor shows file content. Turn off preview if needed, then edit.
3. Click **Save** to apply, or **Reset** to discard and reload.

**View daily memory:**
If `MEMORY.md` exists, click the **▶** arrow to expand date-based entries.
Click a date to view or edit that day's memory.

**Download workspace:**
Click **Download** (⬇) to export the entire workspace as a `.zip`.

**Upload/restore workspace:**
Click **Upload** (⬆) → choose a `.zip` (max 100 MB). Existing workspace files
will be replaced. Useful for migration and backup restore.

---

## Skills

<!--TODO: revise after Skill Hub changes-->

> Sidebar: **Agent → Skills**

Manage skills that extend CoPaw (e.g. read PDF, create Word, fetch news).

![Skills](https://img.alicdn.com/imgextra/i1/O1CN01ZF4kVc1Yz8PlPdiM6_!!6000000003129-2-tps-3822-2070.png)

**Enable a skill:**
Click **Enable** at the bottom of a skill card. It takes effect immediately.

**Disable a skill:**
Click **Disable**. It also takes effect immediately.

**View skill details:**
Click a skill card for the full description.

**Edit a skill:**

<!--TODO: edit details-->

**Import from Skill Hub:**

1. Click **Import Skill**.
2. Enter a skill URL, then import.
3. Wait for completion; the skill appears enabled in the list.

**Upload a skill:**

1. Click **Upload Skill**.
2. Choose a skill **zip** file.
3. Click **Open**; on success the skill appears in the list.

**Create a custom skill:**

1. Click **Create Skill**.
2. Enter a skill name (e.g. `weather_query`) and skill content in Markdown
   (must include `name` and `description`).
3. Click **Save**. The new skill appears immediately.

![Create Skill](https://img.alicdn.com/imgextra/i3/O1CN01hW0eLY1go9qeiPrUF_!!6000000004188-2-tps-3822-2070.png)

**Delete a custom skill:**
Disable the skill first, then click the **🗑** icon on its card and confirm.

> For built-in skills, Skill Hub import, and authoring, see [Skills](./skills).

---

<!--TODO: add skill hub-->

## Tools

> Sidebar: **Agent → Tools**

<!--TODO: figure-->

Toggle **built-in tools** by name (read files, run commands, browser, etc.).
When off, this agent cannot call that tool in chat.

Use **Enable all** / **Disable all** at the top for batch changes. Changes apply
to the **current agent** immediately.

---

## MCP

> Sidebar: **Agent → MCP**

Enable/disable/delete **MCP** clients here, or create new ones.

![MCP](https://img.alicdn.com/imgextra/i4/O1CN01ANXnQQ1IfPVO6bEbY_!!6000000000920-2-tps-3786-1980.png)

**Create a client**
Click **Create Client** in the top-right, fill in required fields, then **Create**.
The new client appears in the list.

---

## Runtime Config

> Sidebar: **Agent → Runtime Config**

![Runtime Config](https://img.alicdn.com/imgextra/i3/O1CN01mhPcqC1KzgGYJQgkW_!!6000000001235-2-tps-3786-1980.png)

This page configures **runtime parameters for the current agent**, grouped in
cards. Click **Save** at the bottom (**Reset** reloads from the server).

- **ReAct Agent** — UI language, user timezone, **max iterations**.
- **Context** — Max input length, compaction ratio, etc.
- **LLM retries** — Whether to retry on failure, count, backoff.

For mechanics, see [Context](./context) and [Config & working directory](./config).

---

## Agent management

> Sidebar: **Settings → Agent management**

<!--TODO: figure-->

Create, edit, enable/disable, or delete agents. The **Description** field is
used when multiple agents collaborate — write a clear role.

The global **agent switcher** at the top picks which agent you are editing; this
page edits each agent's metadata (name, description, custom workspace path,
etc.). See [Multi-Agent](./multi-agent).

---

## Models

> Sidebar: **Settings → Models**

Configure LLM providers and choose the **global default** model. New agents use
this default; you can override the model per agent in the top-left control on
the Chat page.

CoPaw supports cloud providers (API key) and local providers (no API key). See
[Models](./models) for details.

![Models](https://img.alicdn.com/imgextra/i2/O1CN01Kd3lg91HdkS5SaLoF_!!6000000000781-2-tps-3822-2070.png)

### Cloud providers

**Configure a provider:**

1. Click **Settings** on a provider card (ModelScope, DashScope).
2. Enter your **API Key**.
3. Click **Save**. Card status becomes "Authorized".
4. To add a custom provider, click **Add Provider**.
5. Enter provider ID, display name, and required fields, then **Create**.
6. Open **Settings** for the new provider, fill required fields, **Save**. Status
   becomes "Authorized".

**Revoke authorization:**
Open the provider settings dialog and click **Revoke Authorization**. API key
data is cleared. If this provider is currently active, model selection is also
cleared.

### Local providers (llama.cpp / MLX)

Local providers show a purple **Local** tag. Install backend dependencies
first (`pip install 'copaw[llamacpp]'` or `pip install 'copaw[mlx]'`).

**Download a model:**

1. Click **Manage Models** on a local provider card.
2. Click **Download Model**, then fill:
   - **Repo ID** (required) — e.g. `Qwen/Qwen3-4B-GGUF`
   - **Filename** (optional) — leave empty for auto-selection
   - **Source** — Hugging Face (default) or ModelScope
3. Click **Download** and wait for completion.

**View and delete models:**
Downloaded models are listed with file size, source badge (**HF** / **MS**),
and delete button.

### Ollama provider

The Ollama provider integrates with your local Ollama daemon and dynamically
loads models from it.

**Prerequisites:**

- Install Ollama from [ollama.com](https://ollama.com)
- Install the Ollama SDK: `pip install 'copaw[ollama]'` (or re-run the installer with `--extras ollama`)

**Download a model:**

1. Click **Settings** on the Ollama provider card.
2. In **API Key**, enter a value (for example `ollama`), then click **Save**.
3. Click **Manage Models** on the Ollama card, click **Download Model**, and
   enter a model name (e.g. `mistral:7b`, `qwen3:8b`).
4. Click **Download Model** and wait for completion.

**Cancel a download:**
During download, click **✕** next to the progress indicator to cancel.

**View and delete models:**
Downloaded models are listed with size and delete button. The list updates
automatically when models are added/removed via Ollama CLI or Console.

**How it differs from local providers:**

- Models come from the Ollama daemon (not downloaded directly by CoPaw)
- Model list is auto-synced with Ollama
- Popular model examples: `mistral:7b`, `qwen3:8b`

> You can also manage Ollama models via Ollama CLI: `ollama pull`,
> `ollama list`, `ollama rm`. See [Ollama CLI](https://docs.ollama.com/cli).

> ⚠️ **Before running CoPaw, you must set the context length to 32K or higher**
>
> To run CoPaw properly, you must set the model context length to
> **32K or higher**. Note that this can consume substantial compute resources,
> so make sure your local machine can handle it.
>
> ![Ollama context length configuration](https://img.alicdn.com/imgextra/i3/O1CN01JrqRjE1l6FxuO3IMl_!!6000000004769-2-tps-699-656.png)

### LM Studio provider

The LM Studio provider connects to the LM Studio desktop application's
OpenAI-compatible local server to discover and use loaded models.

**Prerequisites:**

- Install LM Studio from [lmstudio.ai](https://lmstudio.ai)
- Load a model and start the local server in LM Studio (default: `http://localhost:1234`)

**Configure:**

1. Click **Settings** on the LM Studio provider card.
2. The default Base URL is `http://localhost:1234/v1`. Adjust if needed, then
   click **Save**.
3. Click **Manage Models** to see models loaded in LM Studio. You can also
   manually add model IDs.
4. Select **LM Studio** in the **Provider** dropdown and pick a model.

> LM Studio does not require an API key by default. Models must be loaded
> in LM Studio before they appear in CoPaw.

> ⚠️ **Before running CoPaw, you must set the context length to 32K or higher**
>
> To run CoPaw properly, you must set the model context length to
> **32K or higher**. Note that this can consume substantial compute resources,
> so make sure your local machine can handle it.
>
> ![LM Studio context length configuration](https://img.alicdn.com/imgextra/i4/O1CN01LWyG6o21E4Zovqv4G_!!6000000006952-2-tps-923-618.png)

### Choose the active model

1. Under **LLM config**, select a **Provider** (only authorized providers or
   local providers with downloaded models).
2. Select a **Model**.
3. Click **Save**.

> **Note:** Cloud API key validity is your responsibility. CoPaw does not
> verify key correctness.
>
> For provider details, see [Config — LLM Providers](./config#llm-providers).

---

## Environment Variables

> Sidebar: **Settings → Environment Variables**

Manage runtime environment variables needed by CoPaw tools and skills
(for example, `TAVILY_API_KEY`).

![Environments](https://img.alicdn.com/imgextra/i1/O1CN01jNMeBA1nMP9tQdTmU_!!6000000005075-2-tps-3822-2070.png)

**Add a variable:**

1. Click **+ Add Variable**.
2. Enter the variable name (e.g. `TAVILY_API_KEY`) and value.
3. Click **Save**.

**Edit a variable:**
Change the **Value** field, then click **Save**.
(Variable names are read-only after save; to rename, delete and recreate.)

**Delete a variable:**
Click the **🗑** icon on a row, then confirm if prompted.

**Batch delete:**
Select rows → click **Delete** in the toolbar → confirm.

> **Note:** Variable validity is your responsibility. CoPaw only stores and
> loads values.
>
> See [Config — Environment variables](./config#environment-variables).

---

## Security

> Sidebar: **Settings → Security**

<!--TODO: figure-->

Tabs for **tool guard**, **file guard**, **skill scanner**, etc.: control
dangerous-tool parameter blocking, sensitive path access, and skill package
scanning policy.

Click **Save** after changing toggles or rules. Details: [Security](./security).

---

## Token Usage

> Sidebar: **Settings → Token Usage**

<!--TODO: figure-->

View LLM token usage over a range, by date and model.

**View usage:**

1. Select a date range (default: last 30 days).
2. Click **Refresh** to fetch data.
3. The page shows total tokens, total calls, and breakdowns by model and date.

**Query via chat:**

Ask e.g. "How many tokens have I used?" or "Show token usage." The agent calls
`get_token_usage` and returns stats.

> Data is stored in `~/.copaw/token_usage.json`. Override the filename with
> `COPAW_TOKEN_USAGE_FILE`. See [Config — Environment variables](./config#environment-variables).

---

## Voice transcription

> Sidebar: **Settings → Voice transcription**

<!--TODO: figure-->

Configure how **voice/audio from channels** is handled before it reaches the
model (same settings apply to voice input in chat and channel voice messages).

- **Audio mode** — **Auto**: transcribe per settings below, then send text
  (works for most models). **Native**: send audio as an attachment (only for
  models that support audio).
- **Transcription backend** — **Off**; **Whisper API** (OpenAI-compatible
  `audio/transcriptions`; configure keys under [Models](#models) and select the
  provider here); **Local Whisper** (requires `ffmpeg` and
  `pip install 'copaw[whisper]'`).

**Save** applies to newly received audio. Follow on-page help for details.

---

## Quick Reference

| Page                  | Sidebar path                     | What you can do                                |
| --------------------- | -------------------------------- | ---------------------------------------------- |
| Chat                  | Chat → Chat                      | Chat, voice, attachments, sessions             |
| Channels              | Control → Channels               | Enable/disable, credentials                    |
| Sessions              | Control → Sessions               | Filter, rename, delete                         |
| Cron Jobs             | Control → Cron Jobs              | Create/edit/delete, run now                    |
| Heartbeat             | Control → Heartbeat              | Interval, delivery target, active hours        |
| Workspace             | Agent → Workspace                | Persona files, memory, upload/download         |
| Skills                | Agent → Skills                   | Enable/disable, Hub/upload/custom              |
| Tools                 | Agent → Tools                    | Toggle built-in tools by name                  |
| MCP                   | Agent → MCP                      | MCP clients                                    |
| Runtime Config        | Agent → Runtime Config           | Iterations, context, retries, compaction, etc. |
| Agent management      | Settings → Agent management      | CRUD agents, enable/disable                    |
| Models                | Settings → Models                | Providers, local models, active model          |
| Environment Variables | Settings → Environment Variables | Keys for tools/skills                          |
| Security              | Settings → Security              | Tool guard, skill scan, file guard             |
| Token Usage           | Settings → Token Usage           | Usage by date/model                            |
| Voice transcription   | Settings → Voice transcription   | Audio mode, Whisper API/local                  |

---

## Related Pages

- [Config & working directory](./config) — Config fields, providers, env vars
- [Channels](./channels) — Per-channel setup and credentials
- [Skills](./skills) — Built-in skills and custom skills
- [Heartbeat](./heartbeat) — Heartbeat configuration
- [Context](./context) — Compaction and context
- [Security](./security) — Web login, tool guard, file guard
- [CLI](./cli) — Command-line reference
- [Multi-Agent](./multi-agent) — Multi-agent setup, management, collaboration
