# Quick start

This section describes four ways to run CoPAW:

- **Option A — One-line install (recommended)**: run on your machine with no Python setup required.
- **Option B — pip install**: if you prefer managing Python yourself.
- **Option C — ModelScope Studio**: one-click cloud deploy, no local install needed.
- **Option D — Alibaba Cloud ECS**: one-click deploy on Alibaba Cloud, no local install.

> 📖 Read [Introduction](./intro) first; after install see [Console](./console).

> 💡 **After install & start**: Before configuring channels, you can open the [Console](./console) (`http://127.0.0.1:8088/`) to chat with CoPAW and configure the agent. When you're ready to chat in DingTalk, Feishu, QQ, etc., head to [Channels](./channels) to add a channel.

---

## Option A: One-line install (recommended)

No Python required — the installer handles everything automatically using [uv](https://docs.astral.sh/uv/).

### Step 1: Install

**macOS / Linux:**

```bash
curl -fsSL https://copaw.agentscope.io/install.sh | bash
```

Then open a new terminal (or `source ~/.zshrc` / `source ~/.bashrc`).

**Windows (PowerShell):**

```powershell
irm https://copaw.agentscope.io/install.ps1 | iex
```

Then open a new terminal (the installer adds CoPaw to your PATH automatically).

You can also pass options:

**macOS / Linux:**

```bash
# Install a specific version
curl -fsSL ... | bash -s -- --version 0.0.2

# Install from source (dev/testing)
curl -fsSL ... | bash -s -- --from-source

# With local model support (see Local Models docs)
bash install.sh --extras llamacpp    # llama.cpp (cross-platform)
bash install.sh --extras mlx         # MLX (Apple Silicon)
```

**Windows (PowerShell):**

```powershell
# Install a specific version
.\install.ps1 -Version 0.0.2

# Install from source (dev/testing)
.\install.ps1 -FromSource

# With local model support (see Local Models docs)
.\install.ps1 -Extras llamacpp      # llama.cpp (cross-platform)
.\install.ps1 -Extras mlx           # MLX
```

To upgrade, simply re-run the install command. To uninstall, run `copaw uninstall`.

### Step 2: Init

Generate `config.json` and `HEARTBEAT.md` in the working directory (default
`~/.copaw`). Two options:

- **Use defaults** (no prompts; good for getting running first, then editing
  config later):
  ```bash
  copaw init --defaults
  ```
- **Interactive** (prompts for heartbeat interval, target, active hours, and
  optional channel and Skills setup):
  ```bash
  copaw init
  ```
  See [CLI - Getting started](./cli#getting-started).

To overwrite existing config, use `copaw init --force` (you will be prompted).
After init, if no channel is enabled yet, follow [Channels](./channels) to add
DingTalk, Feishu, QQ, etc.

### Step 3: Start the server

```bash
copaw app
```

The server listens on `127.0.0.1:8088` by default. If you have already
configured a channel, CoPaw will reply there; otherwise you can add one after
this step via [Channels](./channels).

---

## Option B: pip install

If you prefer managing Python yourself (requires Python >= 3.10, < 3.14):

```bash
pip install copaw
```

Optional: create and activate a virtualenv first (`python -m venv .venv`, then
`source .venv/bin/activate` on Linux/macOS or `.venv\Scripts\Activate.ps1` on Windows). This installs the `copaw` command.

Then follow [Step 2: Init](#step-2-init) and [Step 3: Start the server](#step-3-start-the-server) above.

---

## Option C: ModelScope Studio one-click setup (no install)

If you prefer not to install Python locally, you can deploy CoPaw to ModelScope Studio's cloud:

1. First, sign up and log in at [ModelScope](https://modelscope.cn/register?back=%2Fhome);
2. Open the [CoPaw Studio](https://modelscope.cn/studios/fork?target=AgentScope/CoPaw) and complete the one-click setup.

**Important**: Set your Studio to **non-public**, or others may control your
CoPaw.

---

## Option D: Deploy on Alibaba Cloud ECS

To run CoPaw on Alibaba Cloud, use the ECS one-click deployment:

1. Open the [CoPaw on Alibaba Cloud (ECS) deployment link](https://computenest.console.aliyun.com/service/instance/create/cn-hangzhou?type=user&ServiceId=service-1ed84201799f40879884) and fill in the parameters as prompted;
2. Confirm the cost and create the instance; when deployment finishes, you can get the access URL and start using the service.

For step-by-step instructions, see [Alibaba Cloud Developer: Deploy your AI assistant in 3 minutes](https://developer.aliyun.com/article/1713682).

---

## Verify install (optional)

After the server is running, you can call the Agent API to confirm the setup.
Endpoint: **POST** `/api/agent/process`, JSON body, SSE streaming. Single-turn example:

```bash
curl -N -X POST "http://localhost:8088/api/agent/process" \
  -H "Content-Type: application/json" \
  -d '{"input":[{"role":"user","content":[{"type":"text","text":"Hello"}]}],"session_id":"session123"}'
```

Use the same `session_id` for multi-turn.

---

## What to do next

- **Chat with CoPAW** — [Channels](./channels): connect one channel
  (DingTalk or Feishu is a good first), create the app, fill config, then send a message
  in that app.
- **Run a scheduled "check-in" or digest** — [Heartbeat](./heartbeat): edit
  HEARTBEAT.md and set interval and target in config.
- **More commands** — [CLI](./cli) (interactive init, cron jobs, clean),
  [Skills](./skills).
- **Change working dir or config path** — [Config & working dir](./config).
